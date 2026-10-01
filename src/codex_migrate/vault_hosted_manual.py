"""Dark first/manual hosted backup entrypoint for release acceptance.

Use an already enrolled Keychain device and its existing encryption metadata.
This does not create recovery material, enroll a buyer, install a schedule,
or establish unattended protection. Provider origins are never caller input.
"""

from pathlib import Path
from typing import Optional

from codex_migrate.errors import MigrationError
from codex_migrate.vault_backup import _helper_path, _metadata
from codex_migrate.vault_hosted_enrollment_client import HostedEnrollmentClient
from codex_migrate.vault_hosted_live_run import HostedLiveBackupRun
from codex_migrate.vault_hosted_schedule import MAX_PRIOR_BYTES, SERVICE_ORIGIN, _UUID
from codex_migrate.vault_schedule import _home, _pending_update, _safe_json, _update_lock


def back_up_hosted_history(source_home: str, device_id: str, metadata_path: str, *,
                           crypto_helper: Optional[str] = None,
                           apply: bool = False) -> dict:
    """Publish or resume one snapshot, then reopen its remote sealed manifest.

    The live-run journal owns upload retries. A lost response must not create
    a different reservation. The app-update lock also excludes a concurrent
    LaunchAgent, so a manual run cannot race credential rotation or replacement.
    """
    if apply is not True:
        raise MigrationError("Hosted backup requires explicit confirmation.")
    if not isinstance(device_id, str) or not _UUID.fullmatch(device_id):
        raise MigrationError("The hosted backup device is invalid.")
    if not isinstance(metadata_path, str) or not Path(metadata_path).is_absolute():
        raise MigrationError("Select an absolute path to existing Vault metadata.")
    home = str(_home(source_home))
    metadata = _safe_json(Path(metadata_path))
    key_id = _metadata(metadata)
    if type(metadata["version"]) is not int or "recovery_mode" in metadata:
        raise MigrationError("This backup path requires an individual Vault key.")
    helper = _helper_path(crypto_helper)
    with _update_lock(home, nonblocking=True) as marker_path:
        if _pending_update(marker_path) is not None:
            raise MigrationError("Wait for the app update before starting hosted backup.")
        try:
            enrollment = HostedEnrollmentClient(SERVICE_ORIGIN)
            upload, recovery = enrollment.backup_clients(device_id, crypto_helper=str(helper))
            result = HostedLiveBackupRun(upload, recovery, home).back_up_live_history(
                metadata, crypto_helper=str(helper), max_prior_bytes=MAX_PRIOR_BYTES,
                apply=True)
            unchanged = result.get("unchanged") is True
            snapshot_id = result.get("lastGoodSnapshotId" if unchanged else "snapshotId")
            risk = result.get("atRiskThreads")
            coverage = result.get("sourceCoverage")
            if (not isinstance(snapshot_id, str) or not _UUID.fullmatch(snapshot_id) or
                    type(risk) is not int or risk < 0 or
                    coverage not in ("complete", "needs_attention", "unknown")):
                raise MigrationError("The hosted backup receipt is invalid.")
            # Publication alone is insufficient: independently fetch the
            # exact remote manifest and authenticate it with this Mac's key.
            observed, catalog = recovery.prior_catalog(
                key_id=key_id, crypto_helper=str(helper), max_bytes=MAX_PRIOR_BYTES,
                expected_snapshot_id=snapshot_id, expected_account_id=upload._account_id)
            if observed != snapshot_id:
                raise MigrationError("The hosted backup changed during verification.")
            catalog_risk = len({
                (item["collection"], item.get("thread_id") or item["path"])
                for item in catalog if item["collection"] != "attachments"
                and item.get("at_risk") is not False
            })
            if catalog_risk != risk:
                raise MigrationError("The hosted backup loss evidence disagrees.")
        except Exception:
            # Transport/helper failures can contain bearer tokens, signed
            # URLs or source text. Never forward those exceptions to the CLI.
            raise MigrationError(
                "Hosted backup could not be confirmed. Do not remove any pending state. "
                "Retry with the same device and Keychain-held key, "
                "or contact joshua@segeren.com.") from None
    return {
        "applied": True, "snapshot_id": snapshot_id,
        "status": ("needs_attention" if risk or coverage != "complete" else
                   "unchanged" if unchanged else "published"),
        "source_coverage": coverage, "at_risk_threads": risk,
        "automatic_protection_verified": False,
    }
