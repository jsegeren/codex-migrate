"""Read-only inventory of encrypted files needed for one hosted Vault snapshot.

This is a transfer plan, not an upload or evidence of off-device protection.
Every file must be reopened and checked at transfer time; a plan cannot freeze
the local filesystem against a concurrent change.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat
from typing import Optional, Tuple

from codex_migrate.errors import MigrationError
from codex_migrate.vault_backup import _helper_path, _read_json, _require_unlinked_path, _run_helper
from codex_migrate.vault_recovery import _snapshot


MAX_CHUNKS = 1_000_000
MAX_ENCRYPTED_CHUNK_BYTES = 64 * 1024 * 1024 + 1024
MAX_ENCRYPTED_MANIFEST_BYTES = 128 * 1024 * 1024 + 1024


@dataclass(frozen=True)
class EncryptedFile:
    relative_path: str
    bytes: int


@dataclass(frozen=True)
class RemoteInventory:
    snapshot_id: str
    files: Tuple[EncryptedFile, ...]
    ciphertext_bytes: int
    publish_latest: bool


def _regular_file(root: Path, relative: str, maximum: int) -> EncryptedFile:
    path = root / relative
    _require_unlinked_path(path)
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        info = os.fstat(descriptor)
    except OSError as error:
        raise MigrationError("A required encrypted Vault file is unavailable.") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_size <= 0 or info.st_size > maximum):
        raise MigrationError("A required encrypted Vault file is unsafe or unsupported.")
    return EncryptedFile(relative, info.st_size)


def encrypted_snapshot_inventory(
    vault: str,
    *,
    snapshot: str = "latest",
    crypto_helper: Optional[str] = None,
) -> RemoteInventory:
    """Plan a snapshot's exact ciphertext objects without exporting plaintext.

    The native helper authenticates the entire manifest and every referenced
    chunk before returning only opaque chunk identifiers. The caller must not
    treat this inventory as remotely verified or use it without per-file
    no-follow checks while actually streaming a transfer.
    """
    root, key_id, snapshot_id, manifest, objects = _snapshot(vault, snapshot)
    immutable_reference = root / "refs" / (snapshot_id + ".json")
    reference = _read_json(immutable_reference)
    if reference.get("snapshot_id") != snapshot_id:
        raise MigrationError("The immutable Vault reference has the wrong identity.")
    if snapshot == "latest" and reference != _read_json(root / "latest.json"):
        raise MigrationError("The latest Vault reference disagrees with its immutable copy.")

    helper = _helper_path(crypto_helper)
    response = _run_helper(helper, [
        "encrypted-inventory", "--key-id", key_id,
        "--snapshot-id", snapshot_id,
        "--object-dir", str(objects), "--manifest", str(manifest),
    ])
    identifiers = response.get("chunk_ids")
    if (set(response) != {"snapshot_id", "chunk_ids"}
            or response.get("snapshot_id") != snapshot_id
            or not isinstance(identifiers, list) or len(identifiers) > MAX_CHUNKS
            or any(not isinstance(value, str) or len(value) != 64
                   or any(character not in "0123456789abcdef" for character in value)
                   for value in identifiers)
            or identifiers != sorted(set(identifiers))):
        raise MigrationError("The authenticated Vault inventory is invalid.")

    files = [_regular_file(root, "vault.json", 1024 * 1024)]
    for identifier in identifiers:
        files.append(_regular_file(
            root, "objects/" + identifier[:2] + "/" + identifier[2:] + ".cvchunk",
            MAX_ENCRYPTED_CHUNK_BYTES,
        ))
    files.append(_regular_file(
        root, "manifests/" + snapshot_id + ".cvmanifest",
        MAX_ENCRYPTED_MANIFEST_BYTES,
    ))
    files.append(_regular_file(
        root, "refs/" + snapshot_id + ".json", 1024 * 1024,
    ))
    return RemoteInventory(
        snapshot_id=snapshot_id,
        files=tuple(files),
        ciphertext_bytes=sum(item.bytes for item in files),
        publish_latest=snapshot == "latest",
    )
