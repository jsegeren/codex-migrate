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
import subprocess
import sys
from typing import Iterator, List, Optional
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
        yield from self.items_range(thread_id, 0, None)

    def items_range(self, thread_id: str, start_ordinal: int,
                    end_ordinal: Optional[int]) -> Iterator[PaginatedItem]:
        if canonical_id(thread_id) != thread_id:
            raise ValueError("thread id must be a canonical UUID")
        if (type(start_ordinal) is not int or start_ordinal < 0
                or (end_ordinal is not None and
                    (type(end_ordinal) is not int or end_ordinal < start_ordinal))):
            raise ValueError("invalid paginated history ordinal range")
        try:
            rows = self._connection.execute(
                "SELECT thread_id, turn_id, item_id, rollout_ordinal, "
                "created_at_ms, item_type, item_json FROM thread_items "
                "WHERE thread_id=? AND rollout_ordinal>=? "
                "AND (? IS NULL OR rollout_ordinal<?) ORDER BY rollout_ordinal",
                (thread_id, start_ordinal, end_ordinal, end_ordinal))
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


def restored_items(source_home: str, thread_id: str,
                   start_ordinal: int = 0,
                   end_ordinal: Optional[int] = None) -> Iterator[PaginatedItem]:
    """Read a separately restored, authenticated v3 source without Codex writes."""
    if (type(start_ordinal) is not int or start_ordinal < 0
            or (end_ordinal is not None and
                (type(end_ordinal) is not int or end_ordinal < start_ordinal))):
        raise ValueError("invalid paginated history ordinal range")
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
            if previous_ordinal < start_ordinal:
                continue
            if end_ordinal is not None and previous_ordinal >= end_ordinal:
                break
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


def _safe_sidecar_size(database: Path, suffix: str) -> int:
    """Reject linked or foreign SQLite sidecars before SQLite opens their paths."""
    sidecar = Path(str(database) + suffix)
    _require_unlinked_path(sidecar, allow_missing_leaf=True)
    try:
        info = sidecar.lstat()
    except FileNotFoundError:
        return 0
    except OSError as error:
        raise MigrationError("Codex paginated history sidecar could not be inspected safely.") from error
    require_local(sidecar)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_nlink != 1):
        raise MigrationError("Codex paginated history sidecar is not a private regular file.")
    return info.st_size


@contextmanager
def _open_paginated_source_direct(source_home: str) -> Iterator[PaginatedSource]:
    """Open SQLite only inside the write-denied reader subprocess."""
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
    for suffix in ("-wal", "-shm", "-journal"):
        _safe_sidecar_size(database, suffix)
    wal = Path(str(database) + "-wal")
    # A checkpointed database with no WAL can be read immutably without
    # creating SQLite sidecars. Never use immutable mode when a WAL exists:
    # it silently omits uncheckpointed conversation items.
    immutable = not wal.exists()
    uri = ("file:" + quote(str(database), safe="/") +
           ("?mode=ro&immutable=1" if immutable else "?mode=ro"))
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
        if immutable and ((after.st_size, after.st_mtime_ns, after.st_ctime_ns) !=
                          (info.st_size, info.st_mtime_ns, info.st_ctime_ns)
                          or wal.exists()):
            raise MigrationError("Codex paginated history changed while reading it.")
    finally:
        connection.close()


_READER_FLAG = "--vault-paginated-reader"
_MAX_PROTOCOL_LINE = MAX_RECORD_BYTES * 2 + 4096


def _sandbox_profile(codex: Path) -> str:
    # sandbox-exec resolves /var and /tmp through /private before matching.
    # Its Scheme parser does not interpret JSON's \uXXXX path escapes, so
    # preserve Unicode path characters while escaping quotes and controls.
    return ("(version 1)(allow default)(deny file-write* (subpath " +
            json.dumps(str(codex), ensure_ascii=False) + "))")


