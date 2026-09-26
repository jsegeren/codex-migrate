"""Private, bounded identity and loss signals for Codex rollout snapshots.

Titles and thread IDs are stored only inside the encrypted snapshot manifest.
No transcript body or title is written to a log or unencrypted index.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat
from typing import Dict, Iterable, List, Optional, Tuple
import uuid

from codex_migrate.errors import MigrationError


ROLLOUT_ID = re.compile(r"(?:rollout-)?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$", re.I)
MAX_INDEX_BYTES = 32 * 1024 * 1024
# Compaction records can exceed 32 MiB in ordinary active histories. Keep a
# finite cap, but do not reject verified customer history observed at 58 MiB.
MAX_RECORD_BYTES = 128 * 1024 * 1024
MAX_TITLES_PER_THREAD = 64


class TranscriptChanged(MigrationError):
    """A transcript moved while it was being inspected; a fresh read may work."""


def canonical_id(value: object) -> Optional[str]:
    if not isinstance(value, str):
        return None
    try:
        canonical = str(uuid.UUID(value)).lower()
    except (ValueError, AttributeError):
        return None
    return canonical if value.lower() == canonical else None


def filename_id(relative: str) -> Optional[str]:
    match = ROLLOUT_ID.search(Path(relative).name)
    return canonical_id(match.group(1)) if match else None


def peek_identity(path: Path, relative: str) -> Tuple[Optional[str], str]:
    """Read a bounded rollout header for additive restore collision checks."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise MigrationError("A conversation identity is not a regular file.")
            embedded_ids = set()
            for _ in range(16):
                raw = handle.readline(MAX_RECORD_BYTES + 1)
                if not raw:
                    break
                if len(raw) > MAX_RECORD_BYTES:
                    raise MigrationError("A conversation header is too large for safe identity inspection.")
                try:
                    record = json.loads(raw)
                except (UnicodeError, json.JSONDecodeError) as error:
                    raise MigrationError("A conversation header is unreadable.") from error
                if isinstance(record, dict) and record.get("type") == "session_meta":
                    payload = record.get("payload")
                    found = canonical_id(payload.get("id")) if isinstance(payload, dict) else None
                    if found:
                        embedded_ids.add(found)
            after = os.fstat(handle.fileno())
    except MigrationError:
        raise
    except OSError as error:
        raise MigrationError("A conversation identity could not be inspected safely.") from error
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
            before.st_ctime_ns) != (after.st_dev, after.st_ino, after.st_size,
            after.st_mtime_ns, after.st_ctime_ns):
        raise MigrationError("A conversation changed during identity inspection.")
    named = filename_id(relative)
    if len(embedded_ids) > 1:
        return None, "needs_review"
    embedded = next(iter(embedded_ids), None)
    if embedded and named and embedded != named:
        return None, "needs_review"
    return (embedded or named,
            "verified" if embedded and (not named or named == embedded) else "unverified")


