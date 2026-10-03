"""Read-only diagnosis against a bound, authenticated hosted backup.

Never reserve, upload, publish, rebaseline, write into Codex, or print bodies,
titles, hashes, credentials, or recovery material. Samples contain only IDs and
relative source paths and are intentionally bounded. This is not an approval.
"""

import hashlib
import os
from pathlib import Path
import re
from typing import Optional

from codex_migrate.errors import MigrationError
from codex_migrate.source_availability import check_info, require_local
from codex_migrate.vault_attachments import pasted_references
from codex_migrate.vault_backup import _helper_path, _metadata, _source_files
from codex_migrate.vault_hosted_enrollment_client import HostedEnrollmentClient
from codex_migrate.vault_hosted_schedule import MAX_PRIOR_BYTES, SERVICE_ORIGIN, _UUID
from codex_migrate.vault_hosted_source_loss import (
    missing_unidentified_transcripts, missing_verified_threads,
)
from codex_migrate.vault_identity import (
    canonical_id, loss_warnings, mark_simultaneous_conflicts, scan_transcript,
)
from codex_migrate.vault_local_lock import local_history_lock
from codex_migrate.vault_paginated import (
    encoded_item, open_paginated_source, source_fingerprint,
)
from codex_migrate.vault_schedule import _home, _safe_json


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _files(source_home):
    files = _source_files(source_home)
    if len(files) > 100_000:
        raise MigrationError("Too many history entries for a bounded source review.")
    state = {}
    for folder, path, relative in files:
        require_local(path)
        identity = (folder, relative)
        if identity in state:
            raise MigrationError("Duplicate source paths require review.")
        state[identity] = _identity(check_info(path.lstat()))
    return files, state


def _validate_prior(rows, version):
    """Authenticated bytes still need schema validation before comparison/output.

    The native catalog command authenticates/decrypts but does not validate all
    manifest fields. Legacy v1 rows have no identity/count metadata; that absence
    is unverified, never upgraded to a verified ID. No prior row is mutated.
    """
    if not isinstance(rows, list) or len(rows) > 100_000:
        raise MigrationError("The prior source catalog is invalid.")
    if version is None:
        if rows:
            raise MigrationError("A first backup cannot have a prior source catalog.")
        return
    if type(version) is not int or version not in (1, 2, 3, 4):
        raise MigrationError("The prior source catalog version is invalid.")
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise MigrationError("The prior source catalog is invalid.")
        collection, path = row.get("collection"), row.get("path")
        if (collection not in ("active", "archived", "paginated", "attachments") or
                not isinstance(path, str) or not path or len(path) > 4096 or
                path.startswith("/") or "\\" in path or "\x00" in path or
                any(part in ("", ".", "..") for part in path.split("/")) or
                (collection != "attachments" and not path.endswith(".jsonl"))):
            raise MigrationError("The prior source catalog has an unsafe path.")
        if (collection, path) in seen:
            raise MigrationError("The prior source catalog has a duplicate path.")
        seen.add((collection, path))
        size, digest, thread_id = row.get("size"), row.get("sha256"), row.get("thread_id")
        state = row.get("identity_state")
        if state is None and version == 1:
            state = "unverified"
        if (type(size) is not int or not 0 <= size <= 2**63 - 1 or
                not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest) or
                thread_id is not None and canonical_id(thread_id) != thread_id or
                state not in ("verified", "unverified", "needs_review") or
                state == "verified" and thread_id is None):
            raise MigrationError("The prior source catalog has invalid identity metadata.")
        counts = [row.get(key) for key in ("records", "user_messages", "assistant_messages")]
        if (any(value is not None and (type(value) is not int or not 0 <= value <= 2**63 - 1)
                for value in counts) or
                (version >= 2 or state == "verified") and any(value is None for value in counts) or
                counts[0] is not None and any(value is not None and value > counts[0]
                                             for value in counts[1:])):
            raise MigrationError("The prior source catalog has invalid message counts.")
        titles = row.get("titles", [])
        if (not isinstance(titles, list) or len(titles) > 64 or
                any(not isinstance(title, str) or len(title) > 500 or "\x00" in title
                    for title in titles) or
                row.get("at_risk") is not None and type(row["at_risk"]) is not bool):
            raise MigrationError("The prior source catalog has invalid metadata.")
        if collection == "paginated" and (
                version < 3 or state != "verified" or path != thread_id + ".jsonl" or size == 0 or
                counts[0] == 0):
            raise MigrationError("The prior source catalog has an invalid paginated identity.")
        if collection == "attachments" and (
                version < 4 or state != "unverified" or thread_id is not None or
                titles or counts != [0, 0, 0]):
            raise MigrationError("The prior source catalog has an invalid attachment identity.")


