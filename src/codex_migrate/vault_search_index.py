"""Optional, rebuildable candidate index for complete local Vault search.

The contentless FTS table stores trigrams, not transcript text. It can return
false positives; the normal Vault reader verifies every candidate against the
source. Missing, stale, or unreadable index entries are never used to exclude
source files.
"""

from contextlib import contextmanager
import fcntl
import json
import os
import shutil
import sqlite3
import stat
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Set, Tuple
from urllib.parse import quote

from codex_migrate.errors import MigrationError
from codex_migrate.vault_identity import MAX_RECORD_BYTES


INDEX_VERSION = 4
BLOCK_CHARS = 128 * 1024
QUERY_CHARS = 500
MAX_ATTACHMENT_QUERY_BYTES = 32 * 1024 * 1024
MIN_FREE_BYTES = 5 * 1024 * 1024 * 1024
INDEX_FOLDER = ("Library", "Caches", "Codex Migrate")


class IndexCancelled(Exception):
    """The user stopped a refresh; committed files remain safe to search."""


class SourceChanged(MigrationError):
    """A live transcript changed; leave it uncached for direct search."""


def supported() -> bool:
    """Probe the actual Python SQLite build without writing customer data."""
    if sqlite3.sqlite_version_info < (3, 43, 0):
        return False
    try:
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute("CREATE VIRTUAL TABLE probe USING fts5("
                               "body, content='', contentless_delete=1, "
                               "tokenize='trigram', detail='none')")
        finally:
            connection.close()
        return True
    except sqlite3.Error:
        return False


def _path(source_home: str) -> Path:
    return Path(source_home).joinpath(*INDEX_FOLDER, "search-index-v1.sqlite")


def _safe_parent(parent: Path) -> None:
    if (parent.is_symlink() or not parent.is_dir()
            or parent.stat().st_uid != os.geteuid()
            or parent.stat().st_mode & 0o077):
        raise MigrationError("The local search index folder has unsafe permissions.")


def _cache_files(target: Path) -> Tuple[Path, ...]:
    return (target, Path(str(target) + "-journal"), Path(str(target) + "-wal"),
            Path(str(target) + "-shm"))


def _require_index_space(parent: Path) -> None:
    try:
        free = shutil.disk_usage(parent).free
    except OSError as error:
        raise MigrationError("Free space for the local search cache could not be checked.") from error
    if free < MIN_FREE_BYTES:
        raise MigrationError("Fast search stopped before using the Mac's last 5 GB of space. "
                             "Search still works without this cache.")


def _owned_regular(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_mode & 0o077):
        raise MigrationError("The local search index has unsafe ownership or permissions.")
    return True


@contextmanager
def _cache_lock(parent: Path) -> Iterator[None]:
    path = parent / "search-index-v1.lock"
    try:
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except OSError as error:
        raise MigrationError("The local search index lock could not be opened safely.") from error
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077):
            raise MigrationError("The local search index lock has unsafe permissions.")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise MigrationError("Another local search index operation is running.") from error
        yield
    finally:
        os.close(descriptor)


def _source_stamp(path: Path) -> Tuple[int, int, int, int, int]:
    try:
        info = path.lstat()
    except OSError as error:
        raise SourceChanged("A conversation changed before it could be indexed.") from error
    if not stat.S_ISREG(info.st_mode):
        raise SourceChanged("A conversation changed before it could be indexed.")
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _database_stamp(source_home: str) -> Optional[str]:
    """Conservatively identify a live SQLite source, including its write log."""
    database = Path(source_home) / ".codex/thread_history_1.sqlite"
    try:
        database.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        return None
    stamps = []
    for path in (database, Path(str(database) + "-wal"),
                 Path(str(database) + "-journal")):
        try:
            info = path.lstat()
        except FileNotFoundError:
            stamps.append(None)
            continue
        except OSError:
            return None
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_nlink != 1):
            return None
        # SQLite may create an empty WAL while opening a read-only view. It
        # contains no committed pages, so its appearance must not invalidate
        # an otherwise complete index. Still reject unsafe zero-byte files.
        if path != database and info.st_size == 0:
            stamps.append(None)
        else:
            stamps.append((info.st_dev, info.st_ino, info.st_size,
                           info.st_mtime_ns, info.st_ctime_ns))
    return json.dumps(stamps, separators=(",", ":"))


