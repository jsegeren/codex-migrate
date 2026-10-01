"""Stage the small final objects of one dark hosted-only Vault snapshot.

This assembles a client-checked ciphertext claim. Only independent service
verification and atomic publication may call the snapshot protected.
"""

from __future__ import annotations

import os
from pathlib import Path
import stat
from typing import Mapping, Tuple

from codex_migrate.errors import MigrationError
from codex_migrate.vault_backup import (
    FORMAT_VERSION, _atomic_json, _metadata, _read_json,
    _require_unlinked_path,
)
from codex_migrate.vault_hosted_chunk_journal import HostedChunkJournal
from codex_migrate.vault_hosted_manifest import (
    ManifestUploadClient, stage_hosted_manifest,
)
from codex_migrate.vault_hosted_snapshot_assembly import staged_snapshot_objects
from codex_migrate.vault_remote_inventory import _regular_file
from codex_migrate.vault_remote_transfer import StagedObject, stage_encrypted_object
from codex_migrate.vault_remote_writer import StagedRemoteFile


def _stage_public_json(journal: HostedChunkJournal, client: ManifestUploadClient,
                       relative: str, remote_key: str, value: dict) -> StagedObject:
    journal.ensure_private_directory()
    path = journal.directory / relative
    parent = path.parent
    if parent != journal.directory:
        try:
            parent.mkdir(mode=0o700)
        except FileExistsError:
            pass
        _require_unlinked_path(parent)
        info = parent.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or
                info.st_mode & 0o077):
            raise MigrationError("The hosted snapshot metadata folder is not private.")
    _require_unlinked_path(path, allow_missing_leaf=True)
    if os.path.lexists(path):
        if _read_json(path) != value:
            raise MigrationError("The hosted snapshot metadata changed on retry.")
    else:
        _atomic_json(path, value)
    item = _regular_file(journal.directory, relative, 1024 * 1024,
                         remote_key=remote_key)
    store = client.object_store(journal.reservation_id,
                                {remote_key: (item.bytes, item.sha256)}, apply=True)
    staged, _ = stage_encrypted_object(journal.directory, item, store)
    return staged


def stage_hosted_snapshot_tail(
    metadata: dict, manifest: dict,
    staged_files: Mapping[Tuple[str, str], StagedRemoteFile],
    journal: HostedChunkJournal, client: ManifestUploadClient, *,
    crypto_helper: str, apply: bool = False,
) -> Tuple[StagedObject, ...]:
    """Return the exact claimed object graph, not a publication receipt.

    Call only after all source transcripts have been staged and rechecked.
    Retrying requires the same journal, metadata, manifest and reservation.
    """
    if apply is not True:
        raise MigrationError("Hosted backup changes require explicit confirmation.")
    if (not isinstance(journal, HostedChunkJournal) or
            not isinstance(metadata, dict) or not isinstance(manifest, dict) or
            manifest.get("snapshot_id") != journal.snapshot_id or
            not isinstance(manifest.get("created_at"), str) or
            _metadata(metadata) != journal.key_id):
        raise MigrationError("The hosted snapshot metadata belongs to another Vault.")
    journal.ensure_private_directory()
    snapshot_id = journal.snapshot_id
    reference = {
        "format": "codex-vault-reference", "version": FORMAT_VERSION,
        "snapshot_id": snapshot_id, "created_at": manifest["created_at"],
        "manifest": "manifests/" + snapshot_id + ".cvmanifest",
    }
    staged_metadata = _stage_public_json(
        journal, client, "vault.json", "metadata/" + snapshot_id + ".json",
        metadata)
    staged_manifest = stage_hosted_manifest(
        manifest, journal, client, crypto_helper=crypto_helper, apply=True)
    staged_reference = _stage_public_json(
        journal, client, "refs/" + snapshot_id + ".json",
        "refs/" + snapshot_id + ".json", reference)
    return staged_snapshot_objects(snapshot_id, manifest, staged_files,
                                   staged_metadata, staged_manifest,
                                   staged_reference)
