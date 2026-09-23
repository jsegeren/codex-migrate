"""macOS LaunchAgent scheduling for verified Codex Vault backups.

The scheduler stores only local paths and timing metadata.  Conversation
content remains inside the encrypted Vault written by ``vault_backup``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import plistlib
import stat
import subprocess
import sys
from typing import Dict, List, Optional, Tuple
import uuid

from codex_migrate.errors import MigrationError
from codex_migrate.vault_backup import (
    _atomic_json,
    _fsync_directory,
    _helper_path,
    _metadata,
    _read_json,
    _require_unlinked_path,
    backup,
)
from codex_migrate.vault_recovery import verify_snapshot


LABEL = "com.segeren.codex-vault.backup"
CONFIG_FORMAT = "codex-vault-schedule"
CONFIG_VERSION = 2
ALLOWED_INTERVAL_HOURS = (6, 12, 24, 168)


@dataclass(frozen=True)
class SchedulePlan:
    vault: str
    interval_hours: int
    applied: bool = False

    def as_dict(self) -> Dict[str, object]:
        return asdict(self)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            return parsed.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError):
        pass
    raise MigrationError("The automatic backup timestamp is invalid.")


def _home(source_home: str) -> Path:
    home = Path(source_home).expanduser()
    if not home.is_absolute():
        raise ValueError("source home must be an absolute path")
    _require_unlinked_path(home)
    try:
        info = home.lstat()
    except OSError as error:
        raise MigrationError("The scheduled-backup home folder is unavailable.") from error
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise MigrationError("Scheduled backups require this account's owned home folder.")
    return home.resolve()


def _paths(source_home: str) -> Tuple[Path, Path, Path]:
    home = _home(source_home)
    state = home / "Library/Application Support/Codex Vault"
    plist = home / "Library/LaunchAgents" / (LABEL + ".plist")
    return state / "schedule.json", state / "last-run.json", plist


def _ensure_owned_directory(home: Path, destination: Path) -> None:
    try:
        relative = destination.relative_to(home)
    except ValueError:
        raise MigrationError("Scheduled-backup control files must stay in this account's home.") from None
    current = home
    for name in relative.parts:
        current = current / name
        try:
            os.mkdir(current, 0o700)
        except FileExistsError:
            pass
        except OSError as error:
            raise MigrationError("Scheduled-backup control folders could not be created safely.") from error
        try:
            info = current.lstat()
        except OSError as error:
            raise MigrationError("Scheduled-backup control folders could not be inspected safely.") from error
        if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or info.st_uid != os.getuid() or info.st_mode & 0o022):
            raise MigrationError("Scheduled-backup control folders have unsafe permissions.")


def _engine_command() -> List[str]:
    executable = Path(sys.executable).resolve()
    if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
        raise MigrationError("The scheduled-backup engine is unavailable.")
    if getattr(sys, "frozen", False):
        return [str(executable)]
    return [str(executable), "-m", "codex_migrate"]


def _interval(hours: int) -> int:
    if isinstance(hours, bool) or hours not in ALLOWED_INTERVAL_HOURS:
        raise ValueError("backup interval must be 6, 12, 24, or 168 hours")
    return hours * 60 * 60


def _safe_file(path: Path, maximum: int = 1024 * 1024) -> Optional[bytes]:
    if not path.exists():
        return None
    _require_unlinked_path(path)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o022 or info.st_size > maximum):
                raise MigrationError("Scheduled-backup control files have unsafe permissions.")
            return handle.read(maximum + 1)
    except MigrationError:
        raise
    except OSError as error:
        raise MigrationError("Scheduled-backup control files could not be read safely.") from error


def _safe_json(path: Path) -> Dict[str, object]:
    raw = _safe_file(path)
    if raw is None:
        raise MigrationError("The scheduled-backup control file is missing.")
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise MigrationError("The scheduled-backup control file is invalid.") from error
    if not isinstance(value, dict):
        raise MigrationError("The scheduled-backup control file is invalid.")
    return value


def _atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    _require_unlinked_path(path.parent)
    temporary = path.parent / ("." + path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        _fsync_directory(path.parent)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _launchctl(arguments: List[str]) -> subprocess.CompletedProcess:
    if platform.system() != "Darwin":
        raise MigrationError("Automatic Vault backups require macOS.")
    result = subprocess.run(
        ["/bin/launchctl"] + arguments,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode:
        raise MigrationError("macOS could not update the automatic backup schedule.")
    return result


def _loaded() -> bool:
    if platform.system() != "Darwin":
        return False
    result = subprocess.run(
        ["/bin/launchctl", "print", "gui/%d/%s" % (os.getuid(), LABEL)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    )
    return result.returncode == 0


def _configuration(path: Path) -> Dict[str, object]:
    value = _safe_json(path)
    required = {
        "format", "version", "source_home", "vault", "crypto_helper",
        "interval_seconds", "installed_at",
    }
    legacy = value.get("version") == 1 and set(value) == required
    current = value.get("version") == CONFIG_VERSION and set(value) == required | {"vault_key_id"}
    if not (legacy or current) or value.get("format") != CONFIG_FORMAT:
        raise MigrationError("The automatic backup configuration has an unsupported format.")
    if not all(isinstance(value.get(key), str) for key in (
            "source_home", "vault", "crypto_helper", "installed_at")):
        raise MigrationError("The automatic backup configuration is invalid.")
    if value.get("interval_seconds") not in tuple(hour * 3600 for hour in ALLOWED_INTERVAL_HOURS):
        raise MigrationError("The automatic backup interval is invalid.")
    if not all(Path(str(value[key])).is_absolute() for key in (
            "source_home", "vault", "crypto_helper")):
        raise MigrationError("The automatic backup configuration is invalid.")
    if current:
        try:
            if str(uuid.UUID(value["vault_key_id"])).lower() != value["vault_key_id"]:
                raise ValueError
        except (TypeError, ValueError, AttributeError):
            raise MigrationError("The automatic backup Vault identity is invalid.") from None
    return value


def _same_vault(vault: str, key_id: str) -> bool:
    root = Path(vault)
    try:
        _require_unlinked_path(root)
        return root.is_dir() and _metadata(_read_json(root / "vault.json")) == key_id
    except (MigrationError, OSError):
        return False


def _last_run(path: Path) -> Dict[str, object]:
    value = _safe_json(path)
    status = value.get("status")
    if status == "running":
        valid = set(value) == {"status", "started_at"} \
            and isinstance(value.get("started_at"), str)
    elif status == "completed":
        valid = set(value) == {
            "status", "completed_at", "snapshot_id",
            "transcript_files", "transcript_bytes",
        } and isinstance(value.get("completed_at"), str) \
            and isinstance(value.get("snapshot_id"), str) \
            and all(isinstance(value.get(key), int) and value[key] >= 0
                    for key in ("transcript_files", "transcript_bytes"))
    elif status == "needs_attention":
        valid = set(value) == {
            "status", "completed_at", "snapshot_id", "transcript_files",
            "transcript_bytes", "at_risk_threads",
        } and isinstance(value.get("completed_at"), str) \
            and isinstance(value.get("snapshot_id"), str) \
            and all(isinstance(value.get(key), int) and value[key] >= 0
                    for key in ("transcript_files", "transcript_bytes", "at_risk_threads"))
    elif status == "failed":
        valid = set(value) == {"status", "failed_at", "error"} \
            and isinstance(value.get("failed_at"), str) \
            and value.get("error") == (
                "Automatic backup stopped safely. The previous verified snapshot "
                "and local Codex data were not changed.")
    else:
        valid = False
    if not valid or any(len(str(value[key])) > 256 for key in value):
        raise MigrationError("The automatic backup status is invalid.")
    return value


def plan_schedule(
    source_home: str,
    vault: str,
    interval_hours: int = 24,
    *,
    crypto_helper: Optional[str] = None,
) -> SchedulePlan:
    home = _home(source_home)
    _interval(interval_hours)
    helper = _helper_path(crypto_helper)
    checked = verify_snapshot(vault, crypto_helper=str(helper))
    return SchedulePlan(checked.vault, interval_hours)


def install_schedule(
    source_home: str,
    vault: str,
    interval_hours: int = 24,
    *,
    crypto_helper: Optional[str] = None,
    engine_command: Optional[List[str]] = None,
) -> SchedulePlan:
    plan = plan_schedule(
        source_home, vault, interval_hours, crypto_helper=crypto_helper)
    home = _home(source_home)
    config_path, _, plist_path = _paths(str(home))
    helper = _helper_path(crypto_helper)
    vault_key_id = _metadata(_read_json(Path(plan.vault) / "vault.json"))
    interval_seconds = _interval(interval_hours)
    engine = list(engine_command or _engine_command())
    if not engine or not isinstance(engine[0], str) or not Path(engine[0]).is_absolute():
        raise ValueError("scheduled-backup engine command must begin with an absolute path")

    configuration = {
        "format": CONFIG_FORMAT,
        "version": CONFIG_VERSION,
        "source_home": str(home),
        "vault": plan.vault,
        "vault_key_id": vault_key_id,
        "crypto_helper": str(helper),
        "interval_seconds": interval_seconds,
        "installed_at": _now(),
    }
    program = engine + [
        "vault", "--source-home", str(home), "scheduled-run",
        "--config", str(config_path),
    ]
    plist = plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": program,
        "StartInterval": interval_seconds,
        "RunAtLoad": False,
        "ProcessType": "Background",
        "LowPriorityIO": True,
        "ThrottleInterval": 60,
        "EnvironmentVariables": {"HOME": str(home)},
        "StandardOutPath": "/dev/null",
        "StandardErrorPath": "/dev/null",
    }, fmt=plistlib.FMT_XML, sort_keys=True)

    previous_config = _safe_file(config_path)
    previous_plist = _safe_file(plist_path)
    was_loaded = _loaded()
    _ensure_owned_directory(home, config_path.parent)
    _ensure_owned_directory(home, plist_path.parent)
    _atomic_json(config_path, configuration, replace=True)
    _atomic_bytes(plist_path, plist)
    try:
        if was_loaded:
            _launchctl(["bootout", "gui/%d/%s" % (os.getuid(), LABEL)])
        _launchctl(["bootstrap", "gui/%d" % os.getuid(), str(plist_path)])
    except Exception:
        if previous_config is None:
            config_path.unlink(missing_ok=True)
        else:
            _atomic_bytes(config_path, previous_config)
        if previous_plist is None:
            plist_path.unlink(missing_ok=True)
        else:
            _atomic_bytes(plist_path, previous_plist)
            if was_loaded:
                try:
                    _launchctl(["bootstrap", "gui/%d" % os.getuid(), str(plist_path)])
                except Exception:
                    pass
        raise
    return SchedulePlan(plan.vault, interval_hours, applied=True)


def remove_schedule(source_home: str) -> Dict[str, object]:
    config_path, _, plist_path = _paths(source_home)
    if _loaded():
        _launchctl(["bootout", "gui/%d/%s" % (os.getuid(), LABEL)])
    config_path.unlink(missing_ok=True)
    plist_path.unlink(missing_ok=True)
    for directory in (config_path.parent, plist_path.parent):
        if directory.exists():
            _fsync_directory(directory)
    return {"enabled": False}


def schedule_status(source_home: str) -> Dict[str, object]:
    config_path, status_path, plist_path = _paths(source_home)
    if not config_path.exists() and not plist_path.exists():
        return {"enabled": False}
    if not config_path.exists() or not plist_path.exists():
        return {"enabled": False, "healthy": False,
                "error": "Automatic backup setup is incomplete. Turn it on again."}
    configuration = _configuration(config_path)
    if configuration["source_home"] != str(_home(source_home)):
        raise MigrationError("The automatic backup configuration belongs to another account.")
    _safe_file(plist_path)
    if configuration["version"] == 1:
        return {"enabled": True, "healthy": False,
                "vault": configuration["vault"],
                "interval_hours": configuration["interval_seconds"] // 3600,
                "error": "Turn off automatic backup, run a verified backup in the original Vault folder, then turn on daily backup again."}
    try:
        installed_at = _timestamp(configuration["installed_at"])
    except MigrationError:
        return {"enabled": True, "healthy": False,
                "error": "Automatic backup setup has an invalid timestamp. Turn it on again."}
    status = None
    if status_path.exists():
        try:
            status = _last_run(status_path)
        except MigrationError:
            status = {"status": "unknown"}
    if status and status["status"] != "unknown":
        timestamp_key = {
            "running": "started_at", "completed": "completed_at",
            "needs_attention": "completed_at", "failed": "failed_at",
        }[status["status"]]
        try:
            if _timestamp(status[timestamp_key]) < installed_at:
                status = None
        except MigrationError:
            status = {"status": "unknown"}
    result: Dict[str, object] = {
        "enabled": True,
        "healthy": _loaded(),
        "vault": configuration["vault"],
        "interval_hours": configuration["interval_seconds"] // 3600,
    }
    if status is not None:
        result["last_run"] = status
        if status.get("status") in ("needs_attention", "failed", "unknown"):
            result["healthy"] = False
            result["error"] = "The latest automatic backup needs attention. Earlier snapshots remain available."
    if result["healthy"]:
        if status and status["status"] == "completed":
            last_activity = status["completed_at"]
        elif status and status["status"] == "running":
            last_activity = status["started_at"]
        else:
            last_activity = configuration["installed_at"]
        try:
            age = (datetime.now(timezone.utc) - _timestamp(last_activity)).total_seconds()
        except MigrationError:
            age = float("inf")
        grace = configuration["interval_seconds"] * 2 + 3600
        if age < -3600 or age > grace:
            result["healthy"] = False
            result["error"] = "Automatic backup is overdue. Check the Vault folder and run a verified backup."
    if not result["healthy"]:
        result.setdefault("error", "The automatic backup service is not loaded. Turn it on again.")
    if not _same_vault(str(configuration["vault"]), str(configuration["vault_key_id"])):
        result["healthy"] = False
        result["error"] = "The scheduled Vault folder is missing or changed. Reconnect the original destination before the next backup."
    return result


def run_scheduled_backup(config_path: str) -> int:
    path = Path(config_path).expanduser()
    try:
        if not path.is_absolute():
            raise ValueError("schedule config must be an absolute path")
        configuration = _configuration(path)
        source_home = str(configuration["source_home"])
        expected_config, status_path, _ = _paths(source_home)
        if path.resolve() != expected_config.resolve():
            raise MigrationError("The automatic backup configuration is outside its managed location.")
        if configuration["version"] != CONFIG_VERSION:
            raise MigrationError("The automatic backup must be set up again to verify its Vault destination.")
        _atomic_json(status_path, {
            "status": "running", "started_at": _now(),
        }, replace=True)
        result = backup(
            source_home, str(configuration["vault"]),
            crypto_helper=str(configuration["crypto_helper"]),
            require_existing_key_id=str(configuration["vault_key_id"]),
        )
        if result.recovery_key is not None:
            raise MigrationError("Automatic backup cannot create an unacknowledged recovery key.")
        _atomic_json(status_path, {
            "status": "needs_attention" if result.needs_attention else "completed",
            "completed_at": _now(),
            "snapshot_id": result.snapshot_id,
            "transcript_files": result.transcript_files,
            "transcript_bytes": result.transcript_bytes,
            **({"at_risk_threads": result.at_risk_threads} if result.needs_attention else {}),
        }, replace=True)
        return 0
    except Exception:
        try:
            source_home = str(locals().get("configuration", {}).get("source_home", ""))
            if source_home:
                _, status_path, _ = _paths(source_home)
                _atomic_json(status_path, {
                    "status": "failed",
                    "failed_at": _now(),
                    "error": "Automatic backup stopped safely. The previous verified snapshot and local Codex data were not changed.",
                }, replace=True)
        except Exception:
            pass
        return 1
