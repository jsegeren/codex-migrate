"""Dark whole-snapshot staging without a full local ciphertext Vault.

This freezes only transcript bytes and metadata long enough to stage a client-
checked object graph. It never publishes, schedules, or claims protection.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from codex_migrate.errors import MigrationError
from codex_migrate.source_availability import check_info, require_local
from codex_migrate.vault_backup import (
    DEFAULT_CHUNK_SIZE, _canonical_macos_path, _metadata,
    _paginated_history_unprotected, _source_files,
)
from codex_migrate.vault_hosted_chunk_journal import HostedChunkJournal
from codex_migrate.vault_hosted_snapshot_tail import stage_hosted_snapshot_tail
from codex_migrate.vault_identity import (
    TranscriptChanged, loss_warnings, mark_simultaneous_conflicts,
    scan_transcript, title_index,
)
from codex_migrate.vault_local_lock import local_history_lock
from codex_migrate.vault_remote_transfer import StageResult, StagedObject
from codex_migrate.vault_remote_writer import (
    RemoteAwareClient, StagedRemoteFile, stage_remote_aware_file_windowed,
    stage_remote_aware_records,
)


@dataclass(frozen=True)
class HostedSnapshotStage:
    """Client-side ciphertext facts; not a server publication receipt."""

    snapshot_id: str
    reservation_id: str
    objects: Tuple[StagedObject, ...]
    transcript_files: int
    transcript_bytes: int
    at_risk_threads: int

    def upload_claim(self) -> StageResult:
        """Counts are unknown for the mixed incremental path, never zeroed."""
        return StageResult(self.snapshot_id, None, None,
                           sum(item.bytes for item in self.objects), self.objects)


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def stage_hosted_snapshot(
    source_home: str, metadata: dict, previous_catalog: Sequence[dict],
    journal: HostedChunkJournal, client: RemoteAwareClient, *,
    crypto_helper: str, chunk_size: int = DEFAULT_CHUNK_SIZE,
    window_bytes: int = 64 * 1024 * 1024, apply: bool = False,
) -> HostedSnapshotStage:
    """Stage every supported history source under one sealed reservation.

    `previous_catalog` must come from the authenticated prior last-good
    manifest, or be empty only after the service proves this Vault has none.
    A source change or changed file set refuses publication; retry may reuse
    exact journaled ciphertext after the source settles.
    """
    if apply is not True:
        raise MigrationError("Hosted backup changes require explicit confirmation.")
    if (not isinstance(journal, HostedChunkJournal) or
            not isinstance(metadata, dict) or _metadata(metadata) != journal.key_id or
            not isinstance(previous_catalog, (list, tuple)) or
            len(previous_catalog) > 100_000 or
            any(not isinstance(item, dict) for item in previous_catalog)):
        raise MigrationError("The hosted snapshot source or prior catalog is invalid.")
    journal.ensure_private_directory()
    codex_root = _canonical_macos_path(Path(source_home) / ".codex")
    if journal.directory == codex_root or codex_root in journal.directory.parents:
        raise MigrationError("Hosted backup state cannot be inside Codex history.")
    with local_history_lock(source_home):
        has_paginated = _paginated_history_unprotected(source_home)
        files = _source_files(source_home)
        if len(files) > 100_000:
            raise MigrationError("The hosted snapshot has too many transcripts.")
        titles = title_index(source_home)
        created_at = journal.snapshot_time()
        manifest_files: List[dict] = []
        stages: Dict[Tuple[str, str], StagedRemoteFile] = {}
        source_facts: Dict[Tuple[str, str], tuple[int, int, int, int, int]] = {}
        total_bytes = 0
        for folder, path, relative in files:
            before = check_info(path.lstat())
            identity = (folder, relative)
            try:
                signals = scan_transcript(path, relative, titles)
            except TranscriptChanged:
                raise MigrationError(
                    "A conversation changed during hosted backup; retry after it settles.") from None
            if _identity(check_info(path.lstat())) != _identity(before):
                raise MigrationError("A conversation changed during hosted identity inspection.")
            staged = stage_remote_aware_file_windowed(
                path, journal.key_id, client, journal.reservation_id, journal,
                crypto_helper=crypto_helper, chunk_size=chunk_size,
                window_bytes=window_bytes, apply=True)
            if (_identity(check_info(path.lstat())) != _identity(before) or
                    staged.size != before.st_size):
                raise MigrationError("A conversation changed during hosted backup.")
            source_facts[identity] = _identity(before)
            stages[("active" if folder == "sessions" else "archived", relative)] = staged
            manifest_files.append({
                "collection": "active" if folder == "sessions" else "archived",
                "path": relative, "size": staged.size,
                "mtime_ns": before.st_mtime_ns, "sha256": staged.sha256,
                "chunks": list(staged.chunks), **signals.manifest_fields(),
            })
            total_bytes += staged.size
        current = _source_files(source_home)
        if {(folder, relative) for folder, _, relative in current} != set(source_facts):
            raise MigrationError("Codex conversations changed during hosted backup.")
        for folder, path, relative in current:
            if _identity(check_info(path.lstat())) != source_facts[(folder, relative)]:
                raise MigrationError("A conversation changed after hosted staging.")
            require_local(path)
        mark_simultaneous_conflicts(manifest_files)
        at_risk = set(loss_warnings(
            (item for item in previous_catalog
             if item.get("collection") in ("active", "archived")),
            manifest_files))
        for item in manifest_files:
            if item["identity_state"] == "needs_review":
                at_risk.add(item["collection"] + "/" + item["path"])
        for item in manifest_files:
            item["at_risk"] = (item.get("thread_id") in at_risk or
                               item["collection"] + "/" + item["path"] in at_risk)
        if has_paginated:
            from codex_migrate.vault_paginated import encoded_item, open_paginated_source
            with open_paginated_source(source_home) as paginated:
                thread_ids = paginated.thread_ids()
                if len(manifest_files) + len(thread_ids) > 100_000:
                    raise MigrationError("The hosted snapshot has too many history entries.")
                for thread_id in thread_ids:
                    counts = [0, 0, 0]

                    def records():
                        for item in paginated.items(thread_id):
                            counts[0] += 1
                            counts[1] += item.item_type == "userMessage"
                            counts[2] += item.item_type == "agentMessage"
                            yield encoded_item(item)

                    staged = stage_remote_aware_records(
                        records(), journal.key_id, client, journal.reservation_id,
                        journal, crypto_helper=crypto_helper,
                        chunk_size=chunk_size, window_bytes=window_bytes,
                        apply=True)
                    if not counts[0]:
                        raise MigrationError("Codex paginated history changed during hosted backup.")
                    relative = thread_id + ".jsonl"
                    stages[("paginated", relative)] = staged
                    manifest_files.append({
                        "collection": "paginated", "path": relative,
                        "size": staged.size, "mtime_ns": 0,
                        "sha256": staged.sha256, "chunks": list(staged.chunks),
                        "thread_id": thread_id, "identity_state": "verified",
                        "titles": list(titles.get(thread_id, [])),
                        "records": counts[0], "user_messages": counts[1],
                        "assistant_messages": counts[2], "at_risk": False,
                    })
                    total_bytes += staged.size
        paginated_risk = set(loss_warnings(
            (item for item in previous_catalog
             if item.get("collection") == "paginated"),
            (item for item in manifest_files
             if item["collection"] == "paginated")))
        for item in manifest_files:
            if item["collection"] == "paginated":
                item["at_risk"] = item["thread_id"] in paginated_risk
        at_risk.update(paginated_risk)
        # A long database read must not hide a concurrent transcript change.
        current = _source_files(source_home)
        if {(folder, relative) for folder, _, relative in current} != set(source_facts):
            raise MigrationError("Codex conversations changed during hosted backup.")
        for folder, path, relative in current:
            if _identity(check_info(path.lstat())) != source_facts[(folder, relative)]:
                raise MigrationError("A conversation changed after hosted staging.")
            require_local(path)
        manifest = {
            "format": "codex-vault-snapshot",
            "version": 3 if any(item["collection"] == "paginated"
                                for item in manifest_files) else 2,
            "snapshot_id": journal.snapshot_id, "created_at": created_at,
            "files": manifest_files,
        }
        objects = stage_hosted_snapshot_tail(
            metadata, manifest, stages, journal, client,
            crypto_helper=crypto_helper, apply=True)
        return HostedSnapshotStage(journal.snapshot_id, journal.reservation_id, objects,
                                   len(manifest_files), total_bytes, len(at_risk))