def _attachment_may_match(source_home: str, folded: str) -> bool:
    """Do not let an index of JSON/SQLite hide separately stored pasted text."""
    from codex_migrate.vault_attachments import attachment_files, read_pasted_text
    from codex_migrate.vault_identity import canonical_id

    total = 0
    for _, path, relative in attachment_files(source_home):
        parts = relative.split("/")
        if (len(parts) != 2 or parts[1] != "pasted-text.txt"
                or canonical_id(parts[0]) != parts[0]):
            continue
        try:
            total += path.lstat().st_size
        except OSError:
            return True
        if total > MAX_ATTACHMENT_QUERY_BYTES:
            return True  # Too much to inspect cheaply: use the complete scan.
        body = read_pasted_text(source_home, parts[0])
        if body is None or folded in body.casefold():
            return True
    return False


def _schema(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys=ON")
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version not in (0, 1, 2, 3, INDEX_VERSION):
        raise MigrationError("This local search index has an unsupported format.")
    if version == 0 and connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') LIMIT 1").fetchone():
        raise MigrationError("The local search index has an incomplete or unexpected format.")
    if version in (1, 2, 3):
        # Older caches cannot verify whole phrases inside their unpositioned
        # trigram blocks. Reset only the disposable projections that changed.
        with connection:
            if version == 2:
                connection.execute("DELETE FROM paginated_stamp")
                connection.execute("DROP TABLE paginated_terms")
                connection.execute("DELETE FROM paginated_blocks")
                connection.execute("DELETE FROM paginated_threads")
            connection.execute("DROP TABLE text_terms")
            connection.execute("DELETE FROM blocks")
            connection.execute("DELETE FROM files")
    connection.execute("CREATE TABLE IF NOT EXISTS files ("
                       "id INTEGER PRIMARY KEY, collection TEXT NOT NULL, relative TEXT NOT NULL, "
                       "dev INTEGER NOT NULL, ino INTEGER NOT NULL, size INTEGER NOT NULL, "
                       "mtime_ns INTEGER NOT NULL, ctime_ns INTEGER NOT NULL, "
                       "UNIQUE(collection, relative))")
    connection.execute("CREATE TABLE IF NOT EXISTS blocks ("
                       "id INTEGER PRIMARY KEY, file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE)")
    connection.execute("CREATE INDEX IF NOT EXISTS blocks_file ON blocks(file_id)")
    connection.execute("CREATE VIRTUAL TABLE IF NOT EXISTS text_terms USING fts5("
                       "body, content='', contentless_delete=1, tokenize='trigram')")
    connection.execute("CREATE TABLE IF NOT EXISTS paginated_stamp ("
                       "id INTEGER PRIMARY KEY CHECK(id=1), source_stamp TEXT NOT NULL)")
    connection.execute("CREATE TABLE IF NOT EXISTS paginated_threads ("
                       "thread_id TEXT PRIMARY KEY)")
    connection.execute("CREATE TABLE IF NOT EXISTS paginated_blocks ("
                       "id INTEGER PRIMARY KEY, thread_id TEXT NOT NULL "
                       "REFERENCES paginated_threads(thread_id) ON DELETE CASCADE)")
    connection.execute("CREATE INDEX IF NOT EXISTS paginated_blocks_thread "
                       "ON paginated_blocks(thread_id)")
    connection.execute("CREATE VIRTUAL TABLE IF NOT EXISTS paginated_terms USING fts5("
                       "body, content='', contentless_delete=1, tokenize='trigram')")
    connection.execute("PRAGMA user_version=%d" % INDEX_VERSION)


def _text_blocks(value: str) -> List[str]:
    """Keep a <=500-character query within one block of one source string."""
    # SQLite's trigram tokenizer stops at NUL. A separator keeps text after
    # it searchable; queries containing NUL use the original full scan.
    folded = value.casefold().replace("\x00", "\n")
    if not folded:
        return []
    if len(folded) <= BLOCK_CHARS:
        return [folded]
    result = []
    start = 0
    while start < len(folded):
        result.append(folded[start:start + BLOCK_CHARS])
        if start + BLOCK_CHARS >= len(folded):
            break
        start += BLOCK_CHARS - (QUERY_CHARS - 1)
    return result


def _add_file(connection: sqlite3.Connection, collection: str,
              relative: str, path: Path, cache_parent: Path, cancelled=None) -> int:
    # Import lazily: vault.py also consults this module when searching.
    from codex_migrate.vault import _strings

    before = _source_stamp(path)
    old = connection.execute("SELECT id FROM files WHERE collection=? AND relative=?",
                             (collection, relative)).fetchone()
    if old is not None:
        block_ids = connection.execute("SELECT id FROM blocks WHERE file_id=?", (old[0],)).fetchall()
        for (block_id,) in block_ids:
            connection.execute("DELETE FROM text_terms WHERE rowid=?", (block_id,))
        connection.execute("DELETE FROM files WHERE id=?", (old[0],))
    cursor = connection.execute(
        "INSERT INTO files(collection,relative,dev,ino,size,mtime_ns,ctime_ns) "
        "VALUES (?,?,?,?,?,?,?)", (collection, relative, *before))
    file_id = cursor.lastrowid
    blocks = 0
    pending = []
    pending_chars = 0

    def flush() -> None:
        nonlocal blocks, pending, pending_chars
        if not pending:
            return
        if blocks % 128 == 0:
            _require_index_space(cache_parent)
        block_id = connection.execute("INSERT INTO blocks(file_id) VALUES (?)", (file_id,)).lastrowid
        connection.execute("INSERT INTO text_terms(rowid,body) VALUES (?,?)",
                           (block_id, "\n".join(pending)))
        blocks += 1
        pending = []
        pending_chars = 0

    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise SourceChanged("A conversation changed before it could be indexed.")
            while True:
                if cancelled is not None and cancelled.is_set():
                    raise IndexCancelled()
                raw = handle.readline(MAX_RECORD_BYTES + 1)
                if not raw:
                    break
                if len(raw) > MAX_RECORD_BYTES:
                    raise MigrationError("A conversation record is too large to index safely.")
                try:
                    record = json.loads(raw)
                except (UnicodeError, json.JSONDecodeError) as error:
                    if _source_stamp(path) != before:
                        raise SourceChanged("A conversation changed while it was indexed.") from error
                    raise MigrationError("A conversation contains unreadable JSON.") from error
                for text in _strings(record):
                    for block in _text_blocks(text):
                        if pending and pending_chars + len(block) + 1 > BLOCK_CHARS:
                            flush()
                        pending.append(block)
                        pending_chars += len(block) + 1
                        if pending_chars >= BLOCK_CHARS:
                            flush()
            after = os.fstat(handle.fileno())
        if before != (after.st_dev, after.st_ino, after.st_size,
                      after.st_mtime_ns, after.st_ctime_ns) or before != _source_stamp(path):
            raise SourceChanged("A conversation changed while it was being indexed.")
        flush()
    except FileNotFoundError as error:
        raise SourceChanged("A conversation moved while it was being indexed.") from error
    except OSError as error:
        raise MigrationError("A conversation could not be indexed safely.") from error
    return blocks


def _add_paginated_thread(connection: sqlite3.Connection, source,
                          thread_id: str, cache_parent: Path, cancelled=None) -> int:
    """Index only rendered search text, never a retrievable item JSON body."""
    from codex_migrate.vault import _strings

    connection.execute("INSERT INTO paginated_threads(thread_id) VALUES (?)", (thread_id,))
    pending: List[str] = []
    pending_chars = 0
    blocks = 0

    def flush() -> None:
        nonlocal blocks, pending, pending_chars
        if not pending:
            return
        if blocks % 128 == 0:
            _require_index_space(cache_parent)
        block_id = connection.execute(
            "INSERT INTO paginated_blocks(thread_id) VALUES (?)", (thread_id,)).lastrowid
        connection.execute("INSERT INTO paginated_terms(rowid,body) VALUES (?,?)",
                           (block_id, "\n".join(pending)))
        blocks += 1
        pending = []
        pending_chars = 0

    for item in source.items(thread_id):
        if cancelled is not None and cancelled.is_set():
            raise IndexCancelled()
        record = json.loads(item.item_json)
        for text in _strings(record):
            for block in _text_blocks(text):
                if pending and pending_chars + len(block) + 1 > BLOCK_CHARS:
                    flush()
                pending.append(block)
                pending_chars += len(block) + 1
                if pending_chars >= BLOCK_CHARS:
                    flush()
    flush()
    return blocks


def _refresh_paginated(target: Path, source_home: str, result: Dict[str, object],
                       progress: Optional[Callable[[int, int], None]],
                       transcript_total: int, cancelled) -> None:
    """A partial or changed database index has no valid stamp and is ignored."""
    from codex_migrate.vault_paginated import open_paginated_source

    before = _database_stamp(source_home)
    if before is None:
        return
    try:
        connection = sqlite3.connect(str(target), timeout=5)
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            stored = connection.execute(
                "SELECT source_stamp FROM paginated_stamp WHERE id=1").fetchone()
            if stored == (before,):
                result["paginated_threads"] = connection.execute(
                    "SELECT COUNT(*) FROM paginated_threads").fetchone()[0]
                result["paginated_indexed"] = True
                if progress is not None:
                    progress(transcript_total + result["paginated_threads"],
                             transcript_total + result["paginated_threads"])
                return
            with connection:
                connection.execute("DELETE FROM paginated_stamp")
            with open_paginated_source(source_home) as source:
                thread_ids = source.thread_ids()
                result["paginated_threads"] = len(thread_ids)
                total = transcript_total + len(thread_ids)
                for completed, thread_id in enumerate(thread_ids, 1):
                    if cancelled is not None and cancelled.is_set():
                        raise IndexCancelled()
                    with connection:
                        old = connection.execute(
                            "SELECT 1 FROM paginated_threads WHERE thread_id=?",
                            (thread_id,)).fetchone()
                        if old is not None:
                            block_ids = connection.execute(
                                "SELECT id FROM paginated_blocks WHERE thread_id=?",
                                (thread_id,)).fetchall()
                            for (block_id,) in block_ids:
                                connection.execute(
                                    "DELETE FROM paginated_terms WHERE rowid=?", (block_id,))
                            connection.execute("DELETE FROM paginated_threads WHERE thread_id=?",
                                               (thread_id,))
                        result["paginated_blocks"] = result.get("paginated_blocks", 0) + \
                            _add_paginated_thread(connection, source, thread_id,
                                                  target.parent, cancelled)
                    if progress is not None:
                        progress(transcript_total + completed, total)
                wanted = set(thread_ids)
                stale = connection.execute("SELECT thread_id FROM paginated_threads").fetchall()
                for (thread_id,) in stale:
                    if thread_id in wanted:
                        continue
                    if cancelled is not None and cancelled.is_set():
                        raise IndexCancelled()
                    with connection:
                        block_ids = connection.execute(
                            "SELECT id FROM paginated_blocks WHERE thread_id=?",
                            (thread_id,)).fetchall()
                        for (block_id,) in block_ids:
                            connection.execute(
                                "DELETE FROM paginated_terms WHERE rowid=?", (block_id,))
                        connection.execute("DELETE FROM paginated_threads WHERE thread_id=?",
                                           (thread_id,))
            after = _database_stamp(source_home)
            if before != after or cancelled is not None and cancelled.is_set():
                result["paginated_skipped"] = True
                return
            with connection:
                connection.execute("INSERT INTO paginated_stamp(id,source_stamp) VALUES (1,?)",
                                   (after,))
            result["paginated_indexed"] = True
        finally:
            connection.close()
    except sqlite3.Error as error:
        raise MigrationError("Paginated conversation search could not be indexed safely.") from error


def build(source_home: str, apply: bool = False,
          progress: Optional[Callable[[int, int], None]] = None,
          cancelled=None) -> Dict[str, object]:
    """Refresh an explicitly approved cache. Source transcripts are read-only."""
    from codex_migrate.vault import _transcripts

    discovered = list(_transcripts(source_home))
    result = {"applied": False, "transcripts": len(discovered), "indexed": 0,
              "blocks": 0, "skipped": 0, "index": str(_path(source_home))}
    if _owned_regular(_path(source_home)):
        result["index_bytes"] = _path(source_home).stat().st_size
    if not apply:
        return result
    if not supported():
        raise MigrationError("Fast search is unavailable in this Mac's SQLite. "
                             "Regular conversation search still works.")
    if Path(source_home).stat().st_uid != os.geteuid():
        raise MigrationError("Fast search can only index the current account's home.")
    paginated_count = 0
    if _database_stamp(source_home) is not None:
        from codex_migrate.vault_paginated import open_paginated_source
        with open_paginated_source(source_home) as source:
            paginated_count = len(source.thread_ids())
    target = _path(source_home)
    parent = target.parent
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _safe_parent(parent)
    _require_index_space(parent)
    with _cache_lock(parent):
        if not _owned_regular(target):
            descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                                 0o600)
            os.close(descriptor)
        def combined_progress(completed: int, _: int) -> None:
            if progress is not None:
                progress(completed, len(discovered) + paginated_count)

        _refresh(target, discovered, result, combined_progress, cancelled)
        _refresh_paginated(target, source_home, result, progress, len(discovered), cancelled)
        result["index_bytes"] = target.stat().st_size
        return result


