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
import threading
from typing import BinaryIO, Callable, Dict, Iterator, List, Optional, Tuple
import uuid

from codex_migrate.errors import MigrationError
from codex_migrate.source_availability import check_info, require_local
from codex_migrate.vault import _transcripts, inspect as inspect_vault
from codex_migrate.vault_identity import (
    TranscriptChanged, loss_warnings, mark_simultaneous_conflicts,
    scan_transcript, title_index,
)
from codex_migrate.vault_local_lock import local_history_lock


FORMAT_VERSION = 1
SNAPSHOT_FORMAT_VERSION = 3
DEFAULT_CHUNK_SIZE = 4 * 1024 * 1024
METADATA_NAME = "vault.json"
STORAGE_CODEC = "lzfse-v1"
MAX_CHANGED_TRANSCRIPT_ATTEMPTS = 3


@dataclass(frozen=True)
class BackupPlan:
    destination: str
    transcript_files: int
    transcript_bytes: int
    paginated_threads: int = 0
    paginated_database_bytes: int = 0
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
    needs_attention: bool = False
    at_risk_threads: int = 0
    paginated_history_unprotected: bool = False
    title_index_unavailable: bool = False
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
        bundled = (executable.parents[2] / "Helpers/CodexVaultCrypto.app/Contents/MacOS/CodexVaultCrypto")
        candidate = bundled if bundled.is_file() else executable.parents[1] / "CodexVaultCrypto"
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


def _store_paginated_thread(helper: Path, objects: Path, chunk_size: int,
                            key_id: str, source: object, thread_id: str
                            ) -> Tuple[Dict[str, object], int, int, int]:
    """Encrypt a SQLite thread through a pipe, without plaintext staging files."""
    from codex_migrate.vault_paginated import encoded_item

    read_fd, write_fd = os.pipe()
    failure: List[BaseException] = []
    counts = [0, 0, 0]

    def produce() -> None:
        try:
            with os.fdopen(write_fd, "wb") as output:
                for item in source.items(thread_id):
                    output.write(encoded_item(item))
                    counts[0] += 1
                    counts[1] += item.item_type == "userMessage"
                    counts[2] += item.item_type == "agentMessage"
        except BaseException as error:
            failure.append(error)

    producer = threading.Thread(target=produce, name="vault-paginated-encryption")
    producer.start()
    try:
        with os.fdopen(read_fd, "rb") as input_file:
            stored = _run_helper(
                helper,
                ["store-chunks", "--key-id", key_id,
                 "--object-dir", str(objects), "--chunk-size", str(chunk_size)],
                input_file=input_file,
            )
    finally:
        producer.join()
    if failure:
        error = failure[0]
        if isinstance(error, MigrationError):
            raise error
        raise MigrationError("Codex paginated history changed or could not be encrypted safely.") from error
    return stored, *counts


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
    required = {"format", "version", "key_id", "created_at"}
    if set(value) not in (required, required | {"storage_codec"}):
        raise MigrationError("Vault metadata has an unsupported shape.")
    if value.get("format") != "codex-vault" or value.get("version") != FORMAT_VERSION:
        raise MigrationError("Vault metadata has an unsupported format version.")
    if "storage_codec" in value and value["storage_codec"] != STORAGE_CODEC:
        raise MigrationError("Vault metadata has an unsupported storage codec.")
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
        "storage_codec": STORAGE_CODEC,
        "key_id": canonical,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _atomic_json(metadata_path, metadata)
    return canonical, recovery_key


def _source_files(source_home: str) -> List[Tuple[str, Path, str]]:
    files = list(_transcripts(source_home))
    files.sort(key=lambda item: (item[0], item[2]))
    return files


