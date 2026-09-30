"""Private, bounded identity and loss signals for Codex rollout snapshots.

Titles and thread IDs are stored only inside the encrypted snapshot manifest.
No transcript body or title is written to a log or unencrypted index.
"""

from __future__ import annotations

from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
from typing import Dict, Iterable, List, Optional, Tuple
import uuid
from urllib.parse import quote

from codex_migrate.errors import MigrationError
from codex_migrate.source_availability import require_local
from codex_migrate.vault_attachments import pasted_references


ROLLOUT_ID = re.compile(r"(?:rollout-)?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$", re.I)
MAX_INDEX_BYTES = 32 * 1024 * 1024
# Compaction records can exceed 32 MiB in ordinary active histories. Keep a
# finite cap, but do not reject verified customer history observed at 58 MiB.
MAX_RECORD_BYTES = 128 * 1024 * 1024
MAX_TITLES_PER_THREAD = 64
MAX_STATE_THREADS = 100000


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


def _append_title(titles: Dict[str, List[str]], thread_id: object, title: object) -> None:
    identity = canonical_id(thread_id)
    if (not identity or not isinstance(title, str) or not title.strip()
            or len(title) > 500 or "\x00" in title):
        return
    aliases = titles[identity]
    if title not in aliases:
        if len(aliases) == MAX_TITLES_PER_THREAD:
            aliases.pop(0)
        aliases.append(title)


def _session_titles(source_home: str, titles: Dict[str, List[str]]) -> None:
    path = Path(source_home) / ".codex" / "session_index.jsonl"
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return
    except OSError as error:
        raise MigrationError("The Codex title index could not be read safely.") from error
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
                _append_title(titles, record.get("id"), record.get("thread_name"))
    except MigrationError:
        raise
    except OSError as error:
        raise MigrationError("The Codex title index could not be read safely.") from error


def _state_titles(source_home: str, titles: Dict[str, List[str]]) -> None:
    """Read only the known Codex state schema's titles in one pinned view."""
    if not Path(source_home).is_absolute():
        raise ValueError("source home must be absolute")
    path = Path(source_home) / ".codex/state_5.sqlite"
    if len(path.parts) > 1 and path.parts[1] in ("var", "tmp", "etc"):
        path = Path("/private") / Path(*path.parts[1:])
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            entry = current.lstat()
        except FileNotFoundError:
            if current == path:
                return  # Older Codex versions have no state database.
            raise MigrationError("The Codex state title source could not be opened safely.") from None
        except OSError as error:
            raise MigrationError("The Codex state title source could not be opened safely.") from error
        if stat.S_ISLNK(entry.st_mode) or (current != path and not stat.S_ISDIR(entry.st_mode)):
            raise MigrationError("The Codex state title source has an unsafe path.")
    try:
        require_local(path)
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(descriptor)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_nlink != 1
                    or not os.read(descriptor, 20).startswith(b"SQLite format 3\x00")):
                raise MigrationError("The Codex state title source is not a private SQLite file.")
        finally:
            os.close(descriptor)
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = Path(str(path) + suffix)
            try:
                side = sidecar.lstat()
            except FileNotFoundError:
                continue
            require_local(sidecar)
            if (not stat.S_ISREG(side.st_mode) or side.st_uid != os.getuid()
                    or side.st_nlink != 1):
                raise MigrationError("The Codex state title source has an unsafe sidecar.")
        uri = "file:" + quote(str(path), safe="/") + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, isolation_level=None,
                                     timeout=2)) as connection:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            table = connection.execute(
                "SELECT type FROM sqlite_master WHERE name='threads'").fetchone()
            columns = {row[1] for row in connection.execute("PRAGMA table_info(threads)")}
            if table != ("table",) or not {"id", "title", "name"} <= columns:
                raise MigrationError("The Codex state title source has an unsupported schema.")
            opened = path.lstat()
            if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                raise MigrationError("The Codex state title source moved while opening it.")
            # Codex may put an entire first prompt in `title`. Read only a
            # bounded prefix, never a multi-megabyte prompt into title metadata.
            for count, (thread_id, title, name) in enumerate(connection.execute(
                    "SELECT id, substr(title, 1, 500), substr(name, 1, 500) "
                    "FROM threads"), start=1):
                if count > MAX_STATE_THREADS:
                    raise MigrationError("The Codex state title source has too many threads.")
                _append_title(titles, thread_id, title)
                _append_title(titles, thread_id, name)
            after = path.lstat()
            if (after.st_dev, after.st_ino) != (info.st_dev, info.st_ino):
                raise MigrationError("The Codex state title source moved while reading it.")
    except MigrationError:
        raise
    except (OSError, sqlite3.Error) as error:
        raise MigrationError("The Codex state title source could not be read safely.") from error


