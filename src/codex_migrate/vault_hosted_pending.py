"""Inspect or explicitly abandon one failed upload, never a published backup.

Only opaque IDs and state leave this boundary. A customer confirmation must
name the inspected reservation; a replacement run is never canceled instead.
The existing service/journal lifecycle owns quarantine, lost replies and cleanup.
"""

from contextlib import contextmanager
from pathlib import Path

from codex_migrate.errors import MigrationError
from codex_migrate.vault_backup import _helper_path, _metadata
from codex_migrate.vault_hosted_connection import active_binding
from codex_migrate.vault_hosted_enrollment_client import HostedEnrollmentClient
from codex_migrate.vault_hosted_live_run import HostedLiveBackupRun
from codex_migrate.vault_hosted_schedule import SERVICE_ORIGIN, _UUID
from codex_migrate.vault_schedule import _home, _pending_update, _safe_json, _update_lock


@contextmanager
def _bound_run(source_home, device_id, metadata_path, crypto_helper, expected_binding):
    if not isinstance(device_id, str) or not _UUID.fullmatch(device_id):
        raise MigrationError("The hosted backup device is invalid.")
    if not isinstance(metadata_path, str) or not Path(metadata_path).is_absolute():
        raise MigrationError("Select absolute existing Vault metadata.")
    home = str(_home(source_home))
    metadata = _safe_json(Path(metadata_path))
    key_id = _metadata(metadata)
    if type(metadata["version"]) is not int or "recovery_mode" in metadata:
        raise MigrationError("Pending-upload review requires an individual Vault key.")
    if expected_binding is not None and (
            not isinstance(expected_binding, dict) or
            set(expected_binding) != {"deviceId", "accountId", "vaultId", "keyId"} or
            any(not isinstance(value, str) or not _UUID.fullmatch(value)
                for value in expected_binding.values()) or
            expected_binding["deviceId"] != device_id or expected_binding["keyId"] != key_id):
        raise MigrationError("The pending upload does not match its saved connection and key.")
    helper = str(_helper_path(crypto_helper))
    with _update_lock(home, nonblocking=True) as marker:
        if _pending_update(marker) is not None:
            raise MigrationError("Wait for the app update before reviewing an upload.")
        if expected_binding is not None:
            device_id = active_binding(home, expected_binding)["deviceId"]
        try:
            upload, recovery = HostedEnrollmentClient(SERVICE_ORIGIN).backup_clients(
                device_id, crypto_helper=helper)
            if expected_binding is not None and (
                    upload._account_id != expected_binding["accountId"] or
                    upload._vault_id != expected_binding["vaultId"]):
                raise MigrationError("The hosted connection changed identity.")
            yield HostedLiveBackupRun(upload, recovery, home), upload, key_id
        except Exception:
            raise MigrationError("The pending upload could not be confirmed. Keep its state and "
                                 "retry this same connection, or contact joshua@segeren.com.") from None


def pending_hosted_upload(source_home, device_id, metadata_path, *, crypto_helper=None,
                          expected_binding=None):
    """Read exact service state; never release quota or infer backup protection."""
    with _bound_run(source_home, device_id, metadata_path, crypto_helper, expected_binding) as (run, upload, key):
        pending = run.pending(expected_key_id=key)
        if pending is None:
            return {"pending": False, "automatic_protection_verified": False}
        receipt = upload.reservation_receipt(pending["reservationId"])
        if (receipt["state"] not in ("active", "cleanup_pending", "released", "published") or
                receipt["state"] == "published" and receipt["snapshotId"] != pending["snapshotId"]):
            raise MigrationError("The reservation receipt changed identity.")
        return {"pending": True, "reservation_id": pending["reservationId"],
                "snapshot_id": pending["snapshotId"], "local_phase": pending["phase"],
                "remote_status": receipt["state"], "can_abandon": receipt["state"] != "published",
                "automatic_protection_verified": False}


def abandon_hosted_upload(source_home, device_id, metadata_path, *, reservation_id,
                          crypto_helper=None, expected_binding=None, apply=False):
    """Cancel only the reviewed unpublished upload; retain journals until release."""
    if apply is not True:
        raise MigrationError("Abandoning a pending upload requires explicit confirmation.")
    if not isinstance(reservation_id, str) or not _UUID.fullmatch(reservation_id):
        raise MigrationError("Confirm the exact inspected reservation ID.")
    with _bound_run(source_home, device_id, metadata_path, crypto_helper, expected_binding) as (run, _upload, key):
        status = run.abandon_pending(expected_key_id=key,
            expected_reservation_id=reservation_id, apply=True)
        if status not in ("cleanup_pending", "released"):
            raise MigrationError("The upload cleanup result is invalid.")
        return {"applied": True, "reservation_id": reservation_id, "status": status,
                "automatic_protection_verified": False}
