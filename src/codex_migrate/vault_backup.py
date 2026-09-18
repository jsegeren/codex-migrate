"""Versioned, client-side encrypted backups of Codex conversation transcripts.

The repository contains only ciphertext, public format metadata and opaque
snapshot references. Authentication and installation identity are outside the
enumerated source scope. A snapshot becomes latest only after every encrypted
chunk and the encrypted manifest pass a complete restore verification.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from typing import BinaryIO, Callable, Dict, Iterator, List, Optional, Tuple
import uuid

from codex_migrate.errors import MigrationError
from codex_migrate.source_availability import check_info, require_local
from codex_migrate.vault import _transcripts


FORMAT_VERSION = 1
DEFAULT_CHUNK_SIZE = 4 * 1024 * 1024
METADATA_NAME = "vault.json"


@dataclass(frozen=True)
class BackupPlan:
    destination: str
    transcript_files: int
    transcript_bytes: int
    encrypted: bool = True
    applied: bool = False

    def as_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class BackupResult:
    destination: str
    snapshot_id: str
    transcript_files: int
    transcript_bytes: int
    chunks: int
    key_id: str
    recovery_key: Optional[str]
    applied: bool = True

    def as_dict(self) -> Dict[str, object]:
        return asdict(self)


def _canonical_macos_path(path: Path) -> Path:
    """Normalize only Apple's fixed root aliases, never user-controlled links."""
    absolute = path.absolute()
    parts = absolute.parts
    if len(parts) > 1 and parts[1] in ("var", "tmp", "etc"):
        return Path("/private") / Path(*parts[1:])
    return absolute


def _path_components(path: Path) -> Iterator[Path]:
    absolute = _canonical_macos_path(path)
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        yield current


def _require_unlinked_path(path: Path, allow_missing_leaf: bool = False) -> None:
    components = list(_path_components(path))
    for index, component in enumerate(components):
        try:
            info = component.lstat()
        except FileNotFoundError:
            if allow_missing_leaf and index == len(components) - 1:
                return
            raise MigrationError("The Vault destination parent folder does not exist.") from None
        except OSError as error:
            raise MigrationError("The Vault destination could not be inspected safely.") from error
        if stat.S_ISLNK(info.st_mode):
            raise MigrationError("The Vault destination cannot contain linked path components.")
        if index < len(components) - 1 and not stat.S_ISDIR(info.st_mode):
            raise MigrationError("The Vault destination parent is not a folder.")


def _validate_destination(source_home: str, destination: str) -> Path:
    root = Path(destination).expanduser()
    if not root.is_absolute():
        raise ValueError("Vault destination must be an absolute path")
    _require_unlinked_path(root, allow_missing_leaf=True)
    source = _canonical_macos_path(Path(source_home) / ".codex")
    candidate = _canonical_macos_path(root)
    try:
        overlap = os.path.commonpath((str(source), str(candidate))) in (str(source), str(candidate))
    except ValueError:
        overlap = False
    if overlap:
        raise MigrationError("The Vault destination must be outside the source Codex data folder.")
    return candidate


def _helper_path(explicit: Optional[str]) -> Path:
    if explicit:
        candidate = Path(explicit).expanduser()
    else:
        executable = Path(sys.executable)
        candidate = executable.parents[1] / "CodexVaultCrypto"
    if not candidate.is_absolute():
        raise ValueError("crypto helper path must be absolute")
    try:
        info = candidate.lstat()
    except OSError as error:
        raise MigrationError(
            "The authenticated backup helper is unavailable. Use the packaged Mac app."
        ) from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise MigrationError("The authenticated backup helper is not a regular file.")
    if info.st_uid not in (0, os.getuid()) or info.st_mode & 0o022 or not os.access(candidate, os.X_OK):
        raise MigrationError("The authenticated backup helper has unsafe ownership or permissions.")
    return candidate


