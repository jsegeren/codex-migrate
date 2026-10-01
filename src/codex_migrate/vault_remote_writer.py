"""Dark remote-aware transcript staging for a future hosted snapshot.

Previously published or same-reservation journaled objects may be reused only
after exact remote checks. The windowed path discards *its own* scratch chunks
after their fsynced receipts; it never discards a customer's durable local
Vault. Staging is not publication or a protection receipt: the service must
independently verify and publish the complete snapshot before any such claim.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Iterable, Mapping, Optional, Protocol, Tuple

from codex_migrate.errors import MigrationError
from codex_migrate.vault_backup import _canonical_macos_path, _helper_path, _run_helper
from codex_migrate.vault_hosted_chunk_journal import HostedChunkJournal
from codex_migrate.vault_remote_inventory import (
    MAX_CHUNKS, MAX_ENCRYPTED_CHUNK_BYTES, _regular_file,
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


class RemoteAwareClient(PublishedChunkLookup, ScopedUploadClient, Protocol):
    """The same authenticated client must own lookup and upload."""


@dataclass(frozen=True)
class PreparedRemoteFile:
    sha256: str
    size: int
    chunks: Tuple[dict, ...]
    local_ids: Tuple[str, ...]
    remote_objects: Mapping[str, Tuple[int, str]]


@dataclass(frozen=True)
class StagedRemoteFile:
    """One fully staged transcript, not a published or recoverable snapshot."""

    sha256: str
    size: int
    chunks: Tuple[dict, ...]
    objects: Tuple[StagedObject, ...]


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
                set(row) not in ({"raw_id", "size"},
                                 {"raw_id", "compressed_id", "size", "compressed_bytes"}) or
                type(row["size"]) is not int or
                not 1 <= row["size"] <= chunk_size or
                not isinstance(row["raw_id"], str) or
                not _HEX.fullmatch(row["raw_id"]) or
                (row.get("compressed_id") is not None and
                 (not isinstance(row["compressed_id"], str) or
                  not _HEX.fullmatch(row["compressed_id"]))) or
                (row.get("compressed_bytes") is None) !=
                (row.get("compressed_id") is None) or
                (row.get("compressed_bytes") is not None and
                 (type(row["compressed_bytes"]) is not int or
                  not 1 <= row["compressed_bytes"] < row["size"]))):
            raise MigrationError("The hosted chunk plan is invalid.")
        summed += row["size"]
        ids.append(row["raw_id"])
        if row.get("compressed_id") is not None:
            ids.append(row["compressed_id"])
    if summed != expected_size:
        raise MigrationError("The hosted chunk plan is incomplete.")
    unique = list(dict.fromkeys(ids))
    if len(unique) > 100_000:
        raise MigrationError("The hosted chunk plan is too large for one file.")
    return unique


def _reusable_chunks(candidates: list[str], lookup: PublishedChunkLookup,
                     journal: Optional[HostedChunkJournal],
                     reservation_id: Optional[str]) -> dict[str, Tuple[int, str]]:
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
    reusable = dict(published)
    if journal is not None:
        journal.ensure_open()
        object_store = getattr(lookup, "object_store", None)
        for identifier in candidates:
            facts = journal.fact(identifier)
            if facts is None:
                continue
            if identifier in published:
                if published[identifier] != facts:
                    raise MigrationError("A hosted chunk has conflicting remote receipts.")
                continue
            key = "objects/" + identifier[:2] + "/" + identifier[2:] + ".cvchunk"
            if not callable(object_store):
                raise MigrationError("The hosted chunk lookup cannot verify staged objects.")
            store = object_store(reservation_id, {key: facts}, apply=True)
            checked = getattr(store, "checked_metadata", None)
            if not callable(checked):
                raise MigrationError("The hosted chunk lookup cannot verify staged objects.")
            if checked(key) != facts:
                raise MigrationError("A staged hosted chunk is missing or changed remotely.")
            reusable[identifier] = facts
    return reusable


def _validated_prepared(stored: dict, plan: dict,
                        reusable: Mapping[str, Tuple[int, str]]) -> PreparedRemoteFile:
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
                row.get("id") not in (candidate["raw_id"], candidate.get("compressed_id")) or
                ("encoding" in row) != (row["id"] == candidate.get("compressed_id")) or
                ("encoding" in row and row["encoding"] != "lzfse")):
            raise MigrationError("The hosted chunk writer returned an invalid result.")
    if (set(local) | set(remote) != {row["id"] for row in rows} or
            set(local) & set(remote) or not set(remote).issubset(reusable)):
        raise MigrationError("The hosted chunk writer returned an invalid result.")
    return PreparedRemoteFile(plan["sha256"], plan["size"], tuple(rows),
                              tuple(local), {key: reusable[key] for key in set(remote)})


def prepare_remote_aware_file(source: Path, objects: Path, key_id: str,
                              lookup: PublishedChunkLookup, *,
                              crypto_helper: str, chunk_size: int,
                              journal: Optional[HostedChunkJournal] = None,
                              reservation_id: Optional[str] = None,
                              apply: bool = False) -> PreparedRemoteFile:
    """Plan, verify reusable remote IDs, and encrypt only unknown chunks locally.

    A transcript changed between the two passes fails closed. Even on failure
    the scratch folder may hold encrypted orphan chunks; it is never a Vault
    snapshot and must not be described as a protected backup.
    """
    if apply is not True:
        raise MigrationError("Hosted backup changes require explicit confirmation.")
    if not isinstance(chunk_size, int) or isinstance(chunk_size, bool) or not (
            64 * 1024 <= chunk_size <= 64 * 1024 * 1024):
        raise MigrationError("The hosted chunk size is invalid.")
    if ((journal is None) != (reservation_id is None) or
            (journal is not None and
             (not isinstance(journal, HostedChunkJournal) or
              journal.reservation_id != reservation_id or
              journal.key_id != key_id))):
        raise MigrationError("The hosted chunk journal does not match this reservation.")
    if journal is not None:
        journal.ensure_open()
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
        reusable = _reusable_chunks(candidates, lookup, journal, reservation_id)
        if _identity(os.fstat(handle.fileno())) != _identity(before):
            raise MigrationError("The conversation changed during hosted planning.")
        with tempfile.TemporaryDirectory(prefix="codex-vault-known-") as temporary:
            known_path = Path(temporary) / "known.json"
            known_descriptor = os.open(known_path,
                                       os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(known_descriptor, "w", encoding="utf-8") as known_file:
                json.dump({"version": 1, "ids": sorted(reusable)}, known_file)
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
    return _validated_prepared(stored, plan, reusable)


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
    if journal is not None:
        journal.ensure_open()
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


def _private_scratch(journal: HostedChunkJournal) -> Path:
    journal.ensure_private_directory()
    root = journal.directory / "scratch"
    try:
        root.mkdir(mode=0o700)
    except FileExistsError:
        pass
    info = root.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or
            info.st_mode & 0o077):
        raise MigrationError("The hosted ciphertext scratch folder is unsafe.")
    return root


def _discard_journaled_scratch(root: Path, identifiers: Tuple[str, ...],
                               journal: HostedChunkJournal, *,
                               allow_missing: bool = False) -> None:
    """Remove only our exact ciphertext after its fsynced remote receipt."""
    if root != journal.directory / "scratch":
        raise MigrationError("The hosted ciphertext scratch folder is not owned by this run.")
    journal.ensure_private_directory()
    for identifier in sorted(set(identifiers)):
        facts = journal.fact(identifier)
        if facts is None:
            raise MigrationError("A hosted chunk cannot be discarded before its receipt.")
        relative = identifier[:2] + "/" + identifier[2:] + ".cvchunk"
        path = root / relative
        if allow_missing and not os.path.lexists(path):
            continue
        item = _regular_file(root, relative, MAX_ENCRYPTED_CHUNK_BYTES)
        if (item.bytes, item.sha256) != facts:
            raise MigrationError("A hosted scratch chunk changed after remote verification.")
        before = path.lstat()
        directory = os.open(path.parent,
                            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            pointed = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
            if _identity(pointed) != _identity(before):
                raise MigrationError("A hosted scratch chunk changed before cleanup.")
            os.unlink(path.name, dir_fd=directory)
            os.fsync(directory)
        finally:
            os.close(directory)


def stage_remote_aware_file_windowed(
    source: Path, key_id: str, client: RemoteAwareClient,
    reservation_id: str, journal: HostedChunkJournal, *,
    crypto_helper: str, chunk_size: int = 4 * 1024 * 1024,
    window_bytes: int = 64 * 1024 * 1024, apply: bool = False,
) -> StagedRemoteFile:
    """Stage one transcript with bounded scratch and a recoverable retry path.

    The source is planned before upload and rechecked after all windows. A
    failed window retains its scratch ciphertext for an exact retry; a fully
    staged window removes only ciphertext with durable remote receipts. This
    does not assemble or publish a snapshot.
    """
    if apply is not True:
        raise MigrationError("Hosted backup changes require explicit confirmation.")
    if (not isinstance(journal, HostedChunkJournal) or
            journal.reservation_id != reservation_id or journal.key_id != key_id):
        raise MigrationError("The hosted chunk journal does not match this reservation.")
    journal.ensure_open()
    if (type(chunk_size) is not int or not 64 * 1024 <= chunk_size <= 64 * 1024 * 1024 or
            type(window_bytes) is not int or not chunk_size <= window_bytes <= 256 * 1024 * 1024 or
            window_bytes % chunk_size):
        raise MigrationError("The hosted staging window is invalid.")
    helper = _helper_path(crypto_helper)
    source = _canonical_macos_path(Path(source))
    if source == journal.directory or journal.directory in source.parents:
        raise MigrationError("The hosted source cannot be its own scratch folder.")
    scratch = _private_scratch(journal)
    try:
        source_info = source.lstat()
        if (not stat.S_ISREG(source_info.st_mode) or source_info.st_nlink != 1 or
                source_info.st_uid != os.getuid()):
            raise MigrationError("The conversation is not a regular file.")
        descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as error:
        raise MigrationError("The hosted conversation is unavailable.") from error
    with os.fdopen(descriptor, "rb") as handle:
        before = os.fstat(handle.fileno())
        if _identity(before) != _identity(source_info):
            raise MigrationError("The conversation changed before hosted backup.")
        plan = _run_helper(helper, ["plan-chunks", "--key-id", key_id,
                                    "--chunk-size", str(chunk_size)],
                           input_file=handle)
        _candidate_ids(plan, before.st_size, chunk_size)
        if (_identity(os.fstat(handle.fileno())) != _identity(before) or
                _identity(source.lstat()) != _identity(before)):
            raise MigrationError("The conversation changed during hosted planning.")
        handle.seek(0)
        total = 0
        whole_digest = hashlib.sha256()
        rows = []
        objects: dict[str, StagedObject] = {}
        while total < before.st_size:
            needed = min(window_bytes, before.st_size - total)
            blocks = []
            remaining = needed
            while remaining:
                block = handle.read(remaining)
                if not block:
                    raise MigrationError("The conversation changed during hosted staging.")
                blocks.append(block)
                remaining -= len(block)
            window = b"".join(blocks)
            whole_digest.update(window)
            first = total // chunk_size
            count = (needed + chunk_size - 1) // chunk_size
            window_plan = {"sha256": hashlib.sha256(window).hexdigest(),
                           "size": needed,
                           "chunks": plan["chunks"][first:first + count]}
            candidates = _candidate_ids(window_plan, needed, chunk_size)
            reusable = _reusable_chunks(candidates, client, journal, reservation_id)
            with tempfile.TemporaryDirectory(prefix="known-", dir=journal.directory) as tmp:
                known_path = Path(tmp) / "known.json"
                known_descriptor = os.open(known_path,
                                           os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(known_descriptor, "w", encoding="utf-8") as known_file:
                    json.dump({"version": 1, "ids": sorted(reusable)}, known_file)
                stored = _run_helper(helper, [
                    "store-chunks-with-known", "--key-id", key_id,
                    "--object-dir", str(scratch), "--chunk-size", str(chunk_size),
                    "--known-ids-file", str(known_path),
                    "--expected-sha256", window_plan["sha256"],
                    "--expected-size", str(needed),
                ], input_data=window)
            prepared = _validated_prepared(stored, window_plan, reusable)
            staged = stage_prepared_file(prepared, scratch, client,
                                         reservation_id, journal=journal, apply=True)
            for item in staged:
                existing = objects.get(item.key)
                if existing is not None and existing != item:
                    raise MigrationError("A hosted chunk has conflicting staged versions.")
                objects[item.key] = item
            _discard_journaled_scratch(scratch, prepared.local_ids, journal)
            old_scratch = tuple(
                identifier for identifier, facts in prepared.remote_objects.items()
                if journal.fact(identifier) == facts)
            _discard_journaled_scratch(scratch, old_scratch, journal,
                                       allow_missing=True)
            rows.extend(prepared.chunks)
            total += needed
        if (whole_digest.hexdigest() != plan["sha256"] or
                _identity(os.fstat(handle.fileno())) != _identity(before) or
                _identity(source.lstat()) != _identity(before)):
            raise MigrationError("The conversation changed during hosted staging.")
    return StagedRemoteFile(plan["sha256"], plan["size"], tuple(rows),
                            tuple(objects[key] for key in sorted(objects)))


def stage_remote_aware_records(
    records: Iterable[bytes], key_id: str, client: RemoteAwareClient,
    reservation_id: str, journal: HostedChunkJournal, *,
    crypto_helper: str, chunk_size: int = 4 * 1024 * 1024,
    window_bytes: int = 64 * 1024 * 1024, apply: bool = False,
) -> StagedRemoteFile:
    """Encrypt a generated history stream in bounded windows, with no plaintext file.

    The caller pins the source read transaction. Each ciphertext window is
    verified remotely and journaled before its temporary local chunks are
    discarded; the complete manifest is still required for publication.
    """
    if apply is not True:
        raise MigrationError("Hosted backup changes require explicit confirmation.")
    if (not isinstance(journal, HostedChunkJournal) or
            journal.reservation_id != reservation_id or journal.key_id != key_id):
        raise MigrationError("The hosted chunk journal does not match this reservation.")
    journal.ensure_open()
    if (type(chunk_size) is not int or not 64 * 1024 <= chunk_size <= 64 * 1024 * 1024 or
            type(window_bytes) is not int or not chunk_size <= window_bytes <= 256 * 1024 * 1024 or
            window_bytes % chunk_size):
        raise MigrationError("The hosted staging window is invalid.")
    helper = _helper_path(crypto_helper)
    scratch = _private_scratch(journal)
    pending = bytearray()
    whole_digest = hashlib.sha256()
    total = 0
    rows: list[dict] = []
    objects: dict[str, StagedObject] = {}

    def stage_window() -> None:
        window = bytes(pending)
        plan = _run_helper(helper, ["plan-chunks", "--key-id", key_id,
                                    "--chunk-size", str(chunk_size)],
                           input_data=window)
        candidates = _candidate_ids(plan, len(window), chunk_size)
        reusable = _reusable_chunks(candidates, client, journal, reservation_id)
        with tempfile.TemporaryDirectory(prefix="known-", dir=journal.directory) as tmp:
            known_path = Path(tmp) / "known.json"
            known_descriptor = os.open(known_path,
                                       os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(known_descriptor, "w", encoding="utf-8") as known_file:
                json.dump({"version": 1, "ids": sorted(reusable)}, known_file)
            stored = _run_helper(helper, [
                "store-chunks-with-known", "--key-id", key_id,
                "--object-dir", str(scratch), "--chunk-size", str(chunk_size),
                "--known-ids-file", str(known_path),
                "--expected-sha256", plan["sha256"],
                "--expected-size", str(plan["size"]),
            ], input_data=window)
        prepared = _validated_prepared(stored, plan, reusable)
        staged = stage_prepared_file(prepared, scratch, client,
                                     reservation_id, journal=journal, apply=True)
        for item in staged:
            existing = objects.get(item.key)
            if existing is not None and existing != item:
                raise MigrationError("A hosted chunk has conflicting staged versions.")
            objects[item.key] = item
        _discard_journaled_scratch(scratch, prepared.local_ids, journal)
        old_scratch = tuple(
            identifier for identifier, facts in prepared.remote_objects.items()
            if journal.fact(identifier) == facts)
        _discard_journaled_scratch(scratch, old_scratch, journal,
                                   allow_missing=True)
        rows.extend(prepared.chunks)
        if len(rows) > MAX_CHUNKS:
            raise MigrationError("The hosted stream has too many chunks.")
        pending.clear()

    for record in records:
        if not isinstance(record, bytes) or not record:
            raise MigrationError("The hosted history stream has an invalid record.")
        remaining = memoryview(record)
        while remaining:
            count = min(window_bytes - len(pending), len(remaining))
            fragment = remaining[:count]
            pending.extend(fragment)
            whole_digest.update(fragment)
            total += count
            remaining = remaining[count:]
            if len(pending) == window_bytes:
                stage_window()
    if pending:
        stage_window()
    if total == 0:
        raise MigrationError("The hosted history stream is empty.")
    return StagedRemoteFile(whole_digest.hexdigest(), total, tuple(rows),
                            tuple(objects[key] for key in sorted(objects)))
