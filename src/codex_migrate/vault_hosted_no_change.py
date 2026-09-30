"""Read-only proof that a scheduled hosted check needs no new snapshot.

A local fingerprint is never backup authority by itself: bind it to the live
service pointer and compare the sealed prior manifest to the supported source
inventory. Uncertainty returns None so the normal full staging path runs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from codex_migrate.errors import MigrationError
from codex_migrate.source_availability import check_info, require_local
from codex_migrate.vault_backup import _source_files
from codex_migrate.vault_hosted_recovery_client import HostedRecoveryClient
from codex_migrate.vault_hosted_source_index import published_source_index
from codex_migrate.vault_identity import title_index
from codex_migrate.vault_local_lock import local_history_lock
from codex_migrate.vault_paginated import open_paginated_source, source_fingerprint


def _transcript_state(source_home: str):
    files = _source_files(source_home)
    if len(files) > 100_000:
        raise MigrationError("The hosted snapshot has too many transcripts.")
    state = {}
    for folder, path, relative in files:
        info = check_info(path.lstat())
        require_local(path)
        key = ("active" if folder == "sessions" else
               "archived" if folder == "archived_sessions" else "attachments", relative)
        if key in state:
            raise MigrationError("Codex history has a duplicate source path.")
        state[key] = (info.st_dev, info.st_ino, info.st_size,
                      info.st_mtime_ns, info.st_ctime_ns)
    return state


def unchanged_published_history(
    source_home: str, directory: Path, recovery: HostedRecoveryClient, *,
    account_id: str, vault_id: str, key_id: str, crypto_helper: str,
    max_prior_bytes: int,
) -> Optional[dict]:
    """Return last-good identity only when nothing supported has changed.

    This is a check, not a new verified backup or a server-side renewal. A
    changed source, missing hint, old hint, or changed service pointer enters
    the normal reservation/stage/verify/publish path instead.
    """
    latest = recovery.latest_snapshot(expected_account_id=account_id)
    if latest is None:
        return None
    snapshot_id = latest["snapshotId"]
    hint = published_source_index(
        directory, account_id=account_id, vault_id=vault_id, key_id=key_id,
        snapshot_id=snapshot_id, crypto_helper=crypto_helper)
    if hint is None:
        return None
    prior_files, prior_paginated = hint
    with local_history_lock(source_home):
        before = _transcript_state(source_home)
        before_db = source_fingerprint(source_home)
        if before != prior_files or before_db != prior_paginated:
            return None
        # Only after the cheap fingerprint match, read the sealed prior
        # manifest and enumerate SQLite thread IDs. This avoids the expensive
        # remote object inventory and all history-body reads on a quiet run.
        observed, catalog = recovery.prior_catalog(
            key_id=key_id, crypto_helper=crypto_helper,
            max_bytes=max_prior_bytes, expected_snapshot_id=snapshot_id,
            expected_account_id=account_id)
        if observed != snapshot_id:
            raise MigrationError("The hosted backup changed during its source check.")
        transcript_rows = {}
        paginated_ids = set()
        for item in catalog:
            collection, path = item.get("collection"), item.get("path")
            if collection in ("active", "archived", "attachments"):
                identity = (collection, path)
                if identity in transcript_rows:
                    return None
                transcript_rows[identity] = item
            elif collection == "paginated":
                thread_id = item.get("thread_id")
                if (not isinstance(thread_id, str) or path != thread_id + ".jsonl" or
                        thread_id in paginated_ids):
                    return None
                paginated_ids.add(thread_id)
            else:
                return None
        if set(transcript_rows) != set(before):
            return None
        if before_db is None:
            if paginated_ids:
                return None
        else:
            with open_paginated_source(source_home) as paginated:
                if set(paginated.thread_ids()) != paginated_ids:
                    return None
        titles = title_index(source_home)
        for identity, item in transcript_rows.items():
            if (item.get("size") != before[identity][2] or
                    (identity[0] != "attachments" and
                     item.get("titles") != list(titles.get(item.get("thread_id"), [])))):
                return None
        for item in catalog:
            if item.get("collection") == "paginated" and item.get("titles") != list(
                    titles.get(item["thread_id"], [])):
                return None
        if (_transcript_state(source_home) != before or
                source_fingerprint(source_home) != before_db or
                title_index(source_home) != titles):
            return None
        if recovery.latest_snapshot(expected_account_id=account_id) != latest:
            return None
        # An unchanged source does not make an at-risk published version safe.
        # Legacy/ambiguous catalog rows without an explicit false flag also
        # cannot be promoted to a clean scheduled check.
        at_risk = {
            (item["collection"], item.get("thread_id") or item["path"])
            for item in catalog
            if item["collection"] != "attachments" and item.get("at_risk") is not False
        }
        return {"unchanged": True, "lastGoodSnapshotId": snapshot_id,
                "lastGoodObjectCount": latest["totalObjects"],
                "sourceCoverage": latest.get("sourceCoverage", "unknown"),
                "atRiskThreads": len(at_risk)}
