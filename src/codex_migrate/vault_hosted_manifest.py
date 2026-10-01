"""Seal and stage one immutable manifest for a dark hosted backup run.

The saved ciphertext and its authenticated plaintext fingerprint bind retries
to the same snapshot bytes. A successful stage is not a published backup.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
from typing import Protocol, Tuple

from codex_migrate.errors import MigrationError
from codex_migrate.vault_backup import (
    _fsync_directory, _helper_path, _json_bytes, _require_unlinked_path,
    _run_helper,
)
from codex_migrate.vault_hosted_chunk_journal import HostedChunkJournal
from codex_migrate.vault_remote_inventory import (
    MAX_ENCRYPTED_MANIFEST_BYTES, _regular_file,
)
from codex_migrate.vault_remote_transfer import StagedObject, stage_encrypted_object


class ManifestUploadClient(Protocol):
    def object_store(self, reservation_id: str,
                     expected: dict[str, Tuple[int, str]], *,
                     apply: bool = False) -> object:
        """Provide an exact-key, reservation-scoped ciphertext store."""


def stage_hosted_manifest(manifest: dict, journal: HostedChunkJournal,
                          client: ManifestUploadClient, *, crypto_helper: str,
                          apply: bool = False) -> StagedObject:
    """Reuse exact sealed bytes on retry; never reseal a bound remote key."""
    if apply is not True:
        raise MigrationError("Hosted backup changes require explicit confirmation.")
    if (not isinstance(journal, HostedChunkJournal) or
            not isinstance(manifest, dict) or
            manifest.get("snapshot_id") != journal.snapshot_id):
        raise MigrationError("The hosted manifest belongs to another snapshot.")
    journal.ensure_private_directory()
    helper = _helper_path(crypto_helper)
    plaintext = _json_bytes(manifest)
    if len(plaintext) > MAX_ENCRYPTED_MANIFEST_BYTES - 64:
        raise MigrationError("The hosted manifest is too large for transfer.")
    plaintext_digest = hashlib.sha256(plaintext).hexdigest()
    relative = "manifests/" + journal.snapshot_id + ".cvmanifest"
    directory = journal.directory / "manifests"
    try:
        directory.mkdir(mode=0o700)
        _fsync_directory(journal.directory)
    except FileExistsError:
        pass
    info = directory.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or
            info.st_mode & 0o077):
        raise MigrationError("The hosted manifest folder is unsafe.")
    path = journal.directory / relative
    _require_unlinked_path(path, allow_missing_leaf=True)
    if not os.path.lexists(path):
        if journal.manifest_binding is not None:
            raise MigrationError("The bound hosted manifest is missing; refusing to reseal it.")
        _run_helper(helper, [
            "seal-manifest", "--key-id", journal.key_id,
            "--snapshot-id", journal.snapshot_id, "--output", str(path),
        ], input_data=plaintext)
    item = _regular_file(journal.directory, relative,
                         MAX_ENCRYPTED_MANIFEST_BYTES)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _fsync_directory(directory)
    fingerprint = _run_helper(helper, [
        "manifest-fingerprint", "--key-id", journal.key_id,
        "--snapshot-id", journal.snapshot_id, "--manifest", str(path),
    ])
    if (set(fingerprint) != {"snapshot_id", "plaintext_sha256", "ciphertext_sha256"} or
            fingerprint["snapshot_id"] != journal.snapshot_id or
            fingerprint["plaintext_sha256"] != plaintext_digest or
            fingerprint["ciphertext_sha256"] != item.sha256):
        raise MigrationError("The saved hosted manifest does not match this snapshot.")
    journal.bind_manifest(plaintext_digest, item.sha256, item.bytes)
    key = relative
    store = client.object_store(journal.reservation_id,
                                {key: (item.bytes, item.sha256)}, apply=True)
    staged, _ = stage_encrypted_object(journal.directory, item, store)
    return staged
