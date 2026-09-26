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
import sqlite3
import stat
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Set, Tuple

from codex_migrate.errors import MigrationError
from codex_migrate.vault_identity import MAX_RECORD_BYTES


INDEX_VERSION = 1
BLOCK_CHARS = 128 * 1024
QUERY_CHARS = 500
INDEX_FOLDER = ("Library", "Caches", "Codex Migrate")


class IndexCancelled(Exception):
    """The user stopped a refresh; committed files remain safe to search."""


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
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise MigrationError("A conversation changed before it could be indexed.")
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _schema(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys=ON")
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version not in (0, INDEX_VERSION):
        raise MigrationError("This local search index has an unsupported format.")
    if version == 0 and connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') LIMIT 1").fetchone():
        raise MigrationError("The local search index has an incomplete or unexpected format.")
    connection.execute("CREATE TABLE IF NOT EXISTS files ("
                       "id INTEGER PRIMARY KEY, collection TEXT NOT NULL, relative TEXT NOT NULL, "
                       "dev INTEGER NOT NULL, ino INTEGER NOT NULL, size INTEGER NOT NULL, "
                       "mtime_ns INTEGER NOT NULL, ctime_ns INTEGER NOT NULL, "
                       "UNIQUE(collection, relative))")
    connection.execute("CREATE TABLE IF NOT EXISTS blocks ("
                       "id INTEGER PRIMARY KEY, file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE)")
    connection.execute("CREATE INDEX IF NOT EXISTS blocks_file ON blocks(file_id)")
    connection.execute("CREATE VIRTUAL TABLE IF NOT EXISTS text_terms USING fts5("
                       "body, content='', contentless_delete=1, tokenize='trigram', detail='none')")
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
              relative: str, path: Path, cancelled=None) -> int:
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
                raise MigrationError("A conversation changed before it could be indexed.")
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
            raise MigrationError("A conversation changed while it was being indexed.")
        flush()
    except OSError as error:
        raise MigrationError("A conversation could not be indexed safely.") from error
    return blocks


def build(source_home: str, apply: bool = False,
          progress: Optional[Callable[[int, int], None]] = None,
          cancelled=None) -> Dict[str, object]:
    """Refresh an explicitly approved cache. Source transcripts are read-only."""
    from codex_migrate.vault import _transcripts

    discovered = list(_transcripts(source_home))
    result = {"applied": False, "transcripts": len(discovered), "indexed": 0,
              "blocks": 0, "index": str(_path(source_home))}
    if _owned_regular(_path(source_home)):
        result["index_bytes"] = _path(source_home).stat().st_size
    if not apply:
        return result
    if not supported():
        raise MigrationError("Fast search is unavailable in this Mac's SQLite. "
                             "Regular conversation search still works.")
    if Path(source_home).stat().st_uid != os.geteuid():
        raise MigrationError("Fast search can only index the current account's home.")
    target = _path(source_home)
    parent = target.parent
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _safe_parent(parent)
    with _cache_lock(parent):
        if not _owned_regular(target):
            descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                                 0o600)
            os.close(descriptor)
        return _refresh(target, discovered, result, progress, cancelled)


def _refresh(target: Path, discovered: List[Tuple[str, Path, str]],
             result: Dict[str, object],
             progress: Optional[Callable[[int, int], None]], cancelled) -> Dict[str, object]:
    try:
        connection = sqlite3.connect(str(target), timeout=5)
        try:
            _schema(connection)
            indexed = blocks = 0
            wanted = set()
            if progress is not None:
                progress(0, len(discovered))
            for completed, (collection, path, relative) in enumerate(discovered, 1):
                if cancelled is not None and cancelled.is_set():
                    raise IndexCancelled()
                wanted.add((collection, relative))
                stamp = _source_stamp(path)
                prior = connection.execute(
                    "SELECT dev,ino,size,mtime_ns,ctime_ns FROM files "
                    "WHERE collection=? AND relative=?", (collection, relative)).fetchone()
                if prior == stamp:
                    if progress is not None:
                        progress(completed, len(discovered))
                    continue
                with connection:
                    blocks += _add_file(connection, collection, relative, path, cancelled)
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
            result.update(applied=True, indexed=indexed, blocks=blocks)
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
    try:
        _safe_parent(target.parent)
        available = _owned_regular(target)
    except MigrationError:
        return None
    if not available:
        return None
    try:
        connection = sqlite3.connect("file:%s?mode=ro" % target, uri=True, timeout=2)
        try:
            if connection.execute("PRAGMA user_version").fetchone()[0] != INDEX_VERSION:
                return None
            positions = list(range(len(folded) - 2))
            if len(positions) > 16:
                positions = sorted({positions[(i * (len(positions) - 1)) // 15]
                                    for i in range(16)})
            grams = list(dict.fromkeys(folded[i:i + 3] for i in positions))
            expression = " AND ".join('"%s"' % gram.replace('"', '""') for gram in grams)
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
    for collection, path, relative in discovered:
        key = (collection, relative)
        if key in matches or indexed.get(key) != _source_stamp(path):
            result.add(path)
    return result
