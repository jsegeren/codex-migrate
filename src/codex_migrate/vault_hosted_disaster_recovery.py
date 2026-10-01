"""Dark hosted recovery into an isolated encrypted Vault folder.

This never writes into live Codex history. Pairing a new device and importing
the separately held recovery key are distinct steps, not inferred from an
employee's old Mac or a paid checkout redirect.
"""

from __future__ import annotations

from typing import Optional

from codex_migrate.errors import MigrationError
from codex_migrate.vault_backup import _helper_path
from codex_migrate.vault_hosted_enrollment_client import HostedEnrollmentClient
from codex_migrate.vault_hosted_schedule import SERVICE_ORIGIN
from codex_migrate.vault_remote_recovery import (
    _check_stop, download_encrypted_snapshot, import_encrypted_recovery_key, prepare_encrypted_recovery,
)
from codex_migrate.vault_recovery import snapshot_catalog
from codex_migrate.vault_schedule import _home


def hosted_recovery_options(device_id: str, *,
                            crypto_helper: Optional[str] = None) -> dict:
    """Show the newest published and newest source-complete versions, read-only."""
    helper = _helper_path(crypto_helper)
    enrollment = HostedEnrollmentClient(SERVICE_ORIGIN)
    upload, recovery = enrollment.backup_clients(
        device_id, crypto_helper=str(helper))
    account_id, worker_origin, latest = recovery._latest()
    if account_id != upload._account_id or worker_origin != upload._worker_origin:
        raise MigrationError("The hosted recovery authority changed.")
    latest_complete = recovery.latest_source_complete_snapshot(
        expected_account_id=account_id,
        expected_worker_origin=worker_origin)
    if recovery._latest() != (account_id, worker_origin, latest):
        raise MigrationError("The hosted recovery versions changed.")
    if (latest is None and latest_complete is not None) or (
            latest is not None and latest["sourceCoverage"] == "complete" and
            latest_complete != latest):
        raise MigrationError("The hosted recovery versions changed.")
    return {"latest": latest, "latest_source_complete": latest_complete,
            "coverage_gap": latest is not None and
            latest["sourceCoverage"] != "complete"}


def _recovery_plan(
    device_id: str, *,
    max_bytes: int, snapshot_id: Optional[str] = None,
    crypto_helper: Optional[str] = None,
    cancelled=None,
) -> tuple:
    """Bind both recovery phases to the same authenticated published version."""
    if type(max_bytes) is not int or max_bytes <= 0:
        raise MigrationError("The hosted recovery size limit is invalid.")
    helper = _helper_path(crypto_helper)
    _check_stop(cancelled)
    enrollment = HostedEnrollmentClient(SERVICE_ORIGIN)
    upload, recovery = enrollment.backup_clients(device_id, crypto_helper=str(helper))
    _check_stop(cancelled)
    account_id, worker_origin, latest = recovery._latest()
    _check_stop(cancelled)
    if (account_id != upload._account_id or
            worker_origin != upload._worker_origin or latest is None):
        raise MigrationError("The hosted recovery authority changed.")
    if snapshot_id is None and latest["sourceCoverage"] != "complete":
        raise MigrationError(
            "The newest hosted backup has incomplete or unknown source coverage. "
            "Inspect hosted-backups and select a published version explicitly.")
    selected = (latest if snapshot_id is None or
                snapshot_id == latest["snapshotId"] else
                recovery.published_snapshot(snapshot_id,
                    expected_account_id=account_id,
                    expected_worker_origin=worker_origin))
    _check_stop(cancelled)
    controls = {"cancelled": cancelled} if cancelled is not None else {}
    receipt, store = recovery.prepare(
        max_bytes=max_bytes, expected_pointer=(account_id, worker_origin, latest),
        selected_snapshot_id=snapshot_id, **controls)
    return helper, selected, receipt, store


def prepare_hosted_recovery(
    source_home: str, output: str, device_id: str, *, max_bytes: int,
    snapshot_id: Optional[str] = None, crypto_helper: Optional[str] = None,
    apply: bool = False,
) -> dict:
    """Download only bound metadata; do not claim decryptable recovery."""
    if apply is not True:
        raise MigrationError("Hosted recovery preparation requires explicit confirmation.")
    home = str(_home(source_home))
    _, _, receipt, store = _recovery_plan(
        device_id, max_bytes=max_bytes, snapshot_id=snapshot_id,
        crypto_helper=crypto_helper)
    return prepare_encrypted_recovery(home, output, store, receipt,
                                      max_bytes=max_bytes)


def import_hosted_recovery_key(
    source_home: str, output: str, device_id: str, recovery_key: str, *,
    max_bytes: int, snapshot_id: Optional[str] = None,
    crypto_helper: Optional[str] = None, apply: bool = False,
) -> dict:
    """Verify the saved key against bound ciphertext before storing it."""
    if apply is not True:
        raise MigrationError("Hosted recovery key import requires explicit confirmation.")
    home = str(_home(source_home))
    helper, _, receipt, store = _recovery_plan(
        device_id, max_bytes=max_bytes, snapshot_id=snapshot_id,
        crypto_helper=crypto_helper)
    return import_encrypted_recovery_key(
        home, output, store, receipt, recovery_key, max_bytes=max_bytes,
        crypto_helper=str(helper))


def recover_hosted_snapshot(
    source_home: str, output: str, device_id: str, *,
    max_bytes: int, snapshot_id: Optional[str] = None,
    crypto_helper: Optional[str] = None, apply: bool = False,
    cancelled=None, progress=None,
) -> dict:
    """Fetch and authenticate a published version without installing it.

    A server pointer change between planning and transfer fails closed. A
    partial download may be retried with the same selected snapshot; the
    underlying receiver checks every reused object's exact bytes.
    """
    if apply is not True:
        raise MigrationError("Hosted recovery requires explicit confirmation.")
    _check_stop(cancelled)
    home = str(_home(source_home))
    controls = {"cancelled": cancelled} if cancelled is not None else {}
    helper, selected, receipt, store = _recovery_plan(
        device_id, max_bytes=max_bytes, snapshot_id=snapshot_id,
        crypto_helper=crypto_helper, **controls)
    _check_stop(cancelled)
    if progress is not None:
        controls["progress"] = progress
    result = download_encrypted_snapshot(
        home, output, store, receipt, max_bytes=max_bytes,
        crypto_helper=str(helper), **controls)
    catalog = snapshot_catalog(result.vault, snapshot=result.snapshot_id,
                               crypto_helper=str(helper))
    at_risk = {
        (item["collection"], item["thread_id"] or item["path"])
        for item in catalog
        if item["collection"] != "attachments" and item["at_risk"]
    }
    return {"vault": result.vault, "snapshot_id": result.snapshot_id,
            "downloaded_files": result.downloaded_files,
            "reused_files": result.reused_files,
            "encrypted_bytes_checked": result.encrypted_bytes_checked,
            "transcript_files": result.transcript_files,
            "source_coverage": selected["sourceCoverage"],
            "needs_attention": bool(at_risk) or
            selected["sourceCoverage"] != "complete",
            "at_risk_sources": len(at_risk)}