def _refresh(target: Path, discovered: List[Tuple[str, Path, str]],
             result: Dict[str, object],
             progress: Optional[Callable[[int, int], None]], cancelled) -> Dict[str, object]:
    try:
        connection = sqlite3.connect(str(target), timeout=5)
        try:
            _schema(connection)
            indexed = blocks = skipped = 0
            wanted = set()
            if progress is not None:
                progress(0, len(discovered))
            for completed, (collection, path, relative) in enumerate(discovered, 1):
                if cancelled is not None and cancelled.is_set():
                    raise IndexCancelled()
                wanted.add((collection, relative))
                try:
                    stamp = _source_stamp(path)
                except SourceChanged:
                    skipped += 1
                    if progress is not None:
                        progress(completed, len(discovered))
                    continue
                prior = connection.execute(
                    "SELECT dev,ino,size,mtime_ns,ctime_ns FROM files "
                    "WHERE collection=? AND relative=?", (collection, relative)).fetchone()
                if prior == stamp:
                    if progress is not None:
                        progress(completed, len(discovered))
                    continue
                try:
                    with connection:
                        blocks += _add_file(connection, collection, relative, path,
                                            target.parent, cancelled)
                except SourceChanged:
                    skipped += 1
                    if progress is not None:
                        progress(completed, len(discovered))
                    continue
                indexed += 1
                if progress is not None:
                    progress(completed, len(discovered))
            if cancelled is not None and cancelled.is_set():
                raise IndexCancelled()
            for collection, relative, file_id in connection.execute(
                    "SELECT collection,relative,id FROM files").fetchall():
                if cancelled is not None and cancelled.is_set():
                    raise IndexCancelled()
                if (collection, relative) in wanted:
                    continue
                with connection:
                    for (block_id,) in connection.execute(
                            "SELECT id FROM blocks WHERE file_id=?", (file_id,)).fetchall():
                        connection.execute("DELETE FROM text_terms WHERE rowid=?", (block_id,))
                    connection.execute("DELETE FROM files WHERE id=?", (file_id,))
            result.update(applied=True, indexed=indexed, blocks=blocks, skipped=skipped)
        finally:
            connection.close()
    except sqlite3.Error as error:
        raise MigrationError("The local search index could not be updated safely.") from error
    result["index_bytes"] = target.stat().st_size
    return result


