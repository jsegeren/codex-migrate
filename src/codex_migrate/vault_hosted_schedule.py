"""Dark macOS schedule for verified hosted conversation backups.

The LaunchAgent stores no bearer or recovery key. Each wake reads the device
credential from this account's Keychain and obtains the Worker origin from the
authenticated service. Neither a local timer nor an unchanged check is a new
off-device backup receipt.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import platform
import plistlib
import pwd
import re
import subprocess
import time
from typing import Optional

from codex_migrate.errors import MigrationError
from codex_migrate.vault_backup import (
    _atomic_json, _fsync_directory, _helper_path, _metadata,
)
from codex_migrate.vault_hosted_enrollment_client import HostedEnrollmentClient
from codex_migrate.vault_hosted_live_run import HostedLiveBackupRun
from codex_migrate.vault_hosted_upload_client import HostedUploadClient
from codex_migrate.vault_schedule import (
    _atomic_bytes, _engine_command, _ensure_owned_directory, _home,
    _launchctl, _pending_update, _safe_file, _safe_json, _timestamp,
    _update_lock,
)


LABEL = "com.segeren.codex-vault.hosted-backup"
SERVICE_ORIGIN = "https://codexbackup.segeren.com"
INTERVAL_SECONDS = 30 * 60
ROTATION_INTERVAL = timedelta(days=14)
MAX_PRIOR_BYTES = 64 * 1024 * 1024
_FORMAT = "codex-vault-hosted-schedule"
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")
_FAILED = ("Hosted backup stopped safely. The last verified remote snapshot "
           "was not replaced; this Mac needs attention.")
_COST_HISTORY_FORMAT = "codex-vault-hosted-cost-history"
_COST_HISTORY_LIMIT = 1024


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cost_metrics(started: float, upload: object = None,
                  published: object = None) -> dict:
    """Private counts only; never persist an object key, token, or transcript."""
    result = {"elapsed_ms": max(0, int((time.monotonic() - started) * 1000))}
    if isinstance(upload, HostedUploadClient):
        result["upload_service_attempts"] = upload.service_request_counts()
        result["worker_attempts"] = upload.worker_attempt_counts()
    if isinstance(published, dict):
        for field, target in (("restagedPlaintextBytes", "restaged_plaintext_bytes"),
                              ("reusedPlaintextBytes", "reused_plaintext_bytes"),
                              ("encryptedBytes", "remote_claimed_ciphertext_bytes")):
            value = published.get(field)
            if type(value) is int and value >= 0:
                result[target] = value
    return result


def _append_cost_history(status_path: Path, status: dict) -> None:
    """Keep bounded private run evidence; diagnostics cannot block protection."""
    try:
        history_path = status_path.with_name("hosted-cost-history.json")
        if history_path.exists():
            if history_path.lstat().st_mode & 0o077:
                raise MigrationError("The hosted cost history is not private.")
            history = _safe_json(history_path)
            if (set(history) != {"format", "version", "runs"} or
                    history["format"] != _COST_HISTORY_FORMAT or
                    history["version"] != 1 or type(history["version"]) is not int or
                    not isinstance(history["runs"], list) or
                    len(history["runs"]) > _COST_HISTORY_LIMIT):
                raise MigrationError("The hosted cost history is invalid.")
            runs = history["runs"]
        else:
            runs = []
        sample = {"checked_at": status["checked_at"],
                  "status": status["status"],
                  "cost_metrics": status["cost_metrics"]}
        if runs and runs[-1] == sample:
            return
        _atomic_json(history_path, {
            "format": _COST_HISTORY_FORMAT, "version": 1,
            "runs": (runs + [sample])[-_COST_HISTORY_LIMIT:],
        }, replace=True)
    except Exception:
        # A corrupt or unavailable measurement file cannot stop a backup or
        # overwrite its last-good remote receipt. Missing samples are visible
        # as gaps during the separate economics acceptance review.
        return


def _write_run_status(path: Path, status: dict) -> None:
    _atomic_json(path, status, replace=True)
    if "cost_metrics" in status:
        _append_cost_history(path, status)


def _paths(source_home: str) -> tuple:
    home = _home(source_home)
    root = home / "Library/Application Support/Codex Vault"
    return (root / "hosted-schedule.json", root / "hosted-last-run.json",
            root / "hosted-last-good.json",
            home / "Library/LaunchAgents" / (LABEL + ".plist"))


def _rotation_path(source_home: str) -> Path:
    return _home(source_home) / "Library/Application Support/Codex Vault/hosted-rotation.json"


def _configuration(path: Path) -> dict:
    value = _safe_json(path)
    base = {"format", "version", "source_home", "account_id",
            "vault_id", "device_id", "key_metadata", "installed_at"}
    if (set(value) not in (base, base | {"session_rotated_at"}) or
            value.get("format") != _FORMAT or
            value.get("version") not in (1, 2) or
            type(value.get("version")) is not int or
            (value["version"] == 1 and set(value) != base) or
            (value["version"] == 2 and set(value) != base | {"session_rotated_at"}) or
            not isinstance(value.get("source_home"), str) or
            not Path(value["source_home"]).is_absolute() or
            any(not isinstance(value.get(key), str) or not _UUID.fullmatch(value[key])
                for key in ("account_id", "vault_id", "device_id")) or
            not isinstance(value.get("key_metadata"), dict)):
        raise MigrationError("The hosted backup schedule is invalid.")
    _metadata(value["key_metadata"])
    _timestamp(value.get("installed_at"))
    if value["version"] == 2 and value["session_rotated_at"] is not None:
        _timestamp(value["session_rotated_at"])
    return value


def _rotate_if_due(config_path: Path, configuration: dict,
                   enrollment: HostedEnrollmentClient, helper: Path) -> dict:
    """Durably hand a scheduled run to a new bearer before the old one expires."""
    pending_path = _rotation_path(configuration["source_home"])
    pending = _safe_json(pending_path) if pending_path.exists() else None
    if pending is not None:
        if (set(pending) != {"old_device_id", "new_device_id"} or
                any(not isinstance(pending.get(key), str) or
                    not _UUID.fullmatch(pending[key])
                    for key in ("old_device_id", "new_device_id")) or
                pending["old_device_id"] == pending["new_device_id"]):
            raise MigrationError("The hosted device handoff is invalid.")
        if pending["new_device_id"] == configuration["device_id"]:
            # A crash after saving the new schedule but before cleanup.
            pending_path.unlink()
            _fsync_directory(pending_path.parent)
            return configuration
        if pending["old_device_id"] != configuration["device_id"]:
            raise MigrationError("The hosted device handoff changed identity.")
    else:
        rotated_at = configuration.get("session_rotated_at")
        if rotated_at is not None:
            age = datetime.now(timezone.utc) - _timestamp(rotated_at)
            if timedelta(0) <= age < ROTATION_INTERVAL:
                return configuration
        new_device_id = enrollment.create_device(crypto_helper=str(helper), apply=True)
        pending = {"old_device_id": configuration["device_id"],
                   "new_device_id": new_device_id}
        _atomic_json(pending_path, pending, replace=False)

    identity = enrollment.rotate_device(
        pending["old_device_id"], pending["new_device_id"],
        configuration["account_id"], configuration["vault_id"],
        crypto_helper=str(helper), apply=True)
    if (identity != {"accountId": configuration["account_id"],
                     "vaultId": configuration["vault_id"],
                     "deviceId": pending["new_device_id"]}):
        raise MigrationError("The hosted device handoff changed identity.")
    updated = {**configuration, "version": 2,
               "device_id": pending["new_device_id"],
               "session_rotated_at": _now()}
    _atomic_json(config_path, updated, replace=True)
    pending_path.unlink()
    _fsync_directory(pending_path.parent)
    return updated


def _loaded() -> bool:
    if platform.system() != "Darwin":
        return False
    result = subprocess.run(
        ["/bin/launchctl", "print", "gui/%d/%s" % (os.getuid(), LABEL)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    return result.returncode == 0


def install_hosted_schedule(source_home: str, device_id: str, metadata: dict, *,
                            crypto_helper: Optional[str] = None,
                            engine_command: Optional[list] = None,
                            apply: bool = False) -> dict:
    """Install only after a remote snapshot decrypts with this Mac's key.

    This is intentionally not exposed in the buyer UI until business identity,
    recovery custody, subscription, and clean-Mac acceptance are certified.
    """
    if apply is not True:
        raise MigrationError("Hosted scheduling requires explicit confirmation.")
    home = _home(source_home)
    if not isinstance(device_id, str) or not _UUID.fullmatch(device_id):
        raise MigrationError("The hosted backup device is invalid.")
    key_id = _metadata(metadata)
    helper = _helper_path(crypto_helper)
    enrollment = HostedEnrollmentClient(SERVICE_ORIGIN)
    upload, recovery = enrollment.backup_clients(device_id, crypto_helper=str(helper))
    latest = recovery.latest_snapshot(expected_account_id=upload._account_id)
    if latest is None:
        raise MigrationError("Make and verify the first hosted backup before scheduling.")
    if latest.get("sourceCoverage") != "complete":
        raise MigrationError(
            "The first hosted backup has incomplete or unknown source coverage. "
            "Review it before scheduling protected backups.")
    observed, catalog = recovery.prior_catalog(
        key_id=key_id, crypto_helper=str(helper), max_bytes=MAX_PRIOR_BYTES,
        expected_snapshot_id=latest["snapshotId"],
        expected_account_id=upload._account_id)
    if observed != latest["snapshotId"]:
        raise MigrationError("The first hosted backup could not be opened safely.")
    if any(item.get("at_risk") is True for item in catalog):
        raise MigrationError("Review the first hosted backup's at-risk threads before scheduling.")

    config_path, status_path, good_path, plist_path = _paths(str(home))
    engine = list(engine_command or _engine_command())
    if not engine or not isinstance(engine[0], str) or not Path(engine[0]).is_absolute():
        raise MigrationError("The hosted backup engine is unavailable.")
    try:
        account_home = pwd.getpwuid(os.getuid()).pw_dir
    except KeyError as error:
        raise MigrationError("The macOS account home is unavailable.") from error
    configuration = {
        "format": _FORMAT, "version": 2, "source_home": str(home),
        "account_id": upload._account_id, "vault_id": upload._vault_id,
        "device_id": device_id, "key_metadata": metadata,
        "installed_at": _now(), "session_rotated_at": None,
    }
    program = engine + ["vault", "--source-home", str(home),
                        "hosted-scheduled-run", "--config", str(config_path)]
    plist = plistlib.dumps({
        "Label": LABEL, "ProgramArguments": program,
        "StartInterval": INTERVAL_SECONDS, "RunAtLoad": True,
        "ProcessType": "Background", "LowPriorityIO": True,
        "ThrottleInterval": 60, "EnvironmentVariables": {"HOME": account_home},
        "StandardOutPath": "/dev/null", "StandardErrorPath": "/dev/null",
    }, fmt=plistlib.FMT_XML, sort_keys=True)
    with _update_lock(str(home), nonblocking=True) as marker_path:
        if _pending_update(marker_path) is not None:
            raise MigrationError("Wait for the app update before enabling hosted backup.")
        if _rotation_path(str(home)).exists():
            raise MigrationError("Complete the pending hosted device handoff first.")
        current = enrollment.resolve(device_id, crypto_helper=str(helper))
        if current != {"accountId": upload._account_id,
                       "vaultId": upload._vault_id, "deviceId": device_id}:
            raise MigrationError("The hosted backup device changed identity.")
        previous_config = _safe_file(config_path)
        previous_plist = _safe_file(plist_path)
        previous_good = _safe_file(good_path)
        previous_status = _safe_file(status_path)
        was_loaded = _loaded()
        _ensure_owned_directory(home, config_path.parent)
        _ensure_owned_directory(home, plist_path.parent)
        try:
            _atomic_json(config_path, configuration, replace=True)
            _atomic_bytes(plist_path, plist)
            # Observed now, not first published now. Never invent a recovery time.
            _atomic_json(good_path, {"snapshot_id": latest["snapshotId"],
                                     "observed_at": _now()}, replace=True)
            _atomic_json(status_path, {"status": "awaiting_check",
                                       "checked_at": _now()}, replace=True)
            if was_loaded:
                _launchctl(["bootout", "gui/%d/%s" % (os.getuid(), LABEL)])
            _launchctl(["bootstrap", "gui/%d" % os.getuid(), str(plist_path)])
        except Exception:
            for path, previous in ((config_path, previous_config),
                                   (plist_path, previous_plist),
                                   (good_path, previous_good),
                                   (status_path, previous_status)):
                if previous is None:
                    path.unlink(missing_ok=True)
                else:
                    _atomic_bytes(path, previous)
            if was_loaded:
                try:
                    _launchctl(["bootstrap", "gui/%d" % os.getuid(), str(plist_path)])
                except Exception:
                    pass
            raise
    return {"enabled": True, "interval_minutes": 30,
            "last_good_snapshot_id": latest["snapshotId"]}


def run_hosted_scheduled_backup(config_path: str) -> int:
    """One unattended check; failures are visible and leave last-good intact."""
    started = time.monotonic()
    upload = None
    try:
        path = Path(config_path).expanduser()
        if not path.is_absolute():
            raise MigrationError("The hosted backup schedule path is invalid.")
        configuration = _configuration(path)
        home = str(_home(configuration["source_home"]))
        expected, status_path, good_path, _ = _paths(home)
        if path.resolve() != expected.resolve():
            raise MigrationError("The hosted backup schedule is outside its managed location.")
        with _update_lock(home) as marker_path:
            marker = _pending_update(marker_path)
            if marker is not None:
                _atomic_json(marker_path, {**marker, "deferred": True}, replace=True)
                _write_run_status(status_path, {
                    "status": "failed", "checked_at": _now(), "error": _FAILED,
                    "cost_metrics": _cost_metrics(started),
                })
                return 0
            _atomic_json(status_path, {"status": "running", "checked_at": _now()},
                         replace=True)
            helper = _helper_path(None)
            enrollment = HostedEnrollmentClient(SERVICE_ORIGIN)
            configuration = _rotate_if_due(path, configuration, enrollment, helper)
            upload, recovery = enrollment.backup_clients(
                configuration["device_id"], crypto_helper=str(helper))
            if (upload._account_id != configuration["account_id"] or
                    upload._vault_id != configuration["vault_id"]):
                raise MigrationError("The hosted backup device changed identity.")
            run = HostedLiveBackupRun(upload, recovery, home)
            result = run.back_up_live_history(
                configuration["key_metadata"], crypto_helper=str(helper),
                max_prior_bytes=MAX_PRIOR_BYTES, apply=True)
            if result.get("unchanged") is True:
                snapshot_id = result["lastGoodSnapshotId"]
                state = ("unchanged" if result.get("atRiskThreads") == 0 and
                         result.get("sourceCoverage") == "complete"
                         else "needs_attention")
            else:
                snapshot_id = result["snapshotId"]
                risk = result.get("atRiskThreads")
                state = "verified" if risk == 0 else "needs_attention"
            if not isinstance(snapshot_id, str) or not _UUID.fullmatch(snapshot_id):
                raise MigrationError("The hosted backup receipt is invalid.")
            if state == "verified":
                _atomic_json(good_path, {"snapshot_id": snapshot_id,
                                         "observed_at": _now()}, replace=True)
            _write_run_status(status_path, {
                "status": state, "checked_at": _now(),
                "snapshot_id": snapshot_id,
                **({"title_index_unavailable": True}
                   if result.get("titleIndexUnavailable") is True else {}),
                "cost_metrics": _cost_metrics(started, upload, result),
            })
            return 0
    except Exception:
        try:
            if "status_path" in locals():
                _write_run_status(status_path, {
                    "status": "failed", "checked_at": _now(), "error": _FAILED,
                    "cost_metrics": _cost_metrics(started, upload),
                })
        except Exception:
            pass
        return 1


def hosted_schedule_status(source_home: str) -> dict:
    """Report local schedule health; never substitute it for a remote receipt."""
    config_path, status_path, good_path, plist_path = _paths(source_home)
    if not config_path.exists() and not plist_path.exists():
        return {"enabled": False}
    if not config_path.exists() or not plist_path.exists():
        return {"enabled": False, "healthy": False,
                "error": "Hosted backup setup is incomplete."}
    configuration = _configuration(config_path)
    if configuration["source_home"] != str(_home(source_home)):
        raise MigrationError("The hosted backup schedule belongs to another account.")
    _safe_file(plist_path)
    result = {"enabled": True, "healthy": False,
              "loaded": _loaded(), "interval_minutes": 30,
              "last_good_snapshot_id": None, "last_checked_at": None,
              "status": "awaiting_check"}
    if good_path.exists():
        good = _safe_json(good_path)
        if (set(good) != {"snapshot_id", "observed_at"} or
                not isinstance(good.get("snapshot_id"), str) or
                not _UUID.fullmatch(good["snapshot_id"])):
            raise MigrationError("The hosted last-good receipt is invalid.")
        _timestamp(good.get("observed_at"))
        result["last_good_snapshot_id"] = good["snapshot_id"]
    if status_path.exists():
        status = _safe_json(status_path)
        if (not isinstance(status.get("status"), str) or
                status["status"] not in {"awaiting_check", "running", "failed", "unchanged",
                                          "verified", "needs_attention"} or
                not isinstance(status.get("checked_at"), str) or
                not isinstance(status.get("title_index_unavailable", False), bool)):
            raise MigrationError("The hosted backup status is invalid.")
        checked = _timestamp(status["checked_at"])
        result["last_checked_at"] = status["checked_at"]
        result["status"] = status["status"]
        if status.get("title_index_unavailable") is True:
            result["title_index_unavailable"] = True
        age = (datetime.now(timezone.utc) - checked).total_seconds()
        result["healthy"] = (result["loaded"] and result["last_good_snapshot_id"]
                             is not None and status["status"] in ("unchanged", "verified")
                             and -3600 <= age <= INTERVAL_SECONDS * 2 + 900)
    if not result["healthy"]:
        result["error"] = "Hosted backup needs attention or its scheduled check is overdue."
    return result


def remove_hosted_schedule(source_home: str, *, apply: bool = False) -> dict:
    """Turn off only this LaunchAgent; never delete remote or local snapshots."""
    if apply is not True:
        raise MigrationError("Disabling hosted backup requires explicit confirmation.")
    home = str(_home(source_home))
    config_path, _, _, plist_path = _paths(home)
    with _update_lock(home, nonblocking=True) as marker_path:
        if _pending_update(marker_path) is not None:
            raise MigrationError("Wait for the app update before changing hosted backup.")
        if _loaded():
            _launchctl(["bootout", "gui/%d/%s" % (os.getuid(), LABEL)])
        config_path.unlink(missing_ok=True)
        plist_path.unlink(missing_ok=True)
        for directory in (config_path.parent, plist_path.parent):
            if directory.exists():
                _fsync_directory(directory)
    return {"enabled": False}
