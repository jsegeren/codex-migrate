"""Prepare one transcript for a future low-local-storage hosted snapshot.

Only previously published objects may be reused without local ciphertext.
This is not snapshot publication or a protection receipt. The caller must
upload every new local object, independently verify every remote object, and
publish the complete manifest before removing any temporary ciphertext.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Mapping, Optional, Protocol, Tuple

from codex_migrate.errors import MigrationError
from codex_migrate.vault_backup import _canonical_macos_path, _helper_path, _run_helper
from codex_migrate.vault_hosted_chunk_journal import HostedChunkJournal
from codex_migrate.vault_remote_inventory import (
    MAX_ENCRYPTED_CHUNK_BYTES, _regular_file,
)
from codex_migrate.vault_remote_transfer import StagedObject, stage_encrypted_object


_HEX = re.compile(r"[0-9a-f]{64}\Z")


class PublishedChunkLookup(Protocol):
    def published_chunks(self, ids: list[str]) -> Mapping[str, Tuple[int, str]]:
        """Return scoped, previously published ciphertext size and digest."""


class ScopedUploadClient(Protocol):
    def object_store(self, reservation_id: str,
                     expected: Mapping[str, Tuple[int, str]], *,
                     apply: bool = False) -> object:
        """Return an exact-key, reservation-scoped ciphertext transport."""


@dataclass(frozen=True)
class PreparedRemoteFile:
    sha256: str
    size: int
    chunks: Tuple[dict, ...]
    local_ids: Tuple[str, ...]
    remote_objects: Mapping[str, Tuple[int, str]]


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _candidate_ids(plan: dict, expected_size: int, chunk_size: int) -> list[str]:
    rows = plan.get("chunks")
    if (set(plan) != {"sha256", "size", "chunks"} or
            not isinstance(plan["sha256"], str) or
            not _HEX.fullmatch(plan["sha256"]) or
            type(plan["size"]) is not int or plan["size"] != expected_size or
            not isinstance(rows, list) or len(rows) > 1_000_000):
        raise MigrationError("The hosted chunk plan is invalid.")
    ids = []
    summed = 0
    for row in rows:
        if (not isinstance(row, dict) or
                set(row) != {"raw_id", "compressed_id", "size", "compressed_bytes"} or
                type(row["size"]) is not int or
                not 1 <= row["size"] <= chunk_size or
                not isinstance(row["raw_id"], str) or
                not _HEX.fullmatch(row["raw_id"]) or
                (row["compressed_id"] is not None and
                 (not isinstance(row["compressed_id"], str) or
                  not _HEX.fullmatch(row["compressed_id"]))) or
                (row["compressed_bytes"] is None) !=
                (row["compressed_id"] is None) or
                (row["compressed_bytes"] is not None and
                 (type(row["compressed_bytes"]) is not int or
                  not 1 <= row["compressed_bytes"] < row["size"]))):
            raise MigrationError("The hosted chunk plan is invalid.")
        summed += row["size"]
        ids.append(row["raw_id"])
        if row["compressed_id"] is not None:
            ids.append(row["compressed_id"])
    if summed != expected_size:
        raise MigrationError("The hosted chunk plan is incomplete.")
    unique = list(dict.fromkeys(ids))
    if len(unique) > 100_000:
        raise MigrationError("The hosted chunk plan is too large for one file.")
    return unique


def prepare_remote_aware_file(source: Path, objects: Path, key_id: str,
                              lookup: PublishedChunkLookup, *,
                              crypto_helper: str, chunk_size: int,
                              apply: bool = False) -> PreparedRemoteFile:
    """Plan, look up published IDs, and encrypt only unknown chunks locally.

    A transcript changed between the two passes fails closed. Even on failure
    the scratch folder may hold encrypted orphan chunks; it is never a Vault
    snapshot and must not be described as a protected backup.
    """
    if apply is not True:
        raise MigrationError("Hosted backup changes require explicit confirmation.")
    if not isinstance(chunk_size, int) or isinstance(chunk_size, bool) or not (
            64 * 1024 <= chunk_size <= 64 * 1024 * 1024):
        raise MigrationError("The hosted chunk size is invalid.")
    helper = _helper_path(crypto_helper)
    root = Path(objects)
    try:
        root_info = root.lstat()
        if (not stat.S_ISDIR(root_info.st_mode) or root_info.st_uid != os.getuid() or
                root_info.st_mode & 0o077):
            raise MigrationError("The hosted scratch folder is not private.")
        source_info = source.lstat()
        if (not stat.S_ISREG(source_info.st_mode) or source_info.st_nlink != 1 or
                source_info.st_uid != os.getuid()):
            raise MigrationError("The conversation is not a regular file.")
        descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as error:
        raise MigrationError("The hosted conversation or scratch folder is unavailable.") from error
    with os.fdopen(descriptor, "rb") as handle:
        before = os.fstat(handle.fileno())
        if _identity(before) != _identity(source_info):
            raise MigrationError("The conversation changed before hosted backup.")
        plan = _run_helper(helper, ["plan-chunks", "--key-id", key_id,
                                    "--chunk-size", str(chunk_size)],
                           input_file=handle)
        candidates = _candidate_ids(plan, before.st_size, chunk_size)
        published: dict[str, Tuple[int, str]] = {}
        for start in range(0, len(candidates), 256):
            page = candidates[start:start + 256]
            observed = lookup.published_chunks(page)
            if not isinstance(observed, Mapping) or not set(observed).issubset(page):
                raise MigrationError("The hosted chunk lookup is invalid.")
            for identifier, facts in observed.items():
                if (not isinstance(identifier, str) or not _HEX.fullmatch(identifier) or
                        not isinstance(facts, tuple) or len(facts) != 2 or
                        type(facts[0]) is not int or not 1 <= facts[0] <= 100_000_000 or
                        not isinstance(facts[1], str) or not _HEX.fullmatch(facts[1])):
                    raise MigrationError("The hosted chunk lookup is invalid.")
                published[identifier] = facts
        if _identity(os.fstat(handle.fileno())) != _identity(before):
            raise MigrationError("The conversation changed during hosted planning.")
        with tempfile.TemporaryDirectory(prefix="codex-vault-known-") as temporary:
            known_path = Path(temporary) / "known.json"
            known_descriptor = os.open(known_path,
                                       os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(known_descriptor, "w", encoding="utf-8") as known_file:
                json.dump({"version": 1, "ids": sorted(published)}, known_file)
            handle.seek(0)
            stored = _run_helper(helper, [
                "store-chunks-with-known", "--key-id", key_id,
                "--object-dir", str(root), "--chunk-size", str(chunk_size),
                "--known-ids-file", str(known_path),
                "--expected-sha256", plan["sha256"],
                "--expected-size", str(plan["size"]),
            ], input_file=handle)
        if (_identity(os.fstat(handle.fileno())) != _identity(before) or
                _identity(source.lstat()) != _identity(before)):
            raise MigrationError("The conversation changed during hosted backup.")
    rows = stored.get("chunks")
    local = stored.get("local_ids")
    remote = stored.get("remote_ids")
    if (set(stored) != {"sha256", "size", "chunks", "local_ids", "remote_ids"} or
            stored["sha256"] != plan["sha256"] or stored["size"] != plan["size"] or
            not isinstance(rows, list) or len(rows) != len(plan["chunks"]) or
            not isinstance(local, list) or not isinstance(remote, list) or
            not all(isinstance(item, str) and _HEX.fullmatch(item)
                    for item in local + remote) or
            len(local) + len(remote) != len(rows)):
        raise MigrationError("The hosted chunk writer returned an invalid result.")
    for row, candidate in zip(rows, plan["chunks"]):
        if (not isinstance(row, dict) or
                set(row) not in ({"id", "size"}, {"id", "size", "encoding"}) or
                row.get("size") != candidate["size"] or
                row.get("id") not in (candidate["raw_id"], candidate["compressed_id"]) or
                ("encoding" in row) != (row["id"] == candidate["compressed_id"]) or
                ("encoding" in row and row["encoding"] != "lzfse")):
            raise MigrationError("The hosted chunk writer returned an invalid result.")
    if (set(local) | set(remote) != {row["id"] for row in rows} or
            set(local) & set(remote) or not set(remote).issubset(published)):
        raise MigrationError("The hosted chunk writer returned an invalid result.")
    return PreparedRemoteFile(plan["sha256"], plan["size"],
                              tuple(rows), tuple(local),
                              {key: published[key] for key in set(remote)})


def stage_prepared_file(prepared: PreparedRemoteFile, scratch: Path,
                        client: ScopedUploadClient, reservation_id: str, *,
                        journal: Optional[HostedChunkJournal] = None,
                        apply: bool = False) -> Tuple[StagedObject, ...]:
    """Check old remote ciphertext and upload new encrypted chunks for one file.

    `scratch` is the same private object directory supplied to
    `prepare_remote_aware_file`. With a journal, each new chunk is recorded
    only after exact remote verification. This still leaves scratch in place:
    the complete remote-aware retry and publication flow is not proven yet.
    """
    if apply is not True:
        raise MigrationError("Hosted upload changes require explicit confirmation.")
    if not isinstance(prepared, PreparedRemoteFile):
        raise MigrationError("The hosted prepared file is invalid.")
    if journal is not None and (not isinstance(journal, HostedChunkJournal) or
                                journal.reservation_id != reservation_id):
        raise MigrationError("The hosted chunk journal does not match this reservation.")
    local = set(prepared.local_ids)
    remote = set(prepared.remote_objects)
    if (local & remote or
            any(not isinstance(row, dict) for row in prepared.chunks) or
            local | remote != {row["id"] for row in prepared.chunks}):
        raise MigrationError("The hosted prepared file is incomplete.")
    root = _canonical_macos_path(Path(scratch))
    objects = []
    for identifier in sorted(remote):
        size, digest = prepared.remote_objects[identifier]
        key = "objects/" + identifier[:2] + "/" + identifier[2:] + ".cvchunk"
        store = client.object_store(reservation_id, {key: (size, digest)}, apply=True)
        checked = getattr(store, "checked_metadata", None)
        if not callable(checked) or checked(key) != (size, digest):
            raise MigrationError("A previously published Vault chunk is missing remotely.")
        objects.append(StagedObject(key, size, digest))
    for identifier in sorted(local):
        key = "objects/" + identifier[:2] + "/" + identifier[2:] + ".cvchunk"
        relative = identifier[:2] + "/" + identifier[2:] + ".cvchunk"
        item = _regular_file(root, relative, MAX_ENCRYPTED_CHUNK_BYTES,
                             remote_key=key)
        store = client.object_store(reservation_id,
                                    {key: (item.bytes, item.sha256)}, apply=True)
        staged, _ = stage_encrypted_object(root, item, store)
        if journal is not None:
            journal.record(identifier, staged.bytes, staged.sha256)
        objects.append(staged)
    return tuple(sorted(objects, key=lambda item: item.key))