def remove(source_home: str, apply: bool = False) -> Dict[str, object]:
    """Remove only the exact, rebuildable search cache after explicit approval."""
    target = _path(source_home)
    files = _cache_files(target)
    exists = any([_owned_regular(path) for path in files])
    result = {"applied": False, "present": exists, "index": str(target)}
    if not apply or not exists:
        return result
    _safe_parent(target.parent)
    with _cache_lock(target.parent):
        present = [path for path in files if _owned_regular(path)]
        try:
            for path in present:
                path.unlink()
        except OSError as error:
            raise MigrationError("The local search index could not be removed safely.") from error
    result["applied"] = bool(present)
    result["present"] = False
    return result


def candidates(source_home: str, query: str,
               discovered: List[Tuple[str, Path, str]]) -> Optional[Set[Path]]:
    """Return a superset of matching physical files, or None for a full scan."""
    folded = query.casefold()
    target = _path(source_home)
    if "\x00" in folded or len(folded) < 3 or len(folded) > QUERY_CHARS:
        return None
    if _attachment_may_match(source_home, folded):
        return None
    try:
        _safe_parent(target.parent)
        available = _owned_regular(target)
    except (MigrationError, OSError):
        return None
    if not available:
        return None
    try:
        connection = sqlite3.connect("file:%s?mode=ro" % quote(str(target), safe="/"),
                                     uri=True, timeout=2)
        try:
            if connection.execute("PRAGMA user_version").fetchone()[0] != INDEX_VERSION:
                return None
            expression = _phrase_expression(folded)
            matches = set(connection.execute(
                "SELECT DISTINCT f.collection,f.relative FROM text_terms "
                "JOIN blocks b ON b.id=text_terms.rowid JOIN files f ON f.id=b.file_id "
                "WHERE text_terms MATCH ?", (expression,)).fetchall())
            indexed = {(collection, relative): (dev, ino, size, mtime_ns, ctime_ns)
                       for collection, relative, dev, ino, size, mtime_ns, ctime_ns in
                       connection.execute("SELECT collection,relative,dev,ino,size,mtime_ns,ctime_ns FROM files")}
        finally:
            connection.close()
    except sqlite3.Error:
        return None
    result = set()
    try:
        for collection, path, relative in discovered:
            key = (collection, relative)
            if key in matches or indexed.get(key) != _source_stamp(path):
                result.add(path)
    except SourceChanged:
        return None
    return result


