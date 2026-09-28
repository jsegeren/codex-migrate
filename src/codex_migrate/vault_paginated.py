"""Read-only adapter for the known Codex paginated-history SQLite schema.

This is a source adapter, not a Vault backup. Callers must encrypt and verify
every emitted item before claiming paginated-history coverage. The schema is
private to Codex and must be checked again for each installed version.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sqlite3
import stat
from typing import Iterator, List
from urllib.parse import quote

from codex_migrate.errors import MigrationError
from codex_migrate.source_availability import require_local
from codex_migrate.vault_backup import _canonical_macos_path, _require_unlinked_path
from codex_migrate.vault_identity import MAX_RECORD_BYTES, canonical_id


REQUIRED_ITEMS = frozenset((
    "thread_id", "turn_id", "item_id", "rollout_ordinal", "created_at_ms",
    "item_json", "item_type", "updated_at_ordinal",
))
REQUIRED_PROJECTION = frozenset((
    "thread_id", "next_rollout_byte_offset", "next_rollout_ordinal",
))


@dataclass(frozen=True)
class PaginatedItem:
    thread_id: str
    turn_id: str
    item_id: str
    rollout_ordinal: int
    created_at_ms: int
    item_type: str
    item_json: str


class PaginatedSource:
    """A stable SQLite read transaction; never writes to Codex's database."""

    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection

    def thread_ids(self) -> List[str]:
        try:
            rows = self._connection.execute(
                "SELECT DISTINCT thread_id FROM thread_items ORDER BY thread_id")
            result = []
            for (thread_id,) in rows:
                if canonical_id(thread_id) != thread_id:
                    raise MigrationError("Codex paginated history has an invalid thread identity.")
                result.append(thread_id)
                if len(result) > 100000:
                    raise MigrationError("Codex paginated history has too many threads to capture safely.")
            return result
        except sqlite3.Error as error:
            raise MigrationError("Codex paginated history could not be listed safely.") from error

    def thread_ids_recent(self) -> List[str]:
        """List active database threads by newest persisted item, not UUID."""
        try:
            rows = self._connection.execute(
                "SELECT thread_id FROM thread_items GROUP BY thread_id "
                "ORDER BY MAX(created_at_ms) DESC, thread_id")
            result = []
            for (thread_id,) in rows:
                if canonical_id(thread_id) != thread_id:
                    raise MigrationError("Codex paginated history has an invalid thread identity.")
                result.append(thread_id)
                if len(result) > 100000:
                    raise MigrationError("Codex paginated history has too many threads to search safely.")
            return result
        except sqlite3.Error as error:
            raise MigrationError("Codex paginated history could not be listed safely.") from error

    def has_thread(self, thread_id: str) -> bool:
        if canonical_id(thread_id) != thread_id:
            raise ValueError("thread id must be a canonical UUID")
        try:
            return self._connection.execute(
                "SELECT 1 FROM thread_items WHERE thread_id=? LIMIT 1",
                (thread_id,)).fetchone() is not None
        except sqlite3.Error as error:
            raise MigrationError("Codex paginated history could not be inspected safely.") from error

    def items(self, thread_id: str) -> Iterator[PaginatedItem]:
        if canonical_id(thread_id) != thread_id:
            raise ValueError("thread id must be a canonical UUID")
        try:
            rows = self._connection.execute(
                "SELECT thread_id, turn_id, item_id, rollout_ordinal, "
                "created_at_ms, item_type, item_json FROM thread_items "
                "WHERE thread_id=? ORDER BY rollout_ordinal", (thread_id,))
            previous_ordinal = -1
            for source_id, turn_id, item_id, ordinal, created_at, item_type, raw in rows:
                if (source_id != thread_id or not isinstance(turn_id, str) or not turn_id
                        or not isinstance(item_id, str) or not item_id
                        or type(ordinal) is not int or ordinal <= previous_ordinal
                        or type(created_at) is not int or created_at < 0
                        or not isinstance(item_type, str) or not item_type
                        or not isinstance(raw, str)
                        or len(raw.encode("utf-8")) > MAX_RECORD_BYTES):
                    raise MigrationError("Codex paginated history has invalid item metadata.")
                try:
                    item = json.loads(raw)
                except (UnicodeError, json.JSONDecodeError) as error:
                    raise MigrationError("Codex paginated history has unreadable item JSON.") from error
                if (not isinstance(item, dict) or item.get("id") != item_id
                        or item.get("type") != item_type):
                    raise MigrationError("Codex paginated history item identity needs review.")
                previous_ordinal = ordinal
                yield PaginatedItem(thread_id, turn_id, item_id, ordinal,
                                    created_at, item_type, raw)
        except sqlite3.Error as error:
            raise MigrationError("Codex paginated history could not be read safely.") from error