def _run_helper(
    helper: Path,
    arguments: List[str],
    *,
    input_data: Optional[bytes] = None,
    input_file: Optional[BinaryIO] = None,
) -> Dict[str, object]:
    if input_data is not None and input_file is not None:
        raise ValueError("helper input must use bytes or a file, not both")
    command = [str(helper)] + arguments
    try:
        result = subprocess.run(
            command,
            input=input_data if input_file is None else None,
            stdin=input_file,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as error:
        raise MigrationError("The authenticated backup helper could not start.") from error
    if result.returncode:
        raise MigrationError(
            "Authenticated backup failed; no new snapshot was published."
        )
    try:
        payload = json.loads(result.stdout)
    except (UnicodeError, json.JSONDecodeError):
        raise MigrationError("The authenticated backup helper returned an invalid result.") from None
    if not isinstance(payload, dict):
        raise MigrationError("The authenticated backup helper returned an invalid result.")
    return payload


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_json(path: Path, value: object, replace: bool = False) -> None:
    if path.exists() and not replace:
        raise MigrationError("Refusing to replace existing Vault metadata.")
    temporary = path.parent / ("." + path.name + "." + uuid.uuid4().hex + ".tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(_json_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _read_json(path: Path) -> Dict[str, object]:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 1024 * 1024:
                raise MigrationError("Vault metadata is not a supported regular file.")
            value = json.load(handle)
    except MigrationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise MigrationError("Vault metadata is unreadable or invalid.") from error
    if not isinstance(value, dict):
        raise MigrationError("Vault metadata is unreadable or invalid.")
    return value


def _metadata(value: Dict[str, object]) -> str:
    if set(value) != {"format", "version", "key_id", "created_at"}:
        raise MigrationError("Vault metadata has an unsupported shape.")
    if value.get("format") != "codex-vault" or value.get("version") != FORMAT_VERSION:
        raise MigrationError("Vault metadata has an unsupported format version.")
    key_id = value.get("key_id")
    try:
        canonical = str(uuid.UUID(str(key_id))).lower()
    except (ValueError, TypeError, AttributeError):
        raise MigrationError("Vault metadata has an invalid key identifier.") from None
    if canonical != key_id:
        raise MigrationError("Vault metadata has an invalid key identifier.")
    if not isinstance(value.get("created_at"), str):
        raise MigrationError("Vault metadata has an invalid creation time.")
    return canonical


@contextmanager
def _repository_lock(root: Path) -> Iterator[None]:
    lock = root / "backup.lock"
    try:
        descriptor = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except OSError as error:
        raise MigrationError("The Vault backup lock could not be opened safely.") from error
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise MigrationError("Another Vault backup is already running.") from error
        yield
    finally:
        os.close(descriptor)


def _prepare_repository(root: Path, helper: Path) -> Tuple[str, Optional[str]]:
    metadata_path = root / METADATA_NAME
    if metadata_path.exists():
        return _metadata(_read_json(metadata_path)), None
    unexpected = [item for item in root.iterdir() if item.name != "backup.lock"]
    if unexpected:
        raise MigrationError("The selected folder is not an empty or existing Codex Vault.")
    created = _run_helper(helper, ["create-key"])
    key_id = created.get("key_id")
    recovery_key = created.get("recovery_key")
    try:
        canonical = str(uuid.UUID(str(key_id))).lower()
    except (ValueError, TypeError, AttributeError):
        raise MigrationError("The backup helper returned an invalid key identifier.") from None
    if canonical != key_id or not isinstance(recovery_key, str) or not recovery_key.startswith("CV1-"):
        raise MigrationError("The backup helper returned invalid recovery material.")
    metadata = {
        "format": "codex-vault",
        "version": FORMAT_VERSION,
        "key_id": canonical,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _atomic_json(metadata_path, metadata)
    return canonical, recovery_key


def _source_files(source_home: str) -> List[Tuple[str, Path, str]]:
    files = list(_transcripts(source_home))
    files.sort(key=lambda item: (item[0], item[2]))
    return files


def plan(source_home: str, destination: str) -> BackupPlan:
    root = _validate_destination(source_home, destination)
    files = _source_files(source_home)
    total = sum(check_info(path.lstat()).st_size for _, path, _ in files)
    return BackupPlan(str(root), len(files), total)


def backup(
    source_home: str,
    destination: str,
    *,
    crypto_helper: Optional[str] = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    progress: Optional[Callable[[int, int, int, int], None]] = None,
) -> BackupResult:
    if chunk_size < 64 * 1024 or chunk_size > 64 * 1024 * 1024:
        raise ValueError("chunk size must be between 64 KiB and 64 MiB")
    root = _validate_destination(source_home, destination)
    if not root.exists():
        root.mkdir(mode=0o700)
        _fsync_directory(root.parent)
    _require_unlinked_path(root)
    if not root.is_dir():
        raise MigrationError("The Vault destination is not a folder.")
    helper = _helper_path(crypto_helper)
    files = _source_files(source_home)
    expected_bytes = sum(check_info(path.lstat()).st_size for _, path, _ in files)
    if progress is not None:
        progress(0, len(files), 0, expected_bytes)
    with _repository_lock(root):
        key_id, recovery_key = _prepare_repository(root, helper)
        objects = root / "objects"
        manifests = root / "manifests"
        references = root / "refs"
        for directory in (objects, manifests, references):
            directory.mkdir(mode=0o700, exist_ok=True)
            _require_unlinked_path(directory)
            if not directory.is_dir():
                raise MigrationError("A Vault storage path is not a folder.")

        snapshot_id = str(uuid.uuid4()).lower()
        created_at = datetime.now(timezone.utc).isoformat()
        manifest_files = []
        total_chunks = 0
        total_bytes = 0
        for folder, path, relative in files:
            require_local(path)
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                before = os.fstat(descriptor)
                if not stat.S_ISREG(before.st_mode):
                    raise MigrationError("A conversation transcript changed before backup.")
                with os.fdopen(descriptor, "rb", closefd=False) as handle:
                    stored = _run_helper(
                        helper,
                        ["store-chunks", "--key-id", key_id,
                         "--object-dir", str(objects), "--chunk-size", str(chunk_size)],
                        input_file=handle,
                    )
                after = os.fstat(descriptor)
            finally:
                os.close(descriptor)
            stable = (
                before.st_dev == after.st_dev
                and before.st_ino == after.st_ino
                and before.st_size == after.st_size
                and before.st_mtime_ns == after.st_mtime_ns
                and before.st_ctime_ns == after.st_ctime_ns
            )
            if not stable:
                raise MigrationError(
                    "A conversation changed during backup. Run backup again; no snapshot was published."
                )
            stored_size = stored.get("size")
            digest = stored.get("sha256")
            chunks = stored.get("chunks")
            if (stored_size != before.st_size or not isinstance(digest, str)
                    or len(digest) != 64
                    or any(character not in "0123456789abcdef" for character in digest)
                    or not isinstance(chunks, list)):
                raise MigrationError("The backup helper returned invalid file verification data.")
            for chunk in chunks:
                if (not isinstance(chunk, dict) or set(chunk) != {"id", "size"}
                        or not isinstance(chunk.get("id"), str)
                        or len(chunk["id"]) != 64
                        or any(character not in "0123456789abcdef" for character in chunk["id"])
                        or not isinstance(chunk.get("size"), int)
                        or chunk["size"] < 0 or chunk["size"] > chunk_size):
                    raise MigrationError("The backup helper returned invalid chunk metadata.")
            manifest_files.append({
                "collection": "active" if folder == "sessions" else "archived",
                "path": relative,
                "size": stored_size,
                "mtime_ns": before.st_mtime_ns,
                "sha256": digest,
                "chunks": chunks,
            })
            total_bytes += stored_size
            total_chunks += len(chunks)
            if progress is not None:
                progress(len(manifest_files), len(files), total_bytes, expected_bytes)

        manifest = {
            "format": "codex-vault-snapshot",
            "version": FORMAT_VERSION,
            "snapshot_id": snapshot_id,
            "created_at": created_at,
            "files": manifest_files,
        }
        manifest_path = manifests / (snapshot_id + ".cvmanifest")
        _run_helper(
            helper,
            ["seal-manifest", "--key-id", key_id, "--snapshot-id", snapshot_id,
             "--output", str(manifest_path)],
            input_data=_json_bytes(manifest),
        )
        verified = _run_helper(
            helper,
            ["verify", "--key-id", key_id, "--snapshot-id", snapshot_id,
             "--object-dir", str(objects), "--manifest", str(manifest_path)],
        )
        if (verified.get("snapshot_id") != snapshot_id
                or verified.get("files") != len(manifest_files)
                or verified.get("chunks") != total_chunks
                or verified.get("bytes") != total_bytes):
            raise MigrationError("The completed Vault snapshot did not verify exactly.")
        reference = {
            "format": "codex-vault-reference",
            "version": FORMAT_VERSION,
            "snapshot_id": snapshot_id,
            "created_at": created_at,
            "manifest": "manifests/" + manifest_path.name,
        }
        _atomic_json(references / (snapshot_id + ".json"), reference)
        _atomic_json(root / "latest.json", reference, replace=True)
        return BackupResult(
            destination=str(root),
            snapshot_id=snapshot_id,
            transcript_files=len(manifest_files),
            transcript_bytes=total_bytes,
            chunks=total_chunks,
            key_id=key_id,
            recovery_key=recovery_key,
        )
