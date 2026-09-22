"""Crash-recoverable local installation of verified Codex Vault history."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import shutil
import stat
import tempfile
from typing import Dict, Iterator, Optional, Tuple
import uuid

from codex_migrate.errors import MigrationError
from codex_migrate.processes import codex_running
from codex_migrate.source_availability import check_info, require_local
from codex_migrate.vault import TRANSCRIPT_FOLDERS
from codex_migrate.vault_identity import peek_identity
from codex_migrate.vault_backup import (
    _atomic_json,
    _canonical_macos_path,
    _fsync_directory,
    _read_json,
    _require_unlinked_path,
)
from codex_migrate.vault_local_lock import local_history_lock
from codex_migrate.vault_recovery import restore_snapshot, verify_snapshot


JOURNAL_NAME = ".codex-vault-install.json"
LOCK_NAME = ".codex-vault-install.lock"
FORMAT_VERSION = 1


@dataclass(frozen=True)
class TreeSummary:
    files: int
    bytes: int
    digest: str

    def as_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class InstallPlan:
    vault: str
    snapshot_id: str
    transcript_files: int
    transcript_bytes: int
    backup: Optional[str] = None
    applied: bool = False

    def as_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class InstallResult:
    vault: str
    snapshot_id: str
    transcript_files: int
    transcript_bytes: int
    backup: str
    applied: bool = True

    def as_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ThreadInstallPlan:
    vault: str
    snapshot_id: str
    collection: str
    transcript: str
    action: str
    target: str
    transcript_bytes: int
    applied: bool = False

    def as_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ThreadInstallResult:
    vault: str
    snapshot_id: str
    collection: str
    transcript: str
    status: str
    target: str
    transcript_bytes: int
    receipt: Optional[str]
    applied: bool

    def as_dict(self) -> Dict[str, object]:
        return asdict(self)


def _home(source_home: str) -> Tuple[Path, Path]:
    home = Path(source_home).expanduser()
    if not home.is_absolute():
        raise ValueError("source home must be absolute")
    home = _canonical_macos_path(home)
    _require_unlinked_path(home)
    try:
        info = home.lstat()
    except OSError as error:
        raise MigrationError("The local account home could not be inspected safely.") from error
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or os.getuid() == 0):
        raise MigrationError("Vault installation requires the signed-in non-root Mac account.")
    codex = home / ".codex"
    _require_unlinked_path(codex)
    try:
        info = codex.lstat()
    except OSError as error:
        raise MigrationError("The local Codex data folder is unavailable.") from error
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise MigrationError("The local Codex data folder needs review before recovery.")
    require_local(codex)
    return home, codex


def _snapshot_id(snapshot: str) -> str:
    if snapshot == "latest":
        return snapshot
    try:
        return str(uuid.UUID(snapshot)).lower()
    except (ValueError, TypeError, AttributeError):
        raise ValueError("snapshot must be 'latest' or a UUID") from None


def _hash_file(path: Path) -> Tuple[int, str]:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    digest = hashlib.sha256()
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid():
            raise MigrationError("A conversation transcript is not a safe local file.")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            while True:
                block = handle.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
            before.st_ctime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
            after.st_ctime_ns):
        raise MigrationError("A conversation changed while recovery was being prepared.")
    return before.st_size, digest.hexdigest()


def _tree_records(
    root: Path,
    *,
    strict_root: bool = False,
) -> Dict[str, Tuple[int, str]]:
    _require_unlinked_path(root)
    require_local(root)
    if strict_root:
        allowed = set(TRANSCRIPT_FOLDERS) | {"restore-receipt.json"}
        try:
            if any(item.name not in allowed for item in root.iterdir()):
                raise MigrationError("The recovered snapshot contains an unexpected item.")
        except OSError as error:
            raise MigrationError("The recovered snapshot could not be inspected safely.") from error
    records: Dict[str, Tuple[int, str]] = {}
    for folder in TRANSCRIPT_FOLDERS:
        collection = root / folder
        if not collection.exists():
            continue
        _require_unlinked_path(collection)
        require_local(collection)
        if not collection.is_dir():
            raise MigrationError("A conversation history collection is not a folder.")
        try:
            for current, directories, files in os.walk(collection, followlinks=False):
                current_path = Path(current)
                require_local(current_path)
                for name in directories:
                    child = current_path / name
                    info = child.lstat()
                    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                        raise MigrationError("A linked conversation folder blocks recovery.")
                for name in files:
                    if not name.endswith(".jsonl"):
                        raise MigrationError("The conversation history contains an unexpected file.")
                    path = current_path / name
                    check_info(path.lstat())
                    require_local(path)
                    size, digest = _hash_file(path)
                    relative = folder + "/" + path.relative_to(collection).as_posix()
                    if relative in records:
                        raise MigrationError("The conversation history contains a duplicate transcript path.")
                    records[relative] = (size, digest)
        except MigrationError:
            raise
        except OSError as error:
            raise MigrationError("Conversation history could not be inspected safely.") from error
    return records


def _summary(records: Dict[str, Tuple[int, str]]) -> TreeSummary:
    total = 0
    aggregate = hashlib.sha256()
    for relative in sorted(records):
        size, digest = records[relative]
        aggregate.update(relative.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(str(size).encode("ascii"))
        aggregate.update(b"\0")
        aggregate.update(digest.encode("ascii"))
        aggregate.update(b"\n")
        total += size
    return TreeSummary(len(records), total, aggregate.hexdigest())


def _tree_summary(root: Path, *, strict_root: bool = False) -> TreeSummary:
    return _summary(_tree_records(root, strict_root=strict_root))


def _selection(collection: str, transcript: str) -> Tuple[str, PurePosixPath]:
    if collection not in ("active", "archived"):
        raise ValueError("unknown conversation collection")
    if (not isinstance(transcript, str) or not transcript
            or len(transcript) > 4096 or transcript.startswith("/")
            or "\\" in transcript or "\x00" in transcript):
        raise ValueError("invalid conversation identifier")
    relative = PurePosixPath(transcript)
    if (relative.as_posix() != transcript or relative.suffix != ".jsonl"
            or any(part in ("", ".", "..") for part in relative.parts)):
        raise ValueError("invalid conversation identifier")
    folder = "sessions" if collection == "active" else "archived_sessions"
    return folder, relative


def _selected_source(
    recovered: Path,
    collection: str,
    transcript: str,
) -> Tuple[str, PurePosixPath, Path, Tuple[int, str]]:
    folder, relative = _selection(collection, transcript)
    logical = folder + "/" + relative.as_posix()
    records = _tree_records(recovered, strict_root=True)
    if logical not in records:
        raise MigrationError("The selected conversation is not present in this Vault snapshot.")
    source = recovered / folder / Path(*relative.parts)
    source_id, source_state = peek_identity(source, relative.as_posix())
    if source_state == "verified" and source_id:
        for other in records:
            if other == logical:
                continue
            other_id, other_state = peek_identity(recovered / other, other)
            if other_state != "needs_review" and other_id == source_id:
                raise MigrationError(
                    "This backup contains more than one file for the same thread ID. "
                    "Open or export the versions for review; copy-back is refused."
                )
    return folder, relative, source, records[logical]


def _selected_action(
    live_records: Dict[str, Tuple[int, str]],
    folder: str,
    relative: PurePosixPath,
    source_record: Tuple[int, str],
    source: Path,
    live_root: Path,
) -> Tuple[str, str]:
    target = folder + "/" + relative.as_posix()
    source_id, source_state = peek_identity(source, relative.as_posix())
    if source_state != "verified" or source_id is None:
        raise MigrationError(
            "This saved conversation has no verified thread ID. Open or export it from Vault; "
            "automatic copy-back into Codex needs identity review."
        )
    collisions = {}
    for logical, record in live_records.items():
        if PurePosixPath(logical).name == relative.name:
            collisions[logical] = record
            continue
        live_id, live_state = peek_identity(live_root / logical, logical)
        if live_state == "needs_review":
            raise MigrationError(
                "A local conversation identity needs review before selected recovery."
            )
        if live_state == "verified" and live_id == source_id:
            collisions[logical] = record
    if not collisions:
        return "add", target
    if all(record == source_record for record in collisions.values()):
        return "already_present", sorted(collisions)[0]
    raise MigrationError(
        "A conversation with this thread identity already exists locally with different "
        "content. Selected recovery never overwrites or merges an existing conversation."
    )


def _safe_target_parent(root: Path, relative: PurePosixPath) -> Path:
    current = root
    for part in relative.parts:
        current = current / part
        _require_unlinked_path(current, allow_missing_leaf=True)
        if current.exists():
            try:
                info = current.lstat()
            except OSError as error:
                raise MigrationError("The selected conversation destination is unavailable.") from error
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                raise MigrationError("The selected conversation destination needs review.")
            require_local(current)
            continue
        try:
            current.mkdir(mode=0o700)
            _fsync_directory(current.parent)
        except OSError as error:
            raise MigrationError("The selected conversation destination could not be prepared.") from error
    return current


def _copy_selected(source: Path, target: Path, expected: Tuple[int, str]) -> None:
    _require_unlinked_path(target, allow_missing_leaf=True)
    if target.exists():
        raise MigrationError("The selected conversation appeared locally before recovery finished.")
    temporary = target.parent / ("." + target.name + ".vault-" + secrets.token_hex(8) + ".tmp")
    source_descriptor = -1
    target_descriptor = -1
    try:
        source_descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        source_info = os.fstat(source_descriptor)
        if (not stat.S_ISREG(source_info.st_mode)
                or source_info.st_uid != os.getuid()):
            raise MigrationError("The selected recovered conversation is not a regular file.")
        target_descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(source_descriptor, "rb", closefd=False) as source_handle, \
                os.fdopen(target_descriptor, "wb", closefd=False) as target_handle:
            shutil.copyfileobj(source_handle, target_handle, length=1024 * 1024)
            target_handle.flush()
            os.fsync(target_handle.fileno())
        _same(
            _summary({"selected": _hash_file(temporary)}),
            _summary({"selected": expected}),
            "The selected conversation changed while it was staged for recovery.",
        )
        os.replace(temporary, target)
        _fsync_directory(target.parent)
    finally:
        if source_descriptor >= 0:
            os.close(source_descriptor)
        if target_descriptor >= 0:
            os.close(target_descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _selected_stage(
    home: Path,
    vault: str,
    snapshot: str,
    collection: str,
    transcript: str,
    crypto_helper: Optional[str],
):
    verified = verify_snapshot(
        vault, snapshot=_snapshot_id(snapshot), crypto_helper=crypto_helper)
    temporary = tempfile.TemporaryDirectory(prefix=".codex-vault-selected-", dir=str(home))
    try:
        recovered = Path(temporary.name) / "recovered"
        restored = restore_snapshot(
            str(home), verified.vault, str(recovered),
            snapshot=verified.snapshot_id, crypto_helper=crypto_helper,
        )
        staged = _tree_summary(recovered, strict_root=True)
        if (staged.files != restored.transcript_files
                or staged.bytes != restored.transcript_bytes):
            raise MigrationError("The recovered snapshot changed before selected recovery.")
        selected = _selected_source(recovered, collection, transcript)
        return verified, temporary, selected
    except Exception:
        temporary.cleanup()
        raise


def _thread_receipt_path(home: Path) -> Path:
    return home / (
        "Codex-Vault-Thread-Restore-Receipt-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-")
        + secrets.token_hex(8)
        + ".json"
    )


def _remove_selected_after_failure(
    target: Path,
    expected: Tuple[int, str],
    collection_root: Path,
) -> None:
    """Remove only the file this operation added, then prune its empty parents."""
    _require_unlinked_path(target, allow_missing_leaf=True)
    if target.exists():
        if _hash_file(target) != expected:
            raise MigrationError(
                "The newly recovered conversation changed before rollback and needs review."
            )
        target.unlink()
        _fsync_directory(target.parent)
    current = target.parent
    while current != collection_root:
        if collection_root not in current.parents:
            raise MigrationError("The selected conversation rollback path needs review.")
        try:
            current.rmdir()
        except OSError:
            break
        parent = current.parent
        _fsync_directory(parent)
        current = parent


def plan_thread_install(
    source_home: str,
    vault: str,
    collection: str,
    transcript: str,
    *,
    snapshot: str = "latest",
    crypto_helper: Optional[str] = None,
) -> ThreadInstallPlan:
    """Verify a snapshot and preview one additive conversation recovery."""
    home, codex = _home(source_home)
    with _install_lock(home):
        if _journal(home) is not None:
            raise MigrationError("An interrupted Vault installation must be rolled back first.")
        verified, temporary, selected = _selected_stage(
            home, vault, snapshot, collection, transcript, crypto_helper)
        try:
            folder, relative, source, source_record = selected
            action, target = _selected_action(
                _tree_records(codex), folder, relative, source_record,
                source, codex)
            return ThreadInstallPlan(
                vault=verified.vault,
                snapshot_id=verified.snapshot_id,
                collection=collection,
                transcript=transcript,
                action=action,
                target=target,
                transcript_bytes=source_record[0],
            )
        finally:
            temporary.cleanup()


def install_thread(
    source_home: str,
    vault: str,
    collection: str,
    transcript: str,
    *,
    snapshot: str = "latest",
    crypto_helper: Optional[str] = None,
) -> ThreadInstallResult:
    """Install one missing verified transcript without replacing local history."""
    home, codex = _home(source_home)
    with _install_lock(home):
        if _journal(home) is not None:
            raise MigrationError("An interrupted Vault installation must be rolled back first.")
        with local_history_lock(str(home)):
            if codex_running(str(home)):
                raise MigrationError(
                    "Close Codex and its CLI sessions before recovering a conversation."
                )
            verified, temporary, selected = _selected_stage(
                home, vault, snapshot, collection, transcript, crypto_helper)
            added_target: Optional[Path] = None
            receipt: Optional[Path] = None
            before: Optional[Dict[str, Tuple[int, str]]] = None
            source_record: Optional[Tuple[int, str]] = None
            collection_root: Optional[Path] = None
            try:
                folder, relative, source, source_record = selected
                before = _tree_records(codex)
                action, logical_target = _selected_action(
                    before, folder, relative, source_record, source, codex)
                if action == "already_present":
                    return ThreadInstallResult(
                        vault=verified.vault,
                        snapshot_id=verified.snapshot_id,
                        collection=collection,
                        transcript=transcript,
                        status="already_present",
                        target=logical_target,
                        transcript_bytes=source_record[0],
                        receipt=None,
                        applied=False,
                    )
                if codex_running(str(home)):
                    raise MigrationError(
                        "Codex reopened before selected recovery; no conversation was changed."
                    )
                collection_root = codex / folder
                _require_unlinked_path(collection_root, allow_missing_leaf=True)
                if not collection_root.exists():
                    collection_root.mkdir(mode=0o700)
                    _fsync_directory(codex)
                target_parent = _safe_target_parent(
                    collection_root, PurePosixPath(*relative.parts[:-1]))
                added_target = target_parent / relative.name
                _copy_selected(source, added_target, source_record)

                after = _tree_records(codex)
                expected = dict(before)
                expected[logical_target] = source_record
                if after != expected:
                    raise MigrationError(
                        "Local conversation history changed during selected recovery."
                    )
                if codex_running(str(home)):
                    raise MigrationError("Codex reopened during selected recovery.")
                receipt = _thread_receipt_path(home)
                _atomic_json(receipt, {
                    "format": "codex-vault-thread-restore-receipt",
                    "version": FORMAT_VERSION,
                    "vault": verified.vault,
                    "snapshot_id": verified.snapshot_id,
                    "collection": collection,
                    "transcript": transcript,
                    "target": logical_target,
                    "transcript_bytes": source_record[0],
                    "sha256": source_record[1],
                    "preexisting_transcripts": len(before),
                    "installed_at": datetime.now(timezone.utc).isoformat(),
                    "verified": True,
                })
                return ThreadInstallResult(
                    vault=verified.vault,
                    snapshot_id=verified.snapshot_id,
                    collection=collection,
                    transcript=transcript,
                    status="installed",
                    target=logical_target,
                    transcript_bytes=source_record[0],
                    receipt=str(receipt),
                    applied=True,
                )
            except Exception as error:
                if added_target is not None and before is not None \
                        and source_record is not None and collection_root is not None:
                    try:
                        if receipt is not None and receipt.exists():
                            receipt.unlink()
                            _fsync_directory(home)
                        _remove_selected_after_failure(
                            added_target, source_record, collection_root)
                        if _tree_records(codex) != before:
                            raise MigrationError(
                                "The previous conversation history could not be verified after rollback."
                            )
                    except Exception as rollback_error:
                        raise MigrationError(
                            "Selected recovery stopped and automatic rollback could not be verified. "
                            "Keep Codex closed and review the local conversation history."
                        ) from rollback_error
                    raise MigrationError(
                        "Selected recovery stopped safely. The added conversation was removed and "
                        "previous history was verified."
                    ) from error
                if isinstance(error, (MigrationError, ValueError)):
                    raise
                raise MigrationError("Selected recovery could not start safely.") from error
            finally:
                temporary.cleanup()


def _same(actual: TreeSummary, expected: TreeSummary, message: str) -> None:
    if actual != expected:
        raise MigrationError(message)


@contextmanager
def _install_lock(home: Path) -> Iterator[None]:
    path = home / LOCK_NAME
    _require_unlinked_path(path, allow_missing_leaf=True)
    try:
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except OSError as error:
        raise MigrationError("The Vault installation lock could not be opened safely.") from error
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077):
            raise MigrationError("The Vault installation lock has unsafe permissions.")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise MigrationError("Another Vault installation is already running.") from error
        yield
    finally:
        os.close(descriptor)


def _journal_path(home: Path) -> Path:
    return home / JOURNAL_NAME


def _journal(home: Path) -> Optional[Dict[str, object]]:
    path = _journal_path(home)
    _require_unlinked_path(path, allow_missing_leaf=True)
    if not path.exists():
        return None
    value = _read_json(path)
    required = {
        "format", "version", "status", "vault", "snapshot_id", "backup",
        "stage", "original", "staged", "created_at",
    }
    if (set(value) != required or value.get("format") != "codex-vault-install"
            or value.get("version") != FORMAT_VERSION
            or value.get("status") not in ("prepared", "installing", "verifying")):
        raise MigrationError("The interrupted Vault installation journal needs review.")
    for key in ("vault", "snapshot_id", "backup", "stage", "created_at"):
        if not isinstance(value.get(key), str) or not value[key]:
            raise MigrationError("The interrupted Vault installation journal needs review.")
    for key in ("original", "staged"):
        summary = value.get(key)
        if (not isinstance(summary, dict)
                or set(summary) != {"files", "bytes", "digest"}
                or not isinstance(summary.get("files"), int)
                or not isinstance(summary.get("bytes"), int)
                or not isinstance(summary.get("digest"), str)):
            raise MigrationError("The interrupted Vault installation journal needs review.")
    return value


def install_status(source_home: str) -> Dict[str, object]:
    home, _ = _home(source_home)
    value = _journal(home)
    if value is None:
        return {"status": "idle"}
    return {
        "status": "interrupted",
        "backup": value["backup"],
        "created_at": value["created_at"],
    }


def _write_journal(home: Path, value: Dict[str, object], status: str) -> None:
    updated = dict(value)
    updated["status"] = status
    _atomic_json(_journal_path(home), updated, replace=True)


def _remove_journal(home: Path) -> None:
    path = _journal_path(home)
    path.unlink()
    _fsync_directory(home)


def _remove_owned_tree(path: Path, parent: Path) -> None:
    if not path.exists():
        return
    if path.parent != parent or path.is_symlink():
        raise MigrationError("A private Vault staging folder needs review.")
    shutil.rmtree(path)
    _fsync_directory(parent)


def _install_paths(home: Path, value: Dict[str, object]) -> Tuple[Path, Path]:
    backup = Path(str(value["backup"]))
    stage = Path(str(value["stage"]))
    if (backup.parent != home
            or not backup.name.startswith("Codex-Vault-Restore-Backup-")
            or stage.parent != home
            or not stage.name.startswith(".codex-vault-stage-")):
        raise MigrationError("The interrupted Vault installation paths need review.")
    return backup, stage


def _rollback(home: Path, codex: Path, value: Dict[str, object]) -> None:
    backup, stage = _install_paths(home, value)
    _require_unlinked_path(backup)
    _require_unlinked_path(stage, allow_missing_leaf=True)
    failed = backup / "failed-install"
    incoming_root = stage / "recovered"
    failed.mkdir(mode=0o700, exist_ok=True)
    completed_receipt = backup / "install-receipt.json"
    if completed_receipt.exists():
        os.replace(completed_receipt, failed / "install-receipt.json")
        _fsync_directory(backup)
        _fsync_directory(failed)
    for folder in reversed(TRANSCRIPT_FOLDERS):
        live = codex / folder
        saved = backup / folder
        quarantined = failed / folder
        if saved.exists():
            if live.exists():
                if quarantined.exists():
                    raise MigrationError("The failed Vault installation needs manual recovery.")
                os.replace(live, quarantined)
                _fsync_directory(codex)
            os.replace(saved, live)
            _fsync_directory(backup)
            _fsync_directory(codex)
        elif live.exists() and (incoming_root / folder).exists() is False:
            if quarantined.exists():
                raise MigrationError("The failed Vault installation needs manual recovery.")
            os.replace(live, quarantined)
            _fsync_directory(codex)
    expected = TreeSummary(**value["original"])
    _same(
        _tree_summary(codex), expected,
        "The original Codex history could not be verified after rollback.",
    )
    _atomic_json(backup / "rollback-receipt.json", {
        "format": "codex-vault-rollback",
        "version": FORMAT_VERSION,
        "snapshot_id": value["snapshot_id"],
        "rolled_back_at": datetime.now(timezone.utc).isoformat(),
        "verified": True,
    })
    _remove_journal(home)
    _remove_owned_tree(stage, home)


def recover_interrupted_install(source_home: str, *, apply: bool = False) -> Dict[str, object]:
    home, codex = _home(source_home)
    with _install_lock(home):
        value = _journal(home)
        if value is None:
            return {"status": "idle", "applied": False}
        if not apply:
            return {
                "status": "would_rollback", "backup": value["backup"],
                "applied": False,
            }
        with local_history_lock(str(home)):
            if codex_running(str(home)):
                raise MigrationError("Close Codex and its CLI sessions before recovery.")
            _rollback(home, codex, value)
        return {
            "status": "rolled_back", "backup": value["backup"],
            "applied": True,
        }


def plan_install(
    source_home: str,
    vault: str,
    *,
    snapshot: str = "latest",
    crypto_helper: Optional[str] = None,
) -> InstallPlan:
    home, _ = _home(source_home)
    with _install_lock(home):
        if _journal(home) is not None:
            raise MigrationError("An interrupted Vault installation must be rolled back first.")
        verified = verify_snapshot(
            vault, snapshot=_snapshot_id(snapshot), crypto_helper=crypto_helper)
        return InstallPlan(
            vault=verified.vault, snapshot_id=verified.snapshot_id,
            transcript_files=verified.transcript_files,
            transcript_bytes=verified.transcript_bytes,
        )


def install_snapshot(
    source_home: str,
    vault: str,
    *,
    snapshot: str = "latest",
    crypto_helper: Optional[str] = None,
) -> InstallResult:
    home, codex = _home(source_home)
    with _install_lock(home):
        if _journal(home) is not None:
            raise MigrationError("An interrupted Vault installation must be rolled back first.")
        with local_history_lock(str(home)):
            if codex_running(str(home)):
                raise MigrationError("Close Codex and its CLI sessions before installing a backup.")
            verified = verify_snapshot(
                vault, snapshot=_snapshot_id(snapshot), crypto_helper=crypto_helper)
            stage = Path(tempfile.mkdtemp(prefix=".codex-vault-stage-", dir=str(home)))
            os.chmod(stage, 0o700)
            backup = home / (
                "Codex-Vault-Restore-Backup-"
                + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-")
                + secrets.token_hex(8)
            )
            backup.mkdir(mode=0o700)
            journal_written = False
            try:
                recovered = stage / "recovered"
                restored = restore_snapshot(
                    str(home), verified.vault, str(recovered),
                    snapshot=verified.snapshot_id, crypto_helper=crypto_helper,
                )
                for folder in TRANSCRIPT_FOLDERS:
                    collection = recovered / folder
                    if not collection.exists():
                        collection.mkdir(mode=0o700)
                staged = _tree_summary(recovered, strict_root=True)
                if (staged.files != restored.transcript_files
                        or staged.bytes != restored.transcript_bytes):
                    raise MigrationError("The recovered snapshot changed before installation.")
                original = _tree_summary(codex)
                value = {
                    "format": "codex-vault-install",
                    "version": FORMAT_VERSION,
                    "status": "prepared",
                    "vault": verified.vault,
                    "snapshot_id": restored.snapshot_id,
                    "backup": str(backup),
                    "stage": str(stage),
                    "original": original.as_dict(),
                    "staged": staged.as_dict(),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                _atomic_json(_journal_path(home), value)
                journal_written = True
                if codex_running(str(home)):
                    raise MigrationError("Codex reopened before installation; recovery was cancelled.")
                _write_journal(home, value, "installing")
                for folder in TRANSCRIPT_FOLDERS:
                    live = codex / folder
                    saved = backup / folder
                    incoming = recovered / folder
                    if live.exists():
                        os.replace(live, saved)
                        _fsync_directory(codex)
                        _fsync_directory(backup)
                    os.replace(incoming, live)
                    _fsync_directory(recovered)
                    _fsync_directory(codex)
                _write_journal(home, value, "verifying")
                _same(
                    _tree_summary(codex), staged,
                    "The installed Codex history did not match the verified snapshot.",
                )
                _same(
                    _tree_summary(backup), original,
                    "The rollback backup did not match the displaced Codex history.",
                )
                if codex_running(str(home)):
                    raise MigrationError("Codex reopened during installation.")
                _remove_owned_tree(stage, home)
                _atomic_json(backup / "install-receipt.json", {
                    "format": "codex-vault-install-receipt",
                    "version": FORMAT_VERSION,
                    "snapshot_id": restored.snapshot_id,
                    "installed_at": datetime.now(timezone.utc).isoformat(),
                    "transcript_files": staged.files,
                    "transcript_bytes": staged.bytes,
                    "rollback_backup": str(backup),
                    "verified": True,
                })
                _remove_journal(home)
                journal_written = False
                return InstallResult(
                    vault=verified.vault, snapshot_id=restored.snapshot_id,
                    transcript_files=staged.files, transcript_bytes=staged.bytes,
                    backup=str(backup),
                )
            except Exception as error:
                if journal_written:
                    try:
                        value = _journal(home)
                        if value is not None:
                            _rollback(home, codex, value)
                    except Exception as rollback_error:
                        raise MigrationError(
                            "Vault installation stopped and automatic rollback could not be verified. "
                            "Keep Codex closed and use install recovery before retrying."
                        ) from rollback_error
                    raise MigrationError(
                        "Vault installation stopped safely and rollback was verified. "
                        "The previous Codex history was restored."
                    ) from error
                _remove_owned_tree(stage, home)
                try:
                    backup.rmdir()
                    _fsync_directory(home)
                except OSError:
                    pass
                if isinstance(error, (MigrationError, ValueError)):
                    raise
                raise MigrationError("Vault installation could not start safely.") from error
