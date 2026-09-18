"""Crash-recoverable local installation of verified Codex Vault history."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
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


def _tree_summary(root: Path, *, strict_root: bool = False) -> TreeSummary:
    _require_unlinked_path(root)
    require_local(root)
    if strict_root:
        allowed = set(TRANSCRIPT_FOLDERS) | {"restore-receipt.json"}
        try:
            if any(item.name not in allowed for item in root.iterdir()):
                raise MigrationError("The recovered snapshot contains an unexpected item.")
        except OSError as error:
            raise MigrationError("The recovered snapshot could not be inspected safely.") from error
    records = []
    total = 0
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
                    records.append((relative, size, digest))
                    total += size
        except MigrationError:
            raise
        except OSError as error:
            raise MigrationError("Conversation history could not be inspected safely.") from error
    records.sort()
    aggregate = hashlib.sha256()
    for relative, size, digest in records:
        aggregate.update(relative.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(str(size).encode("ascii"))
        aggregate.update(b"\0")
        aggregate.update(digest.encode("ascii"))
        aggregate.update(b"\n")
    return TreeSummary(len(records), total, aggregate.hexdigest())


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
