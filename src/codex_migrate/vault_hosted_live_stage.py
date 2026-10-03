"""Stage one hosted-only snapshot against its reserved last-good version.

This is a dark client path. It does not schedule, bill, publish, or claim that
the buyer has a protected backup; the service must verify and publish later.
"""

from __future__ import annotations

from codex_migrate.errors import MigrationError
from codex_migrate.vault_backup import DEFAULT_CHUNK_SIZE, _metadata
from codex_migrate.vault_hosted_chunk_journal import HostedChunkJournal
from codex_migrate.vault_hosted_recovery_client import HostedRecoveryClient
from codex_migrate.vault_hosted_snapshot_stage import (
    HostedSnapshotStage, stage_hosted_snapshot,
)
from codex_migrate.vault_hosted_upload_client import HostedUploadClient


def stage_reserved_hosted_snapshot(
    source_home: str, metadata: dict, journal: HostedChunkJournal,
    upload: HostedUploadClient, recovery: HostedRecoveryClient, *,
    crypto_helper: str, max_prior_bytes: int,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    window_bytes: int = 64 * 1024 * 1024,
    apply: bool = False,
    deletion_approval=None,
) -> HostedSnapshotStage:
    """Read the exact prior catalog before staging any live transcript.

    The caller must persist the base returned by ``reserve_with_base`` in a
    version-2 chunk journal before invoking this function. A first backup has
    an explicit null base; an unbound version-1 journal is never interpreted as
    empty history. A later last-good change still fails at server publication.
    """
    if apply is not True:
        raise MigrationError("Hosted backup changes require explicit confirmation.")
    if (not isinstance(journal, HostedChunkJournal) or
            not isinstance(upload, HostedUploadClient) or
            not isinstance(recovery, HostedRecoveryClient) or
            not isinstance(metadata, dict) or _metadata(metadata) != journal.key_id or
            journal.account_id != upload._account_id or
            journal.vault_id != upload._vault_id or
            journal.vault_id != recovery._vault_id or
            upload._service_origin != recovery._origin or
            upload._device_token != recovery._device_token):
        raise MigrationError("The hosted snapshot clients or identity do not match.")
    journal.ensure_private_directory()
    base = journal.base_snapshot_id
    options = {} if deletion_approval is None else {"include_version": True}
    prior = recovery.prior_catalog(
        key_id=journal.key_id, crypto_helper=crypto_helper,
        max_bytes=max_prior_bytes, expected_snapshot_id=base,
        expected_account_id=journal.account_id, include_chunks=True, **options)
    observed, catalog = prior[:2]
    if observed != base:
        raise MigrationError("The hosted backup changed after reservation.")
    if deletion_approval is not None:
        from codex_migrate.vault_hosted_rebaseline import RebaselineApproval
        if not isinstance(deletion_approval, RebaselineApproval) or len(prior) != 3:
            raise MigrationError("The intentional-deletion approval is invalid.")
        deletion_approval.check_authority(source_home, journal.account_id, journal.vault_id, journal.key_id)
        from codex_migrate.vault_hosted_source_review import _validate_prior
        _validate_prior(catalog, prior[2])
        if prior[2] != deletion_approval.value["priorVersion"]:
            raise MigrationError("The authenticated prior format changed after review.")
        options = {"deletion_approval": deletion_approval}
    return stage_hosted_snapshot(
        source_home, metadata, catalog, journal, upload,
        crypto_helper=crypto_helper, chunk_size=chunk_size,
        window_bytes=window_bytes, apply=True, **options)
