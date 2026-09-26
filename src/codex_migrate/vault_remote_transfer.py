"""Stage a Vault snapshot in an account-scoped object store without publishing it.

The store is supplied by a separate authenticated service. This module never
receives bucket credentials, signs URLs, advances a remote latest pointer, or
claims that a staged snapshot is protected. The service must verify and commit
that pointer after its own completeness, entitlement, and quota checks.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
from typing import BinaryIO, Iterator, Optional, Protocol, Tuple

from codex_migrate.errors import MigrationError
from codex_migrate.vault_recovery import _vault_root
from codex_migrate.vault_remote_inventory import (
    VaultTransferFile, encrypted_snapshot_inventory,
)


BLOCK_BYTES = 1024 * 1024


class ScopedObjectStore(Protocol):
    """An already account- and Vault-scoped store; keys are relative paths."""

    def open_read(self, key: str) -> Optional[BinaryIO]:
        """Return a readable object, or None when it does not exist."""

    def put_if_absent(self, key: str, source: BinaryIO, length: int) -> None:
        """Atomically store exactly length bytes without replacing an object."""


@dataclass(frozen=True)
class StagedObject:
    """Client-observed ciphertext object; the service must verify it itself."""

    key: str
    bytes: int
    sha256: str


@dataclass(frozen=True)
class StageResult:
    snapshot_id: str
    uploaded_files: int
    reused_files: int
    remote_bytes_checked: int
    objects: Tuple[StagedObject, ...]


@contextmanager
def _open_vault_file(root: Path, item: VaultTransferFile) -> Iterator[BinaryIO]:
    """Open every directory component without following a late-swapped link."""
    relative = Path(item.relative_path)
    if (relative.is_absolute() or not relative.parts
            or any(part in (".", "..") for part in relative.parts)):
        raise MigrationError("The Vault transfer contains an unsafe path.")
    parts = root.parts[1:] + relative.parts
    directory = -1
    descriptor = -1
    file_descriptor = -1
    try:
        directory = os.open(root.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for part in parts[:-1]:
            next_directory = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=directory,
            )
            os.close(directory)
            directory = next_directory
        descriptor = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=directory,
        )
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_size != item.bytes):
            raise MigrationError("A Vault file changed after inventory verification.")
        file_descriptor, descriptor = descriptor, -1
    except OSError as error:
        raise MigrationError("A Vault file changed or is unavailable for transfer.") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if directory >= 0:
            os.close(directory)
    with os.fdopen(file_descriptor, "rb") as handle:
        yield handle


def _digest(stream: BinaryIO, expected_size: int) -> str:
    hasher = hashlib.sha256()
    total = 0
    while True:
        block = stream.read(BLOCK_BYTES)
        if not block:
            break
        total += len(block)
        if total > expected_size:
            raise MigrationError("A Vault transfer file has an unexpected size.")
        hasher.update(block)
    if total != expected_size:
        raise MigrationError("A Vault transfer file is incomplete.")
    return hasher.hexdigest()


def _remote_digest(store: ScopedObjectStore, item: VaultTransferFile) -> Optional[str]:
    stream = store.open_read(item.remote_key)
    if stream is None:
        return None
    with stream:
        return _digest(stream, item.bytes)


def stage_encrypted_snapshot(
    vault: str,
    store: ScopedObjectStore,
    *,
    snapshot: str = "latest",
    crypto_helper: Optional[str] = None,
) -> StageResult:
    """Copy and read back one authenticated snapshot's portable Vault files.

    No remote latest pointer is written. A missing or altered remote object
    fails closed, leaving any previously published snapshot untouched. Retrying
    reuses already verified immutable objects and uploads only missing ones.
    """
    inventory = encrypted_snapshot_inventory(
        vault, snapshot=snapshot, crypto_helper=crypto_helper)
    root = _vault_root(vault)
    uploaded = reused = checked_bytes = 0
    staged_objects = []
    for item in inventory.files:
        with _open_vault_file(root, item) as source:
            local_digest = _digest(source, item.bytes)
            remote_digest = _remote_digest(store, item)
            if remote_digest is None:
                source.seek(0)
                store.put_if_absent(item.remote_key, source, item.bytes)
                if source.tell() != item.bytes:
                    raise MigrationError("The object store did not consume the Vault file exactly.")
                uploaded += 1
                remote_digest = _remote_digest(store, item)
            else:
                reused += 1
            if remote_digest != local_digest:
                raise MigrationError("A remote Vault object is missing or differs from its local version.")
            checked_bytes += item.bytes
            staged_objects.append(StagedObject(item.remote_key, item.bytes, remote_digest))
    current = encrypted_snapshot_inventory(
        vault, snapshot=snapshot, crypto_helper=crypto_helper)
    if current != inventory:
        raise MigrationError("The local Vault snapshot changed during remote staging.")
    return StageResult(
        snapshot_id=inventory.snapshot_id,
        uploaded_files=uploaded,
        reused_files=reused,
        remote_bytes_checked=checked_bytes,
        objects=tuple(staged_objects),
    )
