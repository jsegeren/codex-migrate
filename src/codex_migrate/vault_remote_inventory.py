"""Read-only inventory of portable files needed for one hosted Vault snapshot.

This is a transfer plan, not an upload or evidence of off-device protection.
Every file must be reopened and checked at transfer time; a plan cannot freeze
the local filesystem against a concurrent change.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
from typing import Optional, Tuple

from codex_migrate.errors import MigrationError
from codex_migrate.vault_backup import _helper_path, _read_json, _require_unlinked_path, _run_helper
from codex_migrate.vault_recovery import _snapshot


# Publication accepts at most one million objects including the required
# metadata, manifest, and immutable reference.
MAX_CHUNKS = 999_997
MAX_ENCRYPTED_CHUNK_BYTES = 64 * 1024 * 1024 + 1024
# The first hosted transport uses a Worker that refuses bodies above 100 MB.
# Fail during planning, before uploading any objects the service cannot publish.
MAX_ENCRYPTED_MANIFEST_BYTES = 100 * 1000 * 1000


@dataclass(frozen=True)
class VaultTransferFile:
    relative_path: str
    remote_key: str
    bytes: int
    sha256: str


@dataclass(frozen=True)
class RemoteInventory:
    snapshot_id: str
    files: Tuple[VaultTransferFile, ...]
    transfer_bytes: int
    is_current_latest: bool


def _regular_file(
    root: Path, relative: str, maximum: int, *, remote_key: Optional[str] = None,
    verified_sha256: Optional[str] = None,
) -> VaultTransferFile:
    path = root / relative
    _require_unlinked_path(path)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as error:
        raise MigrationError("A required Vault file is unavailable.") from error
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_uid != os.geteuid() or before.st_mode & 0o077
                or before.st_size <= 0 or before.st_size > maximum):
            raise MigrationError("A required Vault file is unsafe or unsupported.")
        if verified_sha256 is None:
            digest = hashlib.sha256()
            while block := stream.read(1024 * 1024):
                digest.update(block)
            verified_sha256 = digest.hexdigest()
            after = os.fstat(stream.fileno())
            if (before.st_dev, before.st_ino, before.st_size,
                    before.st_mtime_ns, before.st_ctime_ns) != (
                    after.st_dev, after.st_ino, after.st_size,
                    after.st_mtime_ns, after.st_ctime_ns):
                raise MigrationError("A required Vault file changed during inventory.")
    if (len(verified_sha256) != 64 or
            any(character not in "0123456789abcdef" for character in verified_sha256)):
        raise MigrationError("The authenticated Vault object digest is invalid.")
    return VaultTransferFile(relative, remote_key or relative, before.st_size,
                             verified_sha256)


def encrypted_snapshot_inventory(
    vault: str,
    *,
    snapshot: str = "latest",
    crypto_helper: Optional[str] = None,
) -> RemoteInventory:
    """Plan a snapshot's exact Vault files without exporting conversation text.

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
    digests = response.get("chunk_sha256")
    manifest_digest = response.get("manifest_sha256")
    if (set(response) != {"snapshot_id", "chunk_ids", "chunk_sha256", "manifest_sha256"}
            or response.get("snapshot_id") != snapshot_id
            or not isinstance(identifiers, list) or len(identifiers) > MAX_CHUNKS
            or any(not isinstance(value, str) or len(value) != 64
                   or any(character not in "0123456789abcdef" for character in value)
                   for value in identifiers)
            or identifiers != sorted(set(identifiers))
            or not isinstance(digests, dict) or set(digests) != set(identifiers)
            or any(not isinstance(value, str) or len(value) != 64
                   or any(character not in "0123456789abcdef" for character in value)
                   for value in digests.values())
            or not isinstance(manifest_digest, str) or len(manifest_digest) != 64
            or any(character not in "0123456789abcdef" for character in manifest_digest)):
        raise MigrationError("The authenticated Vault inventory is invalid.")

    files = [_regular_file(
        root, "vault.json", 1024 * 1024,
        remote_key="metadata/" + snapshot_id + ".json",
    )]
    for identifier in identifiers:
        files.append(_regular_file(
            root, "objects/" + identifier[:2] + "/" + identifier[2:] + ".cvchunk",
            MAX_ENCRYPTED_CHUNK_BYTES, verified_sha256=digests[identifier],
        ))
    files.append(_regular_file(
        root, "manifests/" + snapshot_id + ".cvmanifest",
        MAX_ENCRYPTED_MANIFEST_BYTES, verified_sha256=manifest_digest,
    ))
    files.append(_regular_file(
        root, "refs/" + snapshot_id + ".json", 1024 * 1024,
    ))
    return RemoteInventory(
        snapshot_id=snapshot_id,
        files=tuple(files),
        transfer_bytes=sum(item.bytes for item in files),
        is_current_latest=snapshot == "latest",
    )