def title_index(source_home: str) -> Dict[str, List[str]]:
    """Read only Codex's title index; never retain its other fields."""
    path = Path(source_home) / ".codex" / "session_index.jsonl"
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return {}
    except OSError as error:
        raise MigrationError("The Codex title index could not be read safely.") from error
    titles: Dict[str, List[str]] = defaultdict(list)
    try:
        with os.fdopen(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_INDEX_BYTES:
                raise MigrationError("The Codex title index needs review before backup.")
            for raw in handle:
                if len(raw) > MAX_RECORD_BYTES:
                    raise MigrationError("The Codex title index needs review before backup.")
                try:
                    record = json.loads(raw)
                except (UnicodeError, json.JSONDecodeError) as error:
                    raise MigrationError("The Codex title index is unreadable.") from error
                if not isinstance(record, dict):
                    continue
                thread_id = canonical_id(record.get("id"))
                title = record.get("thread_name")
                if (thread_id and isinstance(title, str) and title.strip()
                        and len(title) <= 500 and "\x00" not in title):
                    aliases = titles[thread_id]
                    if title not in aliases:
                        if len(aliases) == MAX_TITLES_PER_THREAD:
                            aliases.pop(0)
                        aliases.append(title)
    except MigrationError:
        raise
    except OSError as error:
        raise MigrationError("The Codex title index could not be read safely.") from error
    return dict(titles)


@dataclass(frozen=True)
class ThreadSignals:
    thread_id: Optional[str]
    identity_state: str
    titles: List[str]
    records: int
    assistant_messages: int
    user_messages: int

    def manifest_fields(self) -> Dict[str, object]:
        return {
            "thread_id": self.thread_id,
            "identity_state": self.identity_state,
            "titles": self.titles,
            "records": self.records,
            "assistant_messages": self.assistant_messages,
            "user_messages": self.user_messages,
        }


def scan_transcript(path: Path, relative: str, titles: Dict[str, List[str]]) -> ThreadSignals:
    """Stream only metadata/counts and refuse an inconsistent source read."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise MigrationError("A conversation changed before identity inspection.")
            embedded_ids = set()
            records = assistant = user = 0
            for raw in handle:
                if len(raw) > MAX_RECORD_BYTES:
                    raise MigrationError("A conversation record is too large for safe identity inspection.")
                try:
                    record = json.loads(raw)
                except (UnicodeError, json.JSONDecodeError) as error:
                    changed = os.fstat(handle.fileno())
                    if (before.st_dev, before.st_ino, before.st_size,
                            before.st_mtime_ns, before.st_ctime_ns) != (
                            changed.st_dev, changed.st_ino, changed.st_size,
                            changed.st_mtime_ns, changed.st_ctime_ns):
                        raise TranscriptChanged("A conversation changed during identity inspection.") from error
                    raise MigrationError("A conversation contains unreadable JSON; it was not backed up.") from error
                if not isinstance(record, dict):
                    continue
                records += 1
                payload = record.get("payload")
                if record.get("type") == "session_meta" and isinstance(payload, dict):
                    found = canonical_id(payload.get("id"))
                    if found:
                        embedded_ids.add(found)
                if record.get("type") == "response_item" and isinstance(payload, dict):
                    role = payload.get("role")
                    if role == "assistant":
                        assistant += 1
                    elif role == "user":
                        user += 1
            after = os.fstat(handle.fileno())
    except MigrationError:
        raise
    except OSError as error:
        raise MigrationError("A conversation could not be inspected safely.") from error
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
            before.st_ctime_ns) != (after.st_dev, after.st_ino, after.st_size,
            after.st_mtime_ns, after.st_ctime_ns):
        raise TranscriptChanged("A conversation changed during identity inspection.")
    named = filename_id(relative)
    if len(embedded_ids) > 1:
        return ThreadSignals(None, "needs_review", [], records, assistant, user)
    embedded = next(iter(embedded_ids), None)
    if embedded and named and embedded != named:
        return ThreadSignals(None, "needs_review", [], records, assistant, user)
    thread_id = embedded or named
    # A filename by itself is a discovery hint, not a verified identity.
    state = "verified" if embedded and (not named or named == embedded) else "unverified"
    return ThreadSignals(thread_id, state, list(titles.get(thread_id, [])), records, assistant, user)


def mark_simultaneous_conflicts(files: List[Dict[str, object]]) -> None:
    """Same ID in two different files of one capture is not a silent merge."""
    grouped: Dict[str, List[Dict[str, object]]] = defaultdict(list)
    for file in files:
        thread_id = file.get("thread_id")
        if file.get("identity_state") == "verified" and isinstance(thread_id, str):
            grouped[thread_id].append(file)
    for matches in grouped.values():
        if len(matches) > 1:
            for file in matches:
                file["identity_state"] = "needs_review"


def loss_warnings(previous: Iterable[Dict[str, object]], current: Iterable[Dict[str, object]]) -> List[str]:
    """Return opaque thread IDs only; never expose titles or content in logs."""
    old_by_id = {item.get("thread_id"): item for item in previous
                 if item.get("identity_state") == "verified" and item.get("thread_id")}
    new_by_id = {item.get("thread_id"): item for item in current
                 if item.get("identity_state") == "verified" and item.get("thread_id")}
    warnings = []
    for thread_id, old in old_by_id.items():
        new = new_by_id.get(thread_id)
        if not new:
            continue  # A missing file may have been archived or deliberately deleted.
        if old.get("at_risk") is True:
            warnings.append(str(thread_id))
            continue
        old_size, new_size = old.get("size"), new.get("size")
        old_assistant, new_assistant = old.get("assistant_messages"), new.get("assistant_messages")
        if (isinstance(old_size, int) and isinstance(new_size, int)
                and old_size >= 1024 * 1024 and new_size < old_size // 2):
            warnings.append(str(thread_id))
        elif (isinstance(old_assistant, int) and isinstance(new_assistant, int)
              and old_assistant >= 10 and new_assistant < old_assistant // 2):
            warnings.append(str(thread_id))
    return warnings
