"""Dark whole-snapshot staging without a full local ciphertext Vault.

This freezes only transcript bytes and metadata long enough to stage a client-
checked object graph. It never publishes, schedules, or claims protection.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Dict, List, Sequence, Tuple

from codex_migrate.errors import MigrationError
from codex_migrate.vault_attachments import pasted_references
from codex_migrate.source_availability import check_info, require_local
from codex_migrate.vault_backup import (
    DEFAULT_CHUNK_SIZE, _canonical_macos_path, _metadata,
    _source_files,
)
from codex_migrate.vault_hosted_chunk_journal import HostedChunkJournal
from codex_migrate.vault_hosted_snapshot_tail import stage_hosted_snapshot_tail
from codex_migrate.vault_hosted_source_index import (
    published_source_facts, record_source_facts,
)
from codex_migrate.vault_paginated import source_fingerprint
from codex_migrate.vault_identity import (
    TranscriptChanged, loss_warnings, mark_simultaneous_conflicts,
    canonical_id, scan_transcript, title_index,
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


_HEX = re.compile(r"[0-9a-f]{64}\Z")


def _published_objects(client: RemoteAwareClient, ids: set[str]
                       ) -> Dict[str, StagedObject]:
    """Resolve reusable ciphertext from service authority, not a local hint."""
    found: Dict[str, StagedObject] = {}
    ordered = sorted(ids)
    for start in range(0, len(ordered), 256):
        page = ordered[start:start + 256]
        observed = client.published_chunks(page)
        if not isinstance(observed, dict) or set(observed) != set(page):
            raise MigrationError("A previously published Codex chunk is unavailable.")
        for identifier, facts in observed.items():
            if (not _HEX.fullmatch(identifier) or not isinstance(facts, tuple) or
                    len(facts) != 2 or type(facts[0]) is not int or
                    not 1 <= facts[0] <= 100_000_000 or
                    not isinstance(facts[1], str) or
                    not _HEX.fullmatch(facts[1])):
                raise MigrationError("The published Codex chunk facts are invalid.")
            key = "objects/" + identifier[:2] + "/" + identifier[2:] + ".cvchunk"
            found[identifier] = StagedObject(key, facts[0], facts[1])
    return found


def _valid_prior_chunks(previous: dict) -> bool:
    chunks = previous.get("chunks")
    return (isinstance(chunks, list) and
            all(isinstance(row, dict) and
                set(row) in ({"id", "size"}, {"id", "size", "encoding"}) and
                isinstance(row.get("id"), str) and
                _HEX.fullmatch(row["id"]) and
                type(row.get("size")) is int and 0 < row["size"] <= 64 * 1024 * 1024 and
                ("encoding" not in row or row["encoding"] == "lzfse")
                for row in chunks))


def _reusable_paginated(prior: Sequence[dict], count: int):
    """Use only complete, uniquely identified rows from the sealed manifest."""
    rows = [item for item in prior if item.get("collection") == "paginated"]
    if len(rows) != count:
        return None
    seen = set()
    for item in rows:
        thread_id = item.get("thread_id")
        if (not isinstance(thread_id, str) or
                canonical_id(thread_id) != thread_id or thread_id in seen or
                item.get("path") != thread_id + ".jsonl" or
                item.get("identity_state") != "verified" or
                type(item.get("size")) is not int or item["size"] <= 0 or
                item.get("mtime_ns") != 0 or
                not isinstance(item.get("sha256"), str) or
                not _HEX.fullmatch(item["sha256"]) or
                any(type(item.get(key)) is not int or item[key] < 0 for key in
                    ("records", "user_messages", "assistant_messages")) or
                item["records"] == 0 or
                item["user_messages"] > item["records"] or
                item["assistant_messages"] > item["records"] or
                not _valid_prior_chunks(item) or not item["chunks"] or
                sum(chunk["size"] for chunk in item["chunks"]) != item["size"]):
            return None
        seen.add(thread_id)
    return rows


def _reuse_candidates(files: list, prior: Sequence[dict],
                      fingerprints: dict) -> Dict[Tuple[str, str], dict]:
    """A stat match is useful only with an authenticated prior manifest row."""
    prior_by_path: Dict[Tuple[str, str], dict] = {}
    duplicates = set()
    for item in prior:
        identity = (item.get("collection"), item.get("path"))
        if identity in prior_by_path:
            duplicates.add(identity)
        prior_by_path[identity] = item
    reusable: Dict[Tuple[str, str], dict] = {}
    for folder, path, relative in files:
        identity = ("active" if folder == "sessions" else
                    "archived" if folder == "archived_sessions" else "attachments", relative)
        previous = prior_by_path.get(identity)
        if (identity in duplicates or not isinstance(previous, dict) or
                previous.get("identity_state") == "needs_review" or
                previous.get("identity_state") not in ("verified", "unverified") or
                type(previous.get("size")) is not int or
                not _valid_prior_chunks(previous) or
                type(previous.get("mtime_ns")) is not int or
                not isinstance(previous.get("sha256"), str) or
                not _HEX.fullmatch(previous["sha256"]) or
                type(previous.get("records")) is not int or
                type(previous.get("assistant_messages")) is not int or
                type(previous.get("user_messages")) is not int):
            continue
        info = check_info(path.lstat())
        if (fingerprints.get(identity) == _identity(info) and
                previous["size"] == info.st_size and
                previous["mtime_ns"] == info.st_mtime_ns):
            reusable[identity] = previous
    return reusable


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
        paginated_before = source_fingerprint(source_home)
        has_paginated = paginated_before is not None
        paginated_count = 0
        paginated_stable = True
        if has_paginated:
            # Fail before the first remote PUT when the separate history
            # database or one of SQLite's sidecars cannot be read safely.
            from codex_migrate.vault_paginated import source_footprint
            paginated_count, _, available = source_footprint(source_home)
            if not available:
                raise MigrationError("Codex paginated history changed before hosted staging.")
            paginated_stable = source_fingerprint(source_home) == paginated_before
        files = _source_files(source_home)
        if len(files) > 100_000:
            raise MigrationError("The hosted snapshot has too many transcripts.")
        attachment_paths = {relative for folder, _, relative in files
                            if folder == "attachments"}
        previous_attachment_paths = {item.get("path") for item in previous_catalog
                                     if item.get("collection") == "attachments"}
        missing_attachments = set()
        missing_paginated_attachments = set()
        titles = title_index(source_home)
        fingerprints, previous_paginated = published_source_facts(
            journal, crypto_helper=crypto_helper, include_paginated=True)
        reuse = _reuse_candidates(files, previous_catalog, fingerprints)
        if attachment_paths != previous_attachment_paths:
            # Re-read wrappers when an attachment appeared or vanished: an
            # unchanged rollout could now reference missing content.
            reuse = {}
        reusable_paginated = (
            _reusable_paginated(previous_catalog, paginated_count)
            if has_paginated and paginated_stable and
               attachment_paths == previous_attachment_paths and
               previous_paginated == paginated_before else None)
        prior_ids = {row.get("id") for item in reuse.values()
                     for row in item["chunks"] if isinstance(row, dict)}
        if reusable_paginated is not None:
            prior_ids.update(row.get("id") for item in reusable_paginated
                             for row in item["chunks"])
        if (None in prior_ids or any(not isinstance(identifier, str) or
                                     not _HEX.fullmatch(identifier)
                                     for identifier in prior_ids)):
            raise MigrationError("The prior hosted chunk map is invalid.")
        prior_objects = _published_objects(client, prior_ids)
        created_at = journal.snapshot_time()
        manifest_files: List[dict] = []
        stages: Dict[Tuple[str, str], StagedRemoteFile] = {}
        source_facts: Dict[Tuple[str, str], tuple[int, int, int, int, int]] = {}
        total_bytes = 0
        for folder, path, relative in files:
            before = check_info(path.lstat())
            identity = (folder, relative)
            collection = ("active" if folder == "sessions" else
                          "archived" if folder == "archived_sessions" else "attachments")
            previous = reuse.get((collection, relative))
            if previous is not None:
                ids = {row["id"] for row in previous["chunks"]}
                staged = StagedRemoteFile(
                    previous["sha256"], previous["size"],
                    tuple(previous["chunks"]),
                    tuple(prior_objects[identifier] for identifier in sorted(ids)))
                signals_fields = {
                    "thread_id": previous.get("thread_id"),
                    "identity_state": previous.get("identity_state"),
                    "titles": list(titles.get(previous.get("thread_id"), [])),
                    "records": previous.get("records"),
                    "assistant_messages": previous.get("assistant_messages"),
                    "user_messages": previous.get("user_messages"),
                }
            else:
                if collection == "attachments":
                    signals_fields = {
                        "thread_id": None, "identity_state": "unverified",
                        "titles": [], "records": 0,
                        "assistant_messages": 0, "user_messages": 0,
                    }
                else:
                    try:
                        signals = scan_transcript(path, relative, titles)
                    except TranscriptChanged:
                        raise MigrationError(
                            "A conversation changed during hosted backup; retry after it settles.") from None
                    signals_fields = signals.manifest_fields()
                    if any(attachment_id + "/pasted-text.txt" not in attachment_paths
                           for attachment_id in signals.pasted_attachment_ids):
                        missing_attachments.add(
                            signals.thread_id or collection + "/" + relative)
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
            stages[(collection, relative)] = staged
            manifest_files.append({
                "collection": collection,
                "path": relative, "size": staged.size,
                "mtime_ns": before.st_mtime_ns, "sha256": staged.sha256,
                "chunks": list(staged.chunks), **signals_fields,
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
        at_risk.update(missing_attachments)
        at_risk.update(
            item.get("thread_id") or item["collection"] + "/" + item["path"]
            for item in previous_catalog
            if item.get("collection") in ("active", "archived") and
               item.get("at_risk") is True)
        for item in manifest_files:
            if item["collection"] != "attachments" and item["identity_state"] == "needs_review":
                at_risk.add(item["collection"] + "/" + item["path"])
        for item in manifest_files:
            item["at_risk"] = (item["collection"] != "attachments" and
                               (item.get("thread_id") in at_risk or
                                item["collection"] + "/" + item["path"] in at_risk))
        if has_paginated:
            from codex_migrate.vault_paginated import encoded_item, open_paginated_source
            if reusable_paginated is not None:
                for previous in reusable_paginated:
                    thread_id = previous["thread_id"]
                    ids = {row["id"] for row in previous["chunks"]}
                    staged = StagedRemoteFile(
                        previous["sha256"], previous["size"],
                        tuple(previous["chunks"]),
                        tuple(prior_objects[identifier] for identifier in sorted(ids)))
                    relative = thread_id + ".jsonl"
                    stages[("paginated", relative)] = staged
                    manifest_files.append({
                        "collection": "paginated", "path": relative,
                        "size": staged.size, "mtime_ns": 0,
                        "sha256": staged.sha256, "chunks": list(staged.chunks),
                        "thread_id": thread_id, "identity_state": "verified",
                        "titles": list(titles.get(thread_id, [])),
                        "records": previous["records"],
                        "user_messages": previous["user_messages"],
                        "assistant_messages": previous["assistant_messages"],
                        "at_risk": False,
                    })
                    total_bytes += staged.size
            else:
                with open_paginated_source(source_home) as paginated:
                    thread_ids = paginated.thread_ids()
                    if len(manifest_files) + len(thread_ids) > 100_000:
                        raise MigrationError("The hosted snapshot has too many history entries.")
                    for thread_id in thread_ids:
                        counts = [0, 0, 0]

                        def records():
                            for item in paginated.items(thread_id):
                                if any(attachment_id + "/pasted-text.txt" not in attachment_paths
                                       for attachment_id in pasted_references(item.item_json)):
                                    missing_paginated_attachments.add(thread_id)
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
            paginated_after = source_fingerprint(source_home)
            if reusable_paginated is not None and paginated_after != paginated_before:
                raise MigrationError("Codex paginated history changed during hosted backup.")
            paginated_hint = (paginated_before if paginated_stable and
                              paginated_after == paginated_before else None)
        else:
            if source_fingerprint(source_home) is not None:
                raise MigrationError("Codex paginated history appeared during hosted backup.")
            paginated_hint = None
        paginated_risk = set(loss_warnings(
            (item for item in previous_catalog
             if item.get("collection") == "paginated"),
            (item for item in manifest_files
             if item["collection"] == "paginated")))
        if not has_paginated:
            # A vanished database is not evidence that its prior threads were
            # intentionally deleted. Preserve the prior version as the clean
            # recovery choice instead of certifying an empty replacement.
            paginated_risk.update(
                item["thread_id"] for item in previous_catalog
                if item.get("collection") == "paginated" and item.get("thread_id"))
        paginated_risk.update(missing_paginated_attachments)
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
            "version": (4 if any(item["collection"] == "attachments"
                                 for item in manifest_files) else
                        3 if any(item["collection"] == "paginated"
                                 for item in manifest_files) else 2),
            "snapshot_id": journal.snapshot_id, "created_at": created_at,
            "files": manifest_files,
        }
        objects = stage_hosted_snapshot_tail(
            metadata, manifest, stages, journal, client,
            crypto_helper=crypto_helper, apply=True)
        record_source_facts(journal, {
            ("active" if folder == "sessions" else
             "archived" if folder == "archived_sessions" else "attachments", relative): facts
            for (folder, relative), facts in source_facts.items()
        }, crypto_helper=crypto_helper, paginated=paginated_hint)
        return HostedSnapshotStage(journal.snapshot_id, journal.reservation_id, objects,
                                   len(manifest_files), total_bytes, len(at_risk))
