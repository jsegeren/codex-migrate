"""Rebuild one hosted snapshot as a separate, verified local Vault.

The caller supplies an authenticated, account-scoped read store and the
service's published object receipt. This module does not authenticate the
customer or grant download capabilities. It never writes into live Codex data.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import BinaryIO, Dict, List, Optional, Protocol, Tuple

from codex_migrate.errors import MigrationError
from codex_migrate.vault_backup import (
    _helper_path, _metadata, _read_json, _run_helper, _validate_destination,
)
from codex_migrate.vault_recovery import verify_snapshot
from codex_migrate.vault_remote_inventory import (
    MAX_CHUNKS, MAX_ENCRYPTED_CHUNK_BYTES, MAX_ENCRYPTED_MANIFEST_BYTES,
)


_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_CHUNK = re.compile(r"objects/([0-9a-f]{2})/([0-9a-f]{62})\.cvchunk\Z")
_METADATA_LIMIT = 1024 * 1024
_BLOCK_BYTES = 1024 * 1024
_MARKER = ".hosted-recovery.json"


class ScopedReadStore(Protocol):
    """Read-only store already scoped to the authenticated account and Vault."""

    def open_read(self, key: str) -> Optional[BinaryIO]:
        """Return the encrypted object stream, or None if it is absent."""


@dataclass(frozen=True)
class _Object:
    key: str
    bytes: int
    sha256: str


@dataclass(frozen=True)
class RemoteRecoveryResult:
    vault: str
    snapshot_id: str
    downloaded_files: int
    reused_files: int
    encrypted_bytes_checked: int
    transcript_files: int


def _objects(receipt: dict, max_bytes: int) -> Tuple[str, Tuple[_Object, ...]]:
    if (not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0
            or not isinstance(receipt, dict)
            or set(receipt) != {"version", "snapshot_id", "remote_bytes_checked", "objects"}
            or type(receipt["version"]) is not int or receipt["version"] != 1
            or not isinstance(receipt["snapshot_id"], str)
            or not _UUID.fullmatch(receipt["snapshot_id"])
            or not isinstance(receipt["objects"], list)
            or not 3 <= len(receipt["objects"]) <= MAX_CHUNKS + 3
            or type(receipt["remote_bytes_checked"]) is not int):
        raise MigrationError("The hosted recovery receipt is invalid.")
    snapshot_id = receipt["snapshot_id"]
    raw = receipt["objects"]
    expected = (
        (0, "metadata/" + snapshot_id + ".json", _METADATA_LIMIT),
        (len(raw) - 2, "manifests/" + snapshot_id + ".cvmanifest",
         MAX_ENCRYPTED_MANIFEST_BYTES),
        (len(raw) - 1, "refs/" + snapshot_id + ".json", _METADATA_LIMIT),
    )
    objects: List[_Object] = []
    total = 0
    previous = ""
    for index, value in enumerate(raw):
        if (not isinstance(value, dict) or set(value) != {"key", "bytes", "sha256"}
                or not isinstance(value["key"], str)
                or type(value["bytes"]) is not int
                or not isinstance(value["sha256"], str)
                or not _HEX.fullmatch(value["sha256"])):
            raise MigrationError("The hosted recovery receipt is invalid.")
        key = value["key"]
        maximum = MAX_ENCRYPTED_CHUNK_BYTES
        fixed = next(((name, limit) for position, name, limit in expected
                      if position == index), None)
        if fixed is not None:
            if key != fixed[0]:
                raise MigrationError("The hosted recovery receipt is invalid.")
            maximum = fixed[1]
        else:
            match = _CHUNK.fullmatch(key)
            if match is None or match[1] + match[2] <= previous:
                raise MigrationError("The hosted recovery receipt is invalid.")
            previous = match[1] + match[2]
        size = value["bytes"]
        if not 0 < size <= maximum:
            raise MigrationError("The hosted recovery receipt is invalid.")
        total += size
        if total > max_bytes:
            raise MigrationError("The hosted recovery exceeds its selected size limit.")
        objects.append(_Object(key, size, value["sha256"]))
    if total != receipt["remote_bytes_checked"]:
        raise MigrationError("The hosted recovery receipt is invalid.")
    return snapshot_id, tuple(objects)


def _private_directory(descriptor: int, name: str) -> int:
    try:
        os.mkdir(name, mode=0o700, dir_fd=descriptor)
    except FileExistsError:
        pass
    child = -1
    try:
        child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=descriptor)
        info = os.fstat(child)
        if info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise MigrationError("The hosted recovery folder is not private.")
        return child
    except OSError as error:
        if child >= 0:
            os.close(child)
        raise MigrationError("The hosted recovery folder is unsafe.") from error
    except MigrationError:
        if child >= 0:
            os.close(child)
        raise


def _digest(stream: BinaryIO, expected: int) -> str:
    digest = hashlib.sha256()
    total = 0
    while True:
        block = stream.read(_BLOCK_BYTES)
        if not block:
            break
        if not isinstance(block, bytes):
            raise MigrationError("A hosted recovery object could not be read safely.")
        total += len(block)
        if total > expected:
            raise MigrationError("A hosted recovery object has the wrong size.")
        digest.update(block)
    if total != expected:
        raise MigrationError("A hosted recovery object is incomplete.")
    return digest.hexdigest()


def _copy_to_file(stream: BinaryIO, descriptor: int, item: _Object) -> None:
    digest = hashlib.sha256()
    total = 0
    with os.fdopen(descriptor, "wb") as destination:
        while True:
            block = stream.read(_BLOCK_BYTES)
            if not block:
                break
            if not isinstance(block, bytes):
                raise MigrationError("A hosted recovery object could not be read safely.")
            total += len(block)
            if total > item.bytes:
                raise MigrationError("A hosted recovery object has the wrong size.")
            destination.write(block)
            digest.update(block)
        destination.flush()
        os.fsync(destination.fileno())
    if total != item.bytes or digest.hexdigest() != item.sha256:
        raise MigrationError("A hosted recovery object is missing or differs from its receipt.")


def _checked_file(directory: int, name: str, item: _Object) -> bool:
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=directory)
    except FileNotFoundError:
        return False
    except OSError as error:
        raise MigrationError("A hosted recovery file is unsafe.") from error
    with os.fdopen(descriptor, "rb") as handle:
        info = os.fstat(handle.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != os.geteuid() or info.st_size != item.bytes
                or _digest(handle, item.bytes) != item.sha256):
            raise MigrationError("An existing hosted recovery file differs from its receipt.")
    return True


def _clear_partial(directory: int, name: str) -> None:
    """Remove only an owned temporary file from this private recovery folder."""
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=directory)
    except FileNotFoundError:
        return
    except OSError as error:
        raise MigrationError("An interrupted hosted download is unsafe.") from error
    with os.fdopen(descriptor, "rb") as handle:
        info = os.fstat(handle.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != os.geteuid()):
            raise MigrationError("An interrupted hosted download is unsafe.")
    os.unlink(name, dir_fd=directory)


def _fetch_item(root: int, item: _Object, store: ScopedReadStore) -> bool:
    relative = "vault.json" if item.key.startswith("metadata/") else item.key
    parts = relative.split("/")
    directory = os.dup(root)
    try:
        for part in parts[:-1]:
            child = _private_directory(directory, part)
            os.close(directory)
            directory = child
        name = parts[-1]
        temporary = name + ".cvdownload"
        _clear_partial(directory, temporary)
        if _checked_file(directory, name, item):
            return False
        stream = store.open_read(item.key)
        if stream is None:
            raise MigrationError("A hosted recovery object is missing.")
        created_temporary = False
        try:
            with stream:
                descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                                     os.O_NOFOLLOW, 0o600, dir_fd=directory)
                created_temporary = True
                _copy_to_file(stream, descriptor, item)
            os.link(temporary, name, src_dir_fd=directory,
                    dst_dir_fd=directory, follow_symlinks=False)
            os.fsync(directory)
        finally:
            if created_temporary:
                try:
                    os.unlink(temporary, dir_fd=directory)
                except FileNotFoundError:
                    pass
        return True
    finally:
        os.close(directory)


def _marker_bytes(snapshot_id: str, objects: Tuple[_Object, ...]) -> bytes:
    claim = {"snapshot_id": snapshot_id, "objects": [item.__dict__ for item in objects]}
    fingerprint = hashlib.sha256(json.dumps(
        claim, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return (json.dumps({"format": "codex-vault-hosted-recovery",
                        "snapshot_id": snapshot_id, "receipt_sha256": fingerprint},
                       sort_keys=True) + "\n").encode("utf-8")


def _prepare_root(source_home: str, output: str, marker: bytes) -> Tuple[Path, int]:
    root = _validate_destination(source_home, output)
    # The caller may inspect another home; never let that omit protection for
    # the account actually running this recovery.
    _validate_destination(str(Path.home()), output)
    created = False
    try:
        root.mkdir(mode=0o700)
        created = True
    except FileExistsError:
        pass
    try:
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as error:
        raise MigrationError("The hosted recovery destination is unsafe.") from error
    try:
        info = os.fstat(descriptor)
        if info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise MigrationError("The hosted recovery destination is not private.")
        if created:
            marker_file = os.open(_MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                                  os.O_NOFOLLOW, 0o600, dir_fd=descriptor)
            with os.fdopen(marker_file, "wb") as handle:
                handle.write(marker)
                handle.flush()
                os.fsync(handle.fileno())
            os.fsync(descriptor)
        else:
            try:
                marker_file = os.open(_MARKER, os.O_RDONLY | os.O_NOFOLLOW |
                                      os.O_NONBLOCK, dir_fd=descriptor)
            except OSError as error:
                raise MigrationError(
                    "The destination is not an interrupted hosted recovery."
                ) from error
            with os.fdopen(marker_file, "rb") as handle:
                info = os.fstat(handle.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                        or info.st_uid != os.geteuid() or info.st_size != len(marker)
                        or handle.read(len(marker) + 1) != marker):
                    raise MigrationError("This folder belongs to another recovery.")
        return root, descriptor
    except OSError as error:
        os.close(descriptor)
        raise MigrationError("The hosted recovery destination is unsafe.") from error
    except MigrationError:
        os.close(descriptor)
        raise


def _finish(descriptor: int, reference_item: _Object) -> None:
    reference_dir = _private_directory(descriptor, "refs")
    try:
        name = reference_item.key.split("/")[-1]
        if not _checked_file(reference_dir, name, reference_item):
            raise MigrationError("The hosted recovery reference is missing.")
        handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                         dir_fd=reference_dir)
        with os.fdopen(handle, "rb") as reference:
            info = os.fstat(reference.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or info.st_uid != os.geteuid()
                    or info.st_size != reference_item.bytes):
                raise MigrationError("The hosted recovery reference changed.")
            data = reference.read(reference_item.bytes + 1)
            if (len(data) != reference_item.bytes
                    or hashlib.sha256(data).hexdigest() != reference_item.sha256):
                raise MigrationError("The hosted recovery reference changed.")
    finally:
        os.close(reference_dir)
    latest = _Object("latest.json", len(data), hashlib.sha256(data).hexdigest())
    temporary = "latest.json.cvdownload"
    _clear_partial(descriptor, temporary)
    if not _checked_file(descriptor, "latest.json", latest):
        handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                         os.O_NOFOLLOW, 0o600, dir_fd=descriptor)
        try:
            with os.fdopen(handle, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.link(temporary, "latest.json", src_dir_fd=descriptor,
                    dst_dir_fd=descriptor, follow_symlinks=False)
        finally:
            os.unlink(temporary, dir_fd=descriptor)
    os.unlink(_MARKER, dir_fd=descriptor)
    os.fsync(descriptor)


def download_encrypted_snapshot(
    source_home: str,
    output: str,
    store: ScopedReadStore,
    receipt: dict,
    *,
    max_bytes: int,
    crypto_helper: Optional[str] = None,
) -> RemoteRecoveryResult:
    """Download and authenticate one snapshot without touching live Codex.

    A failed or interrupted run leaves a private partial folder. Retrying the
    same receipt reuses only objects whose exact bytes still match. The local
    Vault is marked latest only after the native helper authenticates its
    encrypted manifest and chunks with the separately imported recovery key.
    """
    snapshot_id, objects = _objects(receipt, max_bytes)
    root, descriptor = _prepare_root(source_home, output,
                                     _marker_bytes(snapshot_id, objects))
    downloaded = reused = 0
    try:
        # Prove this Mac can open the exact manifest before fetching potentially
        # gigabytes of chunks. Metadata alone cannot validate a recovery key.
        for item in (objects[0], objects[-2]):
            if _fetch_item(descriptor, item, store):
                downloaded += 1
            else:
                reused += 1
        key_id = _metadata(_read_json(root / "vault.json"))
        fingerprint = _run_helper(_helper_path(crypto_helper), [
            "manifest-fingerprint", "--key-id", key_id,
            "--snapshot-id", snapshot_id, "--manifest", str(root / objects[-2].key),
        ])
        if (set(fingerprint) != {"snapshot_id", "plaintext_sha256", "ciphertext_sha256"}
                or fingerprint["snapshot_id"] != snapshot_id
                or fingerprint["ciphertext_sha256"] != objects[-2].sha256
                or not isinstance(fingerprint["plaintext_sha256"], str)
                or not _HEX.fullmatch(fingerprint["plaintext_sha256"])):
            raise MigrationError("The hosted recovery manifest could not be authenticated.")
        for item in (*objects[1:-2], objects[-1]):
            if _fetch_item(descriptor, item, store):
                downloaded += 1
            else:
                reused += 1
        verified = verify_snapshot(str(root), snapshot=snapshot_id,
                                   crypto_helper=crypto_helper)
        _finish(descriptor, objects[-1])
        return RemoteRecoveryResult(
            vault=str(root), snapshot_id=snapshot_id,
            downloaded_files=downloaded, reused_files=reused,
            encrypted_bytes_checked=sum(item.bytes for item in objects),
            transcript_files=verified.transcript_files,
        )
    finally:
        os.close(descriptor)


def prepare_encrypted_recovery(
    source_home: str, output: str, store: ScopedReadStore, receipt: dict, *,
    max_bytes: int,
) -> dict:
    """Fetch only receipt-bound metadata before importing a recovery key.

    The account-scoped service and object receipt authorize this read, not
    successful decryption. No key is created/imported and no recovery-complete
    marker is written. The ordinary downloader can resume this same private
    destination after a separately confirmed key import.
    """
    snapshot_id, objects = _objects(receipt, max_bytes)
    root, descriptor = _prepare_root(source_home, output,
                                     _marker_bytes(snapshot_id, objects))
    try:
        _fetch_item(descriptor, objects[0], store)
        metadata = _read_json(root / "vault.json")
        key_id = _metadata(metadata)
        return {"vault": str(root), "snapshot_id": snapshot_id,
                "key_id": key_id,
                "recovery_mode": metadata.get("recovery_mode", "personal"),
                "encrypted_bytes_expected": sum(item.bytes for item in objects),
                "status": "awaiting_recovery_key"}
    finally:
        os.close(descriptor)
