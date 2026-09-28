"""Validate the ciphertext graph before submitting a dark hosted snapshot.

The service must still independently verify every object in R2 and publish
last-good. This module does not claim that staged data is a backup.
"""

from __future__ import annotations

import re
from typing import Mapping, Tuple

from codex_migrate.errors import MigrationError
from codex_migrate.vault_identity import canonical_id
from codex_migrate.vault_remote_inventory import (
    MAX_CHUNKS, MAX_ENCRYPTED_CHUNK_BYTES, MAX_ENCRYPTED_MANIFEST_BYTES,
)
from codex_migrate.vault_remote_transfer import StagedObject
from codex_migrate.vault_remote_writer import StagedRemoteFile


_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")


def _object(item: StagedObject, expected_key: str, maximum: int) -> None:
    if (not isinstance(item, StagedObject) or item.key != expected_key or
            type(item.bytes) is not int or not 1 <= item.bytes <= maximum or
            not isinstance(item.sha256, str) or not _HEX.fullmatch(item.sha256)):
        raise MigrationError("A hosted snapshot object has invalid verified facts.")


def staged_snapshot_objects(
    snapshot_id: str, manifest: dict,
    staged_files: Mapping[Tuple[str, str], StagedRemoteFile],
    metadata: StagedObject, sealed_manifest: StagedObject,
    reference: StagedObject,
) -> Tuple[StagedObject, ...]:
    """Bind a v2/v3 manifest's exact chunks to staged ciphertext facts.

    The caller separately seals and stages the *same* manifest bytes. This
    check catches missing, extra, or conflicting chunk claims before receipt
    pages reach the service; it cannot replace authenticated manifest opening
    or the service's provider-side publication verification.
    """
    if not isinstance(snapshot_id, str) or not _UUID.fullmatch(snapshot_id):
        raise MigrationError("The hosted snapshot identity is invalid.")
    if (not isinstance(manifest, dict) or
            set(manifest) != {"format", "version", "snapshot_id", "created_at", "files"} or
            manifest["format"] != "codex-vault-snapshot" or
            type(manifest["version"]) is not int or
            manifest["version"] not in (2, 3) or
            manifest["snapshot_id"] != snapshot_id or
            not isinstance(manifest["created_at"], str) or
            not isinstance(manifest["files"], list) or
            len(manifest["files"]) > 100_000 or
            not isinstance(staged_files, Mapping)):
        raise MigrationError("The hosted snapshot manifest is invalid.")
    _object(metadata, "metadata/" + snapshot_id + ".json", 1024 * 1024)
    _object(sealed_manifest, "manifests/" + snapshot_id + ".cvmanifest",
            MAX_ENCRYPTED_MANIFEST_BYTES)
    _object(reference, "refs/" + snapshot_id + ".json", 1024 * 1024)
    seen_files = set()
    chunks: dict[str, StagedObject] = {}
    chunk_shapes: dict[str, Tuple[int, str]] = {}
    for file in manifest["files"]:
        if not isinstance(file, dict):
            raise MigrationError("The hosted snapshot contains an invalid transcript.")
        collection, path = file.get("collection"), file.get("path")
        if (collection not in ("active", "archived", "paginated") or
                not isinstance(path, str) or not path or path.startswith("/") or
                "\\" in path or "\0" in path or
                any(part in ("", ".", "..") for part in path.split("/"))):
            raise MigrationError("The hosted snapshot contains an unsafe transcript path.")
        thread_id = file.get("thread_id")
        if collection == "paginated" and (
                manifest["version"] != 3 or canonical_id(thread_id) != thread_id or
                path != thread_id + ".jsonl" or file.get("mtime_ns") != 0 or
                file.get("identity_state") != "verified" or
                type(file.get("records")) is not int or file["records"] < 1):
            raise MigrationError("The hosted snapshot has invalid paginated history.")
        if (set(file) != {"collection", "path", "size", "mtime_ns", "sha256",
                          "chunks", "thread_id", "identity_state", "titles",
                          "records", "assistant_messages", "user_messages", "at_risk"} or
                type(file["mtime_ns"]) is not int or file["mtime_ns"] < 0 or
                file["identity_state"] not in ("verified", "unverified", "needs_review") or
                (thread_id is not None and canonical_id(thread_id) != thread_id) or
                (file["identity_state"] == "verified" and thread_id is None) or
                not isinstance(file["titles"], list) or len(file["titles"]) > 64 or
                any(not isinstance(title, str) or len(title) > 500 or "\0" in title
                    for title in file["titles"]) or
                any(type(file[key]) is not int or file[key] < 0 for key in
                    ("records", "assistant_messages", "user_messages")) or
                type(file["at_risk"]) is not bool):
            raise MigrationError("The hosted snapshot contains invalid identity metadata.")
        identity = (collection, path)
        if identity in seen_files:
            raise MigrationError("The hosted snapshot has a duplicate transcript path.")
        seen_files.add(identity)
        stage = staged_files.get(identity)
        if (not isinstance(stage, StagedRemoteFile) or
                type(stage.size) is not int or stage.size < 0 or
                type(file.get("size")) is not int or
                file.get("size") != stage.size or
                not isinstance(stage.sha256, str) or
                not _HEX.fullmatch(stage.sha256) or
                file.get("sha256") != stage.sha256 or
                file.get("chunks") != list(stage.chunks)):
            raise MigrationError("A hosted transcript does not match its staged content.")
        required = set()
        total_size = 0
        for row in stage.chunks:
            if (not isinstance(row, dict) or
                    set(row) not in ({"id", "size"}, {"id", "size", "encoding"}) or
                    not isinstance(row.get("id"), str) or
                    not _HEX.fullmatch(row["id"]) or
                    type(row.get("size")) is not int or
                    not 1 <= row["size"] <= 64 * 1024 * 1024 or
                    ("encoding" in row and row["encoding"] != "lzfse")):
                raise MigrationError("A hosted transcript has invalid chunk metadata.")
            total_size += row["size"]
            shape = (row["size"], row.get("encoding", "raw"))
            if row["id"] in chunk_shapes and chunk_shapes[row["id"]] != shape:
                raise MigrationError("A hosted chunk has conflicting plaintext metadata.")
            chunk_shapes[row["id"]] = shape
            required.add("objects/" + row["id"][:2] + "/" +
                         row["id"][2:] + ".cvchunk")
        if total_size != stage.size:
            raise MigrationError("A hosted transcript is missing plaintext chunks.")
        actual = {}
        for item in stage.objects:
            if not isinstance(item, StagedObject) or item.key in actual:
                raise MigrationError("A hosted transcript has duplicate staged objects.")
            actual[item.key] = item
        if set(actual) != required:
            raise MigrationError("A hosted transcript has missing or extra staged objects.")
        for key, item in actual.items():
            _object(item, key, MAX_ENCRYPTED_CHUNK_BYTES)
            if key in chunks and chunks[key] != item:
                raise MigrationError("A hosted chunk has conflicting staged ciphertext.")
            chunks[key] = item
        if len(chunks) > MAX_CHUNKS:
            raise MigrationError("The hosted snapshot has too many chunks.")
    if seen_files != set(staged_files):
        raise MigrationError("The hosted snapshot has unstated staged transcripts.")
    return (metadata, *(chunks[key] for key in sorted(chunks)),
            sealed_manifest, reference)