def title_index(source_home: str) -> Dict[str, List[str]]:
    """Combine old and current titles without reading conversation bodies."""
    titles: Dict[str, List[str]] = defaultdict(list)
    _session_titles(source_home, titles)
    _state_titles(source_home, titles)
    return dict(titles)


@dataclass(frozen=True)
class ThreadSignals:
    thread_id: Optional[str]
    identity_state: str
    titles: List[str]
    records: int
    assistant_messages: int
    user_messages: int
    pasted_attachment_ids: Tuple[str, ...] = ()

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
            pasted_attachment_ids = set()
            records = assistant = user = 0
            for raw in handle:
                if len(raw) > MAX_RECORD_BYTES:
                    raise MigrationError("A conversation record is too large for safe identity inspection.")
                try:
                    record = json.loads(raw)
                    if not isinstance(record, dict):
                        raise ValueError("Conversation records must be JSON objects")
                except (UnicodeError, ValueError) as error:
                    changed = os.fstat(handle.fileno())
                    if (before.st_dev, before.st_ino, before.st_size,
                            before.st_mtime_ns, before.st_ctime_ns) != (
                            changed.st_dev, changed.st_ino, changed.st_size,
                            changed.st_mtime_ns, changed.st_ctime_ns):
                        raise TranscriptChanged("A conversation changed during identity inspection.") from error
                    raise MigrationError("A conversation contains unreadable JSON; it was not backed up.") from error
                records += 1
                payload = record.get("payload")
                stack = [payload]
                while stack:
                    value = stack.pop()
                    if isinstance(value, str):
                        pasted_attachment_ids.update(pasted_references(value))
                    elif isinstance(value, dict):
                        stack.extend(value.values())
                    elif isinstance(value, list):
                        stack.extend(value)
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
        return ThreadSignals(None, "needs_review", [], records, assistant, user,
                             tuple(sorted(pasted_attachment_ids)))
    embedded = next(iter(embedded_ids), None)
    if embedded and named and embedded != named:
        return ThreadSignals(None, "needs_review", [], records, assistant, user,
                             tuple(sorted(pasted_attachment_ids)))
    thread_id = embedded or named
    # A filename by itself is a discovery hint, not a verified identity.
    state = "verified" if embedded and (not named or named == embedded) else "unverified"
    return ThreadSignals(thread_id, state, list(titles.get(thread_id, [])), records,
                         assistant, user, tuple(sorted(pasted_attachment_ids)))


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
        old_user, new_user = old.get("user_messages"), new.get("user_messages")
        if (isinstance(old_size, int) and isinstance(new_size, int)
                and old_size >= 1024 * 1024 and new_size < old_size // 2):
            warnings.append(str(thread_id))
        elif (isinstance(old_assistant, int) and isinstance(new_assistant, int)
              and new_assistant < old_assistant):
            warnings.append(str(thread_id))
        elif (isinstance(old_user, int) and isinstance(new_user, int)
              and new_user < old_user):
            warnings.append(str(thread_id))
    return warnings