def _send_protocol(stream, value: dict) -> None:
    stream.write((json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
    stream.flush()


def _reader_main(source_home: str) -> int:
    """Serve one pinned read transaction from a process unable to write .codex."""
    try:
        with _open_paginated_source_direct(source_home) as source:
            _send_protocol(sys.stdout.buffer, {"ready": True})
            items = None
            for line in sys.stdin.buffer:
                if len(line) > 4096:
                    raise MigrationError("Invalid paginated reader request.")
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise MigrationError("Invalid paginated reader request.")
                operation = request.get("op")
                if operation == "thread_ids":
                    for thread_id in source.thread_ids():
                        _send_protocol(sys.stdout.buffer, {"id": thread_id})
                elif operation == "thread_ids_recent":
                    for thread_id in source.thread_ids_recent():
                        _send_protocol(sys.stdout.buffer, {"id": thread_id})
                elif operation == "has_thread":
                    _send_protocol(sys.stdout.buffer, {"has": source.has_thread(request.get("thread_id"))})
                elif operation == "items_range":
                    items = iter(source.items_range(request.get("thread_id"),
                                                    request.get("start", 0), request.get("end")))
                    _send_protocol(sys.stdout.buffer, {"range_ready": True})
                elif operation == "next_items":
                    if items is None:
                        raise MigrationError("Invalid paginated reader request.")
                    batch_bytes = 0
                    for _ in range(64):
                        try:
                            item = next(items)
                        except StopIteration:
                            items = None
                            _send_protocol(sys.stdout.buffer, {"done": True})
                            break
                        _send_protocol(sys.stdout.buffer, {"item": [
                            item.thread_id, item.turn_id, item.item_id,
                            item.rollout_ordinal, item.created_at_ms,
                            item.item_type, item.item_json,
                        ]})
                        batch_bytes += len(item.item_json)
                        if batch_bytes >= 256 * 1024:
                            break
                elif operation == "cancel_items":
                    items = None
                else:
                    raise MigrationError("Invalid paginated reader request.")
                _send_protocol(sys.stdout.buffer, {"end": True})
    except (MigrationError, ValueError, TypeError, sqlite3.Error, json.JSONDecodeError):
        _send_protocol(sys.stdout.buffer, {"error": "Codex paginated history could not be read safely."})
        return 1
    return 0


class _SandboxedPaginatedSource:
    def __init__(self, process: subprocess.Popen):
        self._process = process
        self._range_active = False

    def _request(self, request: dict) -> Iterator[dict]:
        try:
            _send_protocol(self._process.stdin, request)
            while True:
                line = self._process.stdout.readline(_MAX_PROTOCOL_LINE)
                if not line or len(line) >= _MAX_PROTOCOL_LINE:
                    raise MigrationError("The protected paginated reader stopped unexpectedly.")
                response = json.loads(line)
                if not isinstance(response, dict) or "error" in response:
                    raise MigrationError("Codex paginated history could not be read safely.")
                if response == {"end": True}:
                    return
                yield response
        except (BrokenPipeError, OSError, UnicodeError, json.JSONDecodeError) as error:
            raise MigrationError("The protected paginated reader stopped unexpectedly.") from error

    def thread_ids(self) -> List[str]:
        self._cancel_range()
        return [response["id"] for response in self._request({"op": "thread_ids"})]

    def thread_ids_recent(self) -> List[str]:
        self._cancel_range()
        return [response["id"] for response in self._request({"op": "thread_ids_recent"})]

    def has_thread(self, thread_id: str) -> bool:
        self._cancel_range()
        if canonical_id(thread_id) != thread_id:
            raise ValueError("thread id must be a canonical UUID")
        values = list(self._request({"op": "has_thread", "thread_id": thread_id}))
        if len(values) != 1 or type(values[0].get("has")) is not bool:
            raise MigrationError("The protected paginated reader returned invalid metadata.")
        return values[0]["has"]

    def items(self, thread_id: str) -> Iterator[PaginatedItem]:
        yield from self.items_range(thread_id, 0, None)

    def items_range(self, thread_id: str, start_ordinal: int,
                    end_ordinal: Optional[int]) -> Iterator[PaginatedItem]:
        self._cancel_range()
        if canonical_id(thread_id) != thread_id:
            raise ValueError("thread id must be a canonical UUID")
        if (type(start_ordinal) is not int or start_ordinal < 0
                or (end_ordinal is not None and
                    (type(end_ordinal) is not int or end_ordinal < start_ordinal))):
            raise ValueError("invalid paginated history ordinal range")
        ready = list(self._request({"op": "items_range", "thread_id": thread_id,
                                    "start": start_ordinal, "end": end_ordinal}))
        if ready != [{"range_ready": True}]:
            raise MigrationError("The protected paginated reader returned invalid metadata.")
        self._range_active = True
        while self._range_active:
            batch = list(self._request({"op": "next_items"}))
            for response in batch:
                if response == {"done": True}:
                    self._range_active = False
                    continue
                fields = response.get("item")
                if not isinstance(fields, list) or len(fields) != 7:
                    raise MigrationError("The protected paginated reader returned invalid content.")
                yield PaginatedItem(*fields)

    def _cancel_range(self) -> None:
        if self._range_active:
            if list(self._request({"op": "cancel_items"})):
                raise MigrationError("The protected paginated reader returned invalid metadata.")
            self._range_active = False

    def close(self) -> None:
        if self._process.stdin is not None:
            self._process.stdin.close()
        try:
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=5)
        if self._process.stdout is not None:
            self._process.stdout.close()


@contextmanager
def open_paginated_source(source_home: str) -> Iterator[_SandboxedPaginatedSource]:
    """Pin a complete SQLite view in a process denied writes to Codex state."""
    if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file():
        raise MigrationError("Protected Codex history reading requires macOS sandbox support.")
    if not Path(source_home).is_absolute():
        raise ValueError("source home must be absolute")
    codex = _canonical_macos_path(Path(source_home) / ".codex")
    _require_unlinked_path(codex)
    profile = _sandbox_profile(codex)
    command = ([sys.executable, _READER_FLAG, source_home]
               if getattr(sys, "frozen", False) else
               [sys.executable, "-B", "-m", "codex_migrate.vault_paginated",
                _READER_FLAG, source_home])
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    try:
        process = subprocess.Popen(
            ["/usr/bin/sandbox-exec", "-p", profile, *command],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env=environment, close_fds=True,
        )
    except OSError as error:
        raise MigrationError("Protected Codex history reading could not start.") from error
    source = _SandboxedPaginatedSource(process)
    try:
        line = process.stdout.readline(4096)
        if not line or json.loads(line) != {"ready": True}:
            raise MigrationError("Protected Codex history reading could not start safely.")
        yield source
    finally:
        source.close()


def source_footprint(source_home: str):
    """Return thread count and on-disk database bytes for a preflight estimate.

    This is not the size of a future encrypted snapshot: SQLite pages and WAL
    framing are different from the validated JSONL records Vault stores.
    """
    database = _canonical_macos_path(Path(source_home) / ".codex/thread_history_1.sqlite")
    try:
        database.lstat()
    except FileNotFoundError:
        return 0, 0, False
    except OSError as error:
        raise MigrationError("Codex paginated history could not be measured safely.") from error
    with open_paginated_source(source_home) as source:
        count = len(source.thread_ids())
        size = database.lstat().st_size + _safe_sidecar_size(database, "-wal")
    return count, size, True


def source_fingerprint(source_home: str):
    """Conservative file-state hint for avoiding unchanged hosted DB reads.

    The authenticated published manifest remains content authority. Track the
    database, WAL, and rollback journal; WAL can hold uncheckpointed turns.
    Validate the shared-memory sidecar too, but do not fingerprint its volatile
    reader locks, which change without any conversation change.
    """
    codex = _canonical_macos_path(Path(source_home) / ".codex")
    try:
        codex.lstat()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise MigrationError("Codex paginated history could not be inspected safely.") from error
    _require_unlinked_path(codex)
    database = codex / "thread_history_1.sqlite"
    paths = [database, *(Path(str(database) + suffix)
                         for suffix in ("-wal", "-shm", "-journal"))]
    result = []
    present_sidecar = False
    for index, path in enumerate(paths):
        _require_unlinked_path(path, allow_missing_leaf=True)
        try:
            info = path.lstat()
        except FileNotFoundError:
            if index != 2:
                result.append(None)
            continue
        except OSError as error:
            raise MigrationError("Codex paginated history could not be inspected safely.") from error
        require_local(path)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1):
            raise MigrationError("Codex paginated history is not a private regular file.")
        if index > 0:
            present_sidecar = True
        if index != 2:
            result.append((info.st_dev, info.st_ino, info.st_size,
                           info.st_mtime_ns, info.st_ctime_ns))
    if result[0] is None:
        if present_sidecar:
            raise MigrationError("Codex paginated history has orphaned SQLite sidecars.")
        return None
    return tuple(result)


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != _READER_FLAG:
        raise SystemExit(2)
    raise SystemExit(_reader_main(sys.argv[2]))