def _phrase_expression(folded: str) -> str:
    return '"' + folded.replace('"', '""') + '"'


def paginated_candidates(source_home: str, query: str) -> Optional[Set[str]]:
    """Return candidate physical rollout IDs only for a complete, current index."""
    folded = query.casefold()
    if "\x00" in folded or len(folded) < 3 or len(folded) > QUERY_CHARS:
        return None
    if _attachment_may_match(source_home, folded):
        return None
    source_stamp = _database_stamp(source_home)
    if source_stamp is None:
        return None
    target = _path(source_home)
    try:
        _safe_parent(target.parent)
        if not _owned_regular(target):
            return None
        connection = sqlite3.connect("file:%s?mode=ro" % quote(str(target), safe="/"),
                                     uri=True, timeout=2)
        try:
            if connection.execute("PRAGMA user_version").fetchone()[0] != INDEX_VERSION:
                return None
            stored = connection.execute(
                "SELECT source_stamp FROM paginated_stamp WHERE id=1").fetchone()
            if stored != (source_stamp,):
                return None
            matches = {thread_id for (thread_id,) in connection.execute(
                "SELECT DISTINCT b.thread_id FROM paginated_terms "
                "JOIN paginated_blocks b ON b.id=paginated_terms.rowid "
                "WHERE paginated_terms MATCH ?", (_phrase_expression(folded),))}
        finally:
            connection.close()
    except (MigrationError, OSError, sqlite3.Error):
        return None
    if source_stamp != _database_stamp(source_home):
        return None
    return matches