def _previous_catalog(root: Path, key_id: str, helper: Path) -> List[Dict[str, object]]:
    latest = root / "latest.json"
    if not latest.exists():
        return []
    reference = _read_json(latest)
    if (set(reference) != {"format", "version", "snapshot_id", "created_at", "manifest"}
            or reference.get("format") != "codex-vault-reference"
            or reference.get("version") != FORMAT_VERSION):
        raise MigrationError("The previous Vault reference needs review before backup.")
    try:
        snapshot_id = str(uuid.UUID(str(reference.get("snapshot_id")))).lower()
    except (ValueError, TypeError, AttributeError):
        raise MigrationError("The previous Vault reference has an invalid identity.") from None
    expected = "manifests/" + snapshot_id + ".cvmanifest"
    if reference.get("manifest") != expected:
        raise MigrationError("The previous Vault reference has an invalid manifest path.")
    manifest = root / expected
    _require_unlinked_path(manifest)
    catalog = _run_helper(
        helper, ["catalog", "--key-id", key_id, "--snapshot-id", snapshot_id,
                 "--object-dir", str(root / "objects"), "--manifest", str(manifest)],
    )
    files = catalog.get("files")
    if catalog.get("snapshot_id") != snapshot_id or not isinstance(files, list) \
            or not all(isinstance(item, dict) for item in files):
        raise MigrationError("The previous Vault catalog is invalid.")
    return files


def _paginated_history_unprotected(source_home: str) -> bool:
    """Hold complete-history claims while paginated read/export is unproved.

    Its presence alone is enough: reading projection offsets cannot prove that
    the JSONL files contain everything in the database. This presence check
    never opens or mutates the Codex-owned SQLite file.
    """
    database = _canonical_macos_path(Path(source_home) / ".codex/thread_history_1.sqlite")
    try:
        info = database.lstat()
    except FileNotFoundError:
        return False  # Older Codex versions have no paginated projection.
    except OSError as error:
        raise MigrationError("Codex paginated history could not be inspected safely.") from error
    _require_unlinked_path(database)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_nlink != 1):
        raise MigrationError("Codex paginated history is not a private regular file.")
    return True


def plan(source_home: str, destination: str) -> BackupPlan:
    root = _validate_destination(source_home, destination)
    summary = inspect_vault(source_home)
    return BackupPlan(str(root), summary.active_transcripts + summary.archived_transcripts,
                      summary.transcript_bytes, summary.paginated_threads,
                      summary.paginated_database_bytes)


def backup(
    source_home: str,
    destination: str,
    *,
    crypto_helper: Optional[str] = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    progress: Optional[Callable[[int, int, int, int], None]] = None,
    require_existing_key_id: Optional[str] = None,
) -> BackupResult:
    with local_history_lock(source_home):
        return _backup_unlocked(
            source_home, destination, crypto_helper=crypto_helper,
            chunk_size=chunk_size, progress=progress,
            require_existing_key_id=require_existing_key_id)