def _inventory(source_home):
    """Validate bodies and exact-byte moves, in memory, without staging data."""
    with local_history_lock(source_home):
        files, before = _files(source_home)
        database_before = source_fingerprint(source_home)
        attachments = {relative for folder, _, relative in files if folder == "attachments"}
        rows, missing_attachments = [], set()
        for folder, path, relative in files:
            collection = ("active" if folder == "sessions" else
                          "archived" if folder == "archived_sessions" else "attachments")
            if collection == "attachments":
                fields = {"thread_id": None, "identity_state": "unverified",
                          "records": 0, "user_messages": 0, "assistant_messages": 0}
            else:
                signals = scan_transcript(path, relative, {})
                fields = signals.manifest_fields()
                missing_attachments.update(
                    ref + "/pasted-text.txt" for ref in signals.pasted_attachment_ids
                    if ref + "/pasted-text.txt" not in attachments)
            digest = hashlib.sha256()
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as stream:
                if _identity(check_info(os.fstat(stream.fileno()))) != before[(folder, relative)]:
                    raise MigrationError("A conversation changed during source review.")
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
                if _identity(check_info(os.fstat(stream.fileno()))) != before[(folder, relative)]:
                    raise MigrationError("A conversation changed during source review.")
            rows.append({"collection": collection, "path": relative,
                         "size": before[(folder, relative)][2],
                         "sha256": digest.hexdigest(), **fields})
        mark_simultaneous_conflicts(rows)
        if database_before is not None:
            with open_paginated_source(source_home) as paginated:
                for thread_id in paginated.thread_ids():
                    if len(rows) >= 100_000:
                        raise MigrationError("Too many history entries for a bounded source review.")
                    size, records, users, assistants = 0, 0, 0, 0
                    digest = hashlib.sha256()
                    for item in paginated.items(thread_id):
                        raw = encoded_item(item)
                        size += len(raw)
                        digest.update(raw)
                        records += 1
                        users += item.item_type == "userMessage"
                        assistants += item.item_type == "agentMessage"
                        missing_attachments.update(
                            ref + "/pasted-text.txt" for ref in pasted_references(item.item_json)
                            if ref + "/pasted-text.txt" not in attachments)
                    if not records:
                        raise MigrationError("Paginated history changed during source review.")
                    rows.append({"collection": "paginated", "path": thread_id + ".jsonl",
                                 "thread_id": thread_id, "identity_state": "verified",
                                 "size": size, "sha256": digest.hexdigest(), "records": records,
                                 "user_messages": users, "assistant_messages": assistants})
        _, after = _files(source_home)
        if before != after or database_before != source_fingerprint(source_home):
            raise MigrationError("Codex history changed during source review; retry after it settles.")
        return rows, sorted(missing_attachments)


def review_hosted_source(source_home: str, device_id: str, metadata_path: str, *,
                         crypto_helper: Optional[str] = None) -> dict:
    """Read the current source against one remote version, with no write authority.

    Even a no-loss result is point-in-time diagnosis, not proof of protection
    or permission to replace last-good. Background backup guards are unchanged.
    """
    if not isinstance(device_id, str) or not _UUID.fullmatch(device_id):
        raise MigrationError("The hosted backup device is invalid.")
    if not isinstance(metadata_path, str) or not Path(metadata_path).is_absolute():
        raise MigrationError("Select an absolute path to existing Vault metadata.")
    home = str(_home(source_home))
    metadata = _safe_json(Path(metadata_path))
    key_id = _metadata(metadata)
    if type(metadata["version"]) is not int or "recovery_mode" in metadata:
        raise MigrationError("This review requires an individual Vault key.")
    helper = _helper_path(crypto_helper)
    try:
        enrollment = HostedEnrollmentClient(SERVICE_ORIGIN)
        upload, recovery = enrollment.backup_clients(device_id, crypto_helper=str(helper))
        pointer = recovery._latest()
        account, worker, latest = pointer
        if account != upload._account_id or worker != upload._worker_origin:
            raise MigrationError("The hosted review authority changed.")
        snapshot_id = None if latest is None else latest["snapshotId"]
        observed, prior, version = recovery.prior_catalog(
            key_id=key_id, crypto_helper=str(helper), max_bytes=MAX_PRIOR_BYTES,
            expected_snapshot_id=snapshot_id, expected_account_id=account,
            include_version=True)
        if observed != snapshot_id:
            raise MigrationError("The hosted review version changed.")
        _validate_prior(prior, version)
        if (snapshot_id is None) != (version is None):
            raise MigrationError("The prior source catalog version is unbound.")
        current, missing_attachments = _inventory(home)
        if recovery._latest() != pointer:
            raise MigrationError("The hosted backup changed during source review.")
        missing_ids = missing_verified_threads(prior, current)
        missing_files = missing_unidentified_transcripts(prior, current)
        risks = set()
        for collections in (("active", "archived"), ("paginated",)):
            risks.update(loss_warnings(
                (row for row in prior if row.get("collection") in collections),
                (row for row in current if row.get("collection") in collections)))
        ambiguous = [row for row in current if row.get("identity_state") == "needs_review"]
        source_groups = {"transcripts": ("active", "archived"), "paginated": ("paginated",)}
        lost_sources = [name for name, collections in source_groups.items()
                        if any(row.get("collection") in collections for row in prior) and
                        not any(row.get("collection") in collections for row in current)]
    except Exception:
        # No transport, helper, source text, signed URL or bearer exceptions
        # cross this operator/UI boundary. An unreadable source is NOT empty.
        raise MigrationError(
            "Hosted source review could not be verified. No backup or Codex data "
            "was changed. Retry after history settles or contact joshua@segeren.com.") from None
    needs_review = bool(missing_ids or missing_files or risks or ambiguous or
                        missing_attachments or lost_sources)
    return {
        "status": ("no_prior_backup" if snapshot_id is None else
                   "needs_review" if needs_review else "no_loss_detected"),
        "base_snapshot_id": snapshot_id, "source_entries": len(current),
        "missing_verified_threads": len(missing_ids), "missing_thread_ids": missing_ids[:25],
        "missing_unidentified_transcripts": len(missing_files), "missing_files": missing_files[:25],
        "at_risk_threads": len(risks), "at_risk_thread_ids": sorted(risks)[:25],
        "ambiguous_entries": len(ambiguous),
        "missing_attachments": len(missing_attachments),
        "missing_attachment_paths": missing_attachments[:25], "missing_sources": lost_sources,
        "samples_limited_to": 25, "applied": False, "rebaseline_authorized": False,
        "automatic_protection_verified": False,
    }
