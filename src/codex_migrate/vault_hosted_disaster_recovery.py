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
from codex_migrate.vault_remote_recovery import download_encrypted_snapshot
from codex_migrate.vault_recovery import snapshot_catalog
from codex_migrate.vault_schedule import _home


def recover_hosted_snapshot(
    source_home: str, output: str, device_id: str, *,
    max_bytes: int, snapshot_id: Optional[str] = None,
    crypto_helper: Optional[str] = None, apply: bool = False,
) -> dict:
    """Fetch and authenticate a published version without installing it.

    A server pointer change between planning and transfer fails closed. A
    partial download may be retried with the same selected snapshot; the
    underlying receiver checks every reused object's exact bytes.
    """
    if apply is not True:
        raise MigrationError("Hosted recovery requires explicit confirmation.")
    if type(max_bytes) is not int or max_bytes <= 0:
        raise MigrationError("The hosted recovery size limit is invalid.")
    home = str(_home(source_home))
    helper = _helper_path(crypto_helper)
    enrollment = HostedEnrollmentClient(SERVICE_ORIGIN)
    upload, recovery = enrollment.backup_clients(device_id, crypto_helper=str(helper))
    account_id, worker_origin, latest = recovery._latest()
    if (account_id != upload._account_id or
            worker_origin != upload._worker_origin or latest is None):
        raise MigrationError("The hosted recovery authority changed.")
    selected = (latest if snapshot_id is None or
                snapshot_id == latest["snapshotId"] else
                recovery.published_snapshot(snapshot_id,
                    expected_account_id=account_id,
                    expected_worker_origin=worker_origin))
    receipt, store = recovery.prepare(
        max_bytes=max_bytes, expected_pointer=(account_id, worker_origin, latest),
        selected_snapshot_id=snapshot_id)
    result = download_encrypted_snapshot(
        home, output, store, receipt, max_bytes=max_bytes,
        crypto_helper=str(helper))
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