def encoded_item(item: PaginatedItem) -> bytes:
    """One self-contained, provenance-labelled record; never a synthetic rollout."""
    return (json.dumps({
        "source": "codex-paginated-thread-items-v1",
        "thread_id": item.thread_id,
        "turn_id": item.turn_id,
        "item_id": item.item_id,
        "rollout_ordinal": item.rollout_ordinal,
        "created_at_ms": item.created_at_ms,
        "item_type": item.item_type,
        "item_json": item.item_json,
    }, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def restored_path(source_home: str, thread_id: str) -> Path:
    if not Path(source_home).is_absolute():
        raise ValueError("restored source home must be absolute")
    if canonical_id(thread_id) != thread_id:
        raise ValueError("thread id must be a canonical UUID")
    path = _canonical_macos_path(Path(source_home) / ".codex/paginated_history" /
                                 (thread_id + ".jsonl"))
    _require_unlinked_path(path)
    require_local(path)
    try:
        info = path.lstat()
    except OSError as error:
        raise MigrationError("The recovered paginated thread could not be inspected safely.") from error
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_nlink != 1):
        raise MigrationError("The recovered paginated thread is not a private regular file.")
    return path


def restored_items(source_home: str, thread_id: str) -> Iterator[PaginatedItem]:
    """Read a separately restored, authenticated v3 source without Codex writes."""
    path = restored_path(source_home, thread_id)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as error:
        raise MigrationError("The recovered paginated thread could not be opened safely.") from error
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1):
            raise MigrationError("The recovered paginated thread is not a private regular file.")
        previous_ordinal = -1
        while True:
            line = stream.readline(MAX_RECORD_BYTES * 2 + 4096)
            if not line:
                break
            if len(line) > MAX_RECORD_BYTES * 2 or not line.endswith(b"\n"):
                raise MigrationError("The recovered paginated thread has an invalid record length.")
            try:
                record = json.loads(line)
            except (UnicodeError, json.JSONDecodeError) as error:
                raise MigrationError("The recovered paginated thread has unreadable JSON.") from error
            if (not isinstance(record, dict) or set(record) != {
                    "source", "thread_id", "turn_id", "item_id", "rollout_ordinal",
                    "created_at_ms", "item_type", "item_json"}
                    or record["source"] != "codex-paginated-thread-items-v1"
                    or record["thread_id"] != thread_id
                    or not isinstance(record["turn_id"], str) or not record["turn_id"]
                    or not isinstance(record["item_id"], str) or not record["item_id"]
                    or type(record["rollout_ordinal"]) is not int
                    or record["rollout_ordinal"] <= previous_ordinal
                    or type(record["created_at_ms"]) is not int
                    or record["created_at_ms"] < 0
                    or not isinstance(record["item_type"], str) or not record["item_type"]
                    or not isinstance(record["item_json"], str)
                    or len(record["item_json"].encode("utf-8")) > MAX_RECORD_BYTES):
                raise MigrationError("The recovered paginated thread has invalid item metadata.")
            try:
                item = json.loads(record["item_json"])
            except (UnicodeError, json.JSONDecodeError) as error:
                raise MigrationError("The recovered paginated thread has unreadable item JSON.") from error
            if (not isinstance(item, dict) or item.get("id") != record["item_id"]
                    or item.get("type") != record["item_type"]):
                raise MigrationError("The recovered paginated item identity needs review.")
            previous_ordinal = record["rollout_ordinal"]
            yield PaginatedItem(thread_id, record["turn_id"], record["item_id"],
                                record["rollout_ordinal"], record["created_at_ms"],
                                record["item_type"], record["item_json"])


def _check_schema(connection: sqlite3.Connection) -> None:
    for table, required in (("thread_items", REQUIRED_ITEMS),
                            ("thread_history_projection_state", REQUIRED_PROJECTION)):
        row = connection.execute(
            "SELECT type FROM sqlite_master WHERE name=?", (table,)).fetchone()
        if row != ("table",):
            raise MigrationError("Codex paginated history has an unsupported schema.")
        columns = {entry[1] for entry in connection.execute("PRAGMA table_info(" + table + ")")}
        if not required <= columns:
            raise MigrationError("Codex paginated history has an unsupported schema.")


@contextmanager
def open_paginated_source(source_home: str) -> Iterator[PaginatedSource]:
    """Pin a read view of the known schema, or fail without modifying source data."""
    if not Path(source_home).is_absolute():
        raise ValueError("source home must be absolute")
    database = _canonical_macos_path(Path(source_home) / ".codex/thread_history_1.sqlite")
    try:
        _require_unlinked_path(database)
        require_local(database)
        descriptor = os.open(database, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except (OSError, MigrationError) as error:
        raise MigrationError("Codex paginated history could not be opened safely.") from error
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1):
            raise MigrationError("Codex paginated history is not a private regular file.")
        header = os.read(descriptor, 20)
        if not header.startswith(b"SQLite format 3\x00"):
            raise MigrationError("Codex paginated history is not a supported SQLite file.")
    finally:
        os.close(descriptor)
    uri = "file:" + quote(str(database), safe="/") + "?mode=ro"
    connection = None
    try:
        # The bounded pipe producer uses this pinned read transaction on one
        # worker thread while the main thread waits for the crypto helper.
        connection = sqlite3.connect(uri, uri=True, isolation_level=None,
                                     timeout=2, check_same_thread=False)
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        _check_schema(connection)
    except sqlite3.Error as error:
        if connection is not None:
            connection.close()
        raise MigrationError("Codex paginated history could not be read safely.") from error
    except BaseException:
        if connection is not None:
            connection.close()
        raise
    try:
        try:
            opened = database.lstat()
        except OSError as error:
            raise MigrationError("Codex paginated history moved while opening it.") from error
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            raise MigrationError("Codex paginated history moved while opening it.")
        yield PaginatedSource(connection)
        try:
            after = database.lstat()
        except OSError as error:
            raise MigrationError("Codex paginated history moved while reading it.") from error
        if (after.st_dev, after.st_ino) != (info.st_dev, info.st_ino):
            raise MigrationError("Codex paginated history moved while reading it.")
    finally:
        connection.close()