def _backup_unlocked(
    source_home: str,
    destination: str,
    *,
    crypto_helper: Optional[str] = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    progress: Optional[Callable[[int, int, int, int], None]] = None,
    require_existing_key_id: Optional[str] = None,
) -> BackupResult:
    if chunk_size < 64 * 1024 or chunk_size > 64 * 1024 * 1024:
        raise ValueError("chunk size must be between 64 KiB and 64 MiB")
    root = _validate_destination(source_home, destination)
    if require_existing_key_id is not None:
        if not root.is_dir() or _metadata(_read_json(root / METADATA_NAME)) != require_existing_key_id:
            raise MigrationError("The scheduled Vault destination is missing or has changed. No new Vault was created.")
    if not root.exists():
        root.mkdir(mode=0o700)
        _fsync_directory(root.parent)
    _require_unlinked_path(root)
    if not root.is_dir():
        raise MigrationError("The Vault destination is not a folder.")
    helper = _helper_path(crypto_helper)
    paginated_history_unprotected = _paginated_history_unprotected(source_home)
    files = _source_files(source_home)
    try:
        titles = title_index(source_home)
        title_index_unavailable = False
    except MigrationError:
        # The optional Codex title index must not prevent a verified backup of
        # intact transcripts. Search by transcript text remains available.
        titles = {}
        title_index_unavailable = True
    expected_bytes = sum(check_info(path.lstat()).st_size for _, path, _ in files)
    progress_total_files = len(files)
    progress_total_bytes = expected_bytes
    if progress is not None and paginated_history_unprotected:
        from codex_migrate.vault_paginated import source_footprint

        paginated_count, _, _ = source_footprint(source_home)
        progress_total_files += paginated_count
        # SQLite page bytes are not the encoded source length. Do not show a
        # false percentage for this phase or imply that 100% means verified.
        progress_total_bytes = 0
    if progress is not None:
        progress(0, progress_total_files, 0, progress_total_bytes)
    with _repository_lock(root):
        if require_existing_key_id is not None and \
                _metadata(_read_json(root / METADATA_NAME)) != require_existing_key_id:
            raise MigrationError("The scheduled Vault destination changed during backup setup.")
        key_id, recovery_key = _prepare_repository(root, helper)
        objects = root / "objects"
        manifests = root / "manifests"
        references = root / "refs"
        for directory in (objects, manifests, references):
            directory.mkdir(mode=0o700, exist_ok=True)
            _require_unlinked_path(directory)
            if not directory.is_dir():
                raise MigrationError("A Vault storage path is not a folder.")
        previous_files = _previous_catalog(root, key_id, helper)

        snapshot_id = str(uuid.uuid4()).lower()
        created_at = datetime.now(timezone.utc).isoformat()
        manifest_files = []
        total_chunks = 0
        total_bytes = 0
        for folder, path, relative in files:
            require_local(path)
            for attempt in range(MAX_CHANGED_TRANSCRIPT_ATTEMPTS):
                scanned = check_info(path.lstat())
                try:
                    signals = scan_transcript(path, relative, titles)
                except TranscriptChanged:
                    if attempt + 1 == MAX_CHANGED_TRANSCRIPT_ATTEMPTS:
                        raise MigrationError(
                            "A conversation changed during backup. Run backup again; no snapshot was published."
                        ) from None
                    continue
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
                    scanned.st_dev == before.st_dev
                    and scanned.st_ino == before.st_ino
                    and scanned.st_size == before.st_size
                    and scanned.st_mtime_ns == before.st_mtime_ns
                    and scanned.st_ctime_ns == before.st_ctime_ns
                    and before.st_dev == after.st_dev
                    and before.st_ino == after.st_ino
                    and before.st_size == after.st_size
                    and before.st_mtime_ns == after.st_mtime_ns
                    and before.st_ctime_ns == after.st_ctime_ns
                )
                if stable:
                    break
                if attempt + 1 == MAX_CHANGED_TRANSCRIPT_ATTEMPTS:
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
                if (not isinstance(chunk, dict)
                        or set(chunk) not in ({"id", "size"}, {"id", "size", "encoding"})
                        or not isinstance(chunk.get("id"), str)
                        or len(chunk["id"]) != 64
                        or any(character not in "0123456789abcdef" for character in chunk["id"])
                        or not isinstance(chunk.get("size"), int)
                        or chunk["size"] < 0 or chunk["size"] > chunk_size
                        or ("encoding" in chunk and chunk["encoding"] != "lzfse")):
                    raise MigrationError("The backup helper returned invalid chunk metadata.")
            manifest_files.append({
                "collection": "active" if folder == "sessions" else "archived",
                "path": relative,
                "size": stored_size,
                "mtime_ns": before.st_mtime_ns,
                "sha256": digest,
                "chunks": chunks,
                **signals.manifest_fields(),
            })
            total_bytes += stored_size
            total_chunks += len(chunks)
            if progress is not None:
                progress(len(manifest_files), progress_total_files,
                         total_bytes, progress_total_bytes)

        mark_simultaneous_conflicts(manifest_files)
        at_risk = set(loss_warnings(
            (item for item in previous_files
             if item.get("collection") in ("active", "archived")),
            manifest_files,
        ))
        # Keep the database projection separate from the JSONL rollout. Equal
        # thread IDs across these two sources are not a simultaneous-file
        # conflict and are never treated as proof that their bodies agree.
        if paginated_history_unprotected:
            from codex_migrate.vault_paginated import open_paginated_source
            with open_paginated_source(source_home) as source:
                thread_ids = source.thread_ids()
                progress_total_files = len(files) + len(thread_ids)
                if progress is not None:
                    progress(len(files), progress_total_files, total_bytes, 0)
                for thread_id in thread_ids:
                    stored, records, users, assistants = _store_paginated_thread(
                        helper, objects, chunk_size, key_id, source, thread_id)
                    size = stored.get("size")
                    digest = stored.get("sha256")
                    chunks = stored.get("chunks")
                    if (not isinstance(size, int) or size <= 0
                            or not isinstance(digest, str) or len(digest) != 64
                            or any(character not in "0123456789abcdef" for character in digest)
                            or not isinstance(chunks, list) or records <= 0):
                        raise MigrationError("The paginated history helper returned invalid verification data.")
                    for chunk in chunks:
                        if (not isinstance(chunk, dict)
                                or set(chunk) not in ({"id", "size"}, {"id", "size", "encoding"})
                                or not isinstance(chunk.get("id"), str)
                                or len(chunk["id"]) != 64
                                or any(character not in "0123456789abcdef" for character in chunk["id"])
                                or not isinstance(chunk.get("size"), int)
                                or chunk["size"] < 0 or chunk["size"] > chunk_size
                                or ("encoding" in chunk and chunk["encoding"] != "lzfse")):
                            raise MigrationError("The paginated history helper returned invalid chunk metadata.")
                    manifest_files.append({
                        "collection": "paginated",
                        "path": thread_id + ".jsonl",
                        "size": size,
                        "mtime_ns": 0,
                        "sha256": digest,
                        "chunks": chunks,
                        "thread_id": thread_id,
                        "identity_state": "verified",
                        "titles": list(titles.get(thread_id, [])),
                        "records": records,
                        "assistant_messages": assistants,
                        "user_messages": users,
                        "at_risk": False,
                    })
                    total_bytes += size
                    total_chunks += len(chunks)
                    if progress is not None:
                        progress(len(manifest_files), progress_total_files,
                                 total_bytes, 0)
        paginated_at_risk = set(loss_warnings(
            (item for item in previous_files if item.get("collection") == "paginated"),
            (item for item in manifest_files if item.get("collection") == "paginated"),
        ))
        for item in manifest_files:
            if item["collection"] == "paginated":
                item["at_risk"] = item["thread_id"] in paginated_at_risk
        paginated_history_unprotected |= _paginated_history_unprotected(source_home)
        for item in manifest_files:
            if item["collection"] == "paginated":
                continue
            if item["identity_state"] == "needs_review":
                at_risk.add(item["collection"] + "/" + item["path"])
        for item in manifest_files:
            if item["collection"] == "paginated":
                continue
            item["at_risk"] = (item.get("thread_id") in at_risk or
                               item["collection"] + "/" + item["path"] in at_risk)
        manifest = {
            "format": "codex-vault-snapshot",
            "version": (SNAPSHOT_FORMAT_VERSION if any(
                item["collection"] == "paginated" for item in manifest_files) else 2),
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
        metadata_path = root / METADATA_NAME
        metadata = _read_json(metadata_path)
        _metadata(metadata)
        if "storage_codec" not in metadata:
            # Older helpers refuse the additional field, so no legacy build can
            # publish over a snapshot containing compressed objects.
            _atomic_json(metadata_path, {**metadata, "storage_codec": STORAGE_CODEC},
                         replace=True)
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
            needs_attention=bool(at_risk or paginated_at_risk) or paginated_history_unprotected,
            at_risk_threads=len(at_risk | paginated_at_risk),
            paginated_history_unprotected=paginated_history_unprotected,
            title_index_unavailable=title_index_unavailable,
        )
