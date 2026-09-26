"""Read-only inspection and search for local Codex conversation transcripts.

This is the first Codex Vault boundary. It deliberately reads only the two
documented transcript trees and never opens authentication or installation
identity files. Search is streaming and creates no derived copy or index.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import stat
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

from codex_migrate.errors import MigrationError
from codex_migrate.source_availability import check_info, require_local
from codex_migrate.vault_identity import MAX_RECORD_BYTES, canonical_id, filename_id, title_index


TRANSCRIPT_FOLDERS = ("sessions", "archived_sessions")
TEXT_KEYS = frozenset(("content", "message", "summary", "text", "title"))
MAX_LINEAGE_DEPTH = 32


@dataclass(frozen=True)
class VaultSummary:
    active_transcripts: int
    archived_transcripts: int
    transcript_bytes: int

    def as_dict(self) -> Dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class VaultMatch:
    collection: str
    transcript: str
    line: int
    timestamp: Optional[str]
    snippet: str
    title: Optional[str] = None
    cursor: int = 0

    def as_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ThreadEntry:
    timestamp: Optional[str]
    role: Optional[str]
    text: str
    excerpted: bool = False

    def as_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class VaultThread:
    collection: str
    transcript: str
    entries: List[ThreadEntry]

    def as_dict(self) -> Dict[str, object]:
        return {
            "collection": self.collection,
            "transcript": self.transcript,
            "entries": [entry.as_dict() for entry in self.entries],
        }


def _transcripts(source_home: str) -> Iterator[Tuple[str, Path, str]]:
    """Yield regular JSONL transcripts without following links."""
    codex = Path(source_home) / ".codex"
    if codex.is_symlink():
        raise MigrationError("The Codex data folder is linked; review its storage before browsing history.")
    if not codex.is_dir():
        raise MigrationError("No local Codex data folder was found.")
    require_local(codex)
    for folder in TRANSCRIPT_FOLDERS:
        root = codex / folder
        if not root.exists():
            continue
        if root.is_symlink() or not root.is_dir():
            raise MigrationError("The Codex conversation folder needs review before history can be read.")
        require_local(root)
        try:
            for current, directories, files in os.walk(root, followlinks=False):
                current_path = Path(current)
                require_local(current_path)
                if any((current_path / name).is_symlink() for name in directories):
                    raise MigrationError("A linked conversation folder needs review before history can be read.")
                for name in files:
                    if not name.endswith(".jsonl"):
                        continue
                    path = current_path / name
                    info = check_info(path.lstat())
                    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                        raise MigrationError("A conversation transcript is not a regular file; history was not read.")
                    relative = path.relative_to(root).as_posix()
                    yield folder, path, relative
        except OSError as error:
            raise MigrationError("Codex conversation history could not be read safely.") from error


def _rollout_map(discovered: List[Tuple[str, Path, str]]) -> Dict[str, List[Path]]:
    by_rollout: Dict[str, List[Path]] = {}
    for _, candidate, relative in discovered:
        rollout_id = filename_id(relative)
        if rollout_id:
            by_rollout.setdefault(rollout_id, []).append(candidate)
    return by_rollout


def _lineage_segments(
    source_home: str, path: Path,
    transcripts: Optional[List[Tuple[str, Path, str]]] = None,
    rollouts: Optional[Dict[str, List[Path]]] = None,
) -> List[Tuple[Path, int]]:
    """Resolve the physical, byte-bounded rollout prefixes visible in a fork.

    A paginated fork's history_base names a rollout ID (not necessarily the
    stable thread ID after a revert). Only discovered transcript files may be
    followed; missing, ambiguous, cyclic, or torn references fail closed.
    """
    discovered = transcripts if transcripts is not None else list(_transcripts(source_home))
    by_rollout = rollouts if rollouts is not None else _rollout_map(discovered)

    def resolve(candidate: Path, cutoff: Optional[int], expected_ordinal: Optional[int],
                seen: set) -> List[Tuple[Path, int]]:
        if candidate in seen or len(seen) >= MAX_LINEAGE_DEPTH:
            raise MigrationError("A conversation has cyclic or unusually deep fork history.")
        try:
            descriptor = os.open(candidate, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as handle:
                info = os.fstat(handle.fileno())
                if not stat.S_ISREG(info.st_mode):
                    raise MigrationError("A conversation lineage is not a regular file.")
                length = info.st_size if cutoff is None else cutoff
                if not isinstance(length, int) or length < 0 or length > info.st_size:
                    raise MigrationError("A conversation fork points outside its parent history.")
                if length:
                    handle.seek(length - 1)
                    if handle.read(1) != b"\n":
                        raise MigrationError("A conversation fork cuts through a parent record.")
                if expected_ordinal is not None:
                    if length == 0:
                        if expected_ordinal != 0:
                            raise MigrationError("A conversation fork has a mismatched parent boundary.")
                    else:
                        # A byte boundary is insufficient after a parent rewrite: it
                        # might still land on a different complete JSONL record.
                        position = length - 2
                        record_start = 0
                        while position >= 0:
                            block_start = max(0, position - 4095)
                            handle.seek(block_start)
                            block = handle.read(position - block_start + 1)
                            previous_newline = block.rfind(b"\n")
                            if previous_newline >= 0:
                                record_start = block_start + previous_newline + 1
                                break
                            if length - block_start > MAX_RECORD_BYTES:
                                raise MigrationError("A conversation parent record is too large.")
                            position = block_start - 1
                        if length - record_start > MAX_RECORD_BYTES:
                            raise MigrationError("A conversation parent record is too large.")
                        handle.seek(record_start)
                        last_record = json.loads(handle.read(length - record_start))
                        ordinal = (last_record.get("ordinal")
                                   if isinstance(last_record, dict) else None)
                        if (not isinstance(ordinal, int) or isinstance(ordinal, bool)
                                or ordinal + 1 != expected_ordinal):
                            raise MigrationError("A conversation fork has a mismatched parent boundary.")
                handle.seek(0)
                raw = handle.readline(MAX_RECORD_BYTES + 1)
                if len(raw) > MAX_RECORD_BYTES:
                    raise MigrationError("A conversation header is too large to inspect safely.")
                header = json.loads(raw) if raw else {}
        except MigrationError:
            raise
        except (UnicodeError, json.JSONDecodeError) as error:
            raise MigrationError("A conversation transcript contains unreadable JSON.") from error
        except OSError as error:
            raise MigrationError("A conversation fork could not be inspected safely.") from error
        payload = header.get("payload") if isinstance(header, dict) else None
        base = payload.get("history_base") if (isinstance(header, dict)
                                               and header.get("type") == "session_meta"
                                               and isinstance(payload, dict)) else None
        prefix: List[Tuple[Path, int]] = []
        if base is not None:
            if not isinstance(base, dict):
                raise MigrationError("A conversation fork has an invalid parent reference.")
            parent_id = canonical_id(base.get("thread_id"))
            boundary = base.get("end_byte_offset")
            ordinal = base.get("end_ordinal_exclusive")
            if (not parent_id or not isinstance(boundary, int) or isinstance(boundary, bool)
                    or boundary < 0 or not isinstance(ordinal, int)
                    or isinstance(ordinal, bool) or ordinal < 0):
                raise MigrationError("A conversation fork has an invalid parent reference.")
            parents = by_rollout.get(parent_id, [])
            if len(parents) != 1:
                raise MigrationError("A conversation fork's parent is missing or ambiguous.")
            prefix = resolve(parents[0], boundary, ordinal, seen | {candidate})
        return prefix + [(candidate, length)]

    return resolve(path, None, None, set())


def _lineage_records(segments: List[Tuple[Path, int]], cursor: int = 0,
                     stable: bool = False):
    """Yield (record, virtual byte cursor, virtual line) across a fork lineage."""
    origin = 0
    line_number = 0
    for path, length in segments:
        if cursor >= origin + length:
            origin += length
            continue
        start = max(0, cursor - origin)
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as handle:
                info = os.fstat(handle.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size < length:
                    raise MigrationError("A conversation lineage changed while it was read.")
                if start:
                    handle.seek(start - 1)
                    if handle.read(1) != b"\n":
                        raise MigrationError("A conversation cursor is not at a record boundary.")
                handle.seek(start)
                try:
                    while handle.tell() < length:
                        position = handle.tell()
                        raw = handle.readline(min(MAX_RECORD_BYTES + 1, length - position + 1))
                        if not raw or len(raw) > MAX_RECORD_BYTES or position + len(raw) > length:
                            raise MigrationError("A conversation record is incomplete or too large.")
                        try:
                            record = json.loads(raw)
                        except (UnicodeError, json.JSONDecodeError) as error:
                            raise MigrationError("A conversation transcript contains unreadable JSON.") from error
                        line_number += 1
                        yield record, origin + position, line_number
                finally:
                    if stable:
                        after = os.fstat(handle.fileno())
                        if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
                                info.st_ctime_ns) != (after.st_dev, after.st_ino, after.st_size,
                                                       after.st_mtime_ns, after.st_ctime_ns):
                            raise MigrationError("A conversation lineage changed while it was read.")
        except MigrationError:
            raise
        except OSError as error:
            raise MigrationError("A conversation lineage could not be read safely.") from error
        origin += length


def inspect(source_home: str) -> VaultSummary:
    active = 0
    archived = 0
    total = 0
    for folder, path, _ in _transcripts(source_home):
        info = check_info(path.lstat())
        total += info.st_size
        if folder == "sessions":
            active += 1
        else:
            archived += 1
    return VaultSummary(active, archived, total)


def _strings(value: object, key: str = "") -> Iterable[str]:
    if isinstance(value, str):
        if key.casefold() in TEXT_KEYS:
            yield value
        return
    if isinstance(value, list):
        for item in value:
            yield from _strings(item, key)
        return
    if isinstance(value, dict):
        for child_key, child in value.items():
            if isinstance(child_key, str):
                yield from _strings(child, child_key)


def _timestamp(record: object) -> Optional[str]:
    if not isinstance(record, dict):
        return None
    value = record.get("timestamp")
    if isinstance(value, str) and len(value) <= 100 and "\n" not in value and "\r" not in value:
        return value
    payload = record.get("payload")
    if isinstance(payload, dict):
        value = payload.get("timestamp")
        if isinstance(value, str) and len(value) <= 100 and "\n" not in value and "\r" not in value:
            return value
    return None


def _first_named_string(value: object, name: str) -> Optional[str]:
    if isinstance(value, dict):
        direct = value.get(name)
        if (isinstance(direct, str) and len(direct) <= 80
                and "\n" not in direct and "\r" not in direct):
            return direct
        for child in value.values():
            found = _first_named_string(child, name)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _first_named_string(child, name)
            if found is not None:
                return found
    return None


def _snippet(text: str, start: int, query_length: int, width: int = 220) -> str:
    compact = " ".join(text.split())
    if len(compact) <= width:
        return compact
    folded = compact.casefold()
    # Whitespace normalization can move the original offset. Find again in the
    # display value and otherwise keep the beginning as a safe fallback.
    needle = text[start:start + query_length].casefold()
    display_start = folded.find(needle)
    if display_start < 0:
        display_start = 0
    left = max(0, display_start - width // 3)
    right = min(len(compact), left + width)
    prefix = "…" if left else ""
    suffix = "…" if right < len(compact) else ""
    return prefix + compact[left:right] + suffix


def search(
    source_home: str,
    query: str,
    limit: int = 25,
    catalog: Optional[List[Dict[str, object]]] = None,
    offset: int = 0,
    titles_only: bool = False,
) -> List[VaultMatch]:
    """Find recent matching conversations without retaining a local content index."""
    needle = query.strip().casefold()
    if not needle:
        raise ValueError("search query must not be empty")
    if limit < 1 or limit > 500:
        raise ValueError("search limit must be between 1 and 500")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0 or offset > 100000:
        raise ValueError("search offset must be between 0 and 100000")
    matches: List[VaultMatch] = []
    matched_threads = 0
    indexed = title_index(source_home) if catalog is None else {}
    catalog_by_path = {
        (item["collection"], item["path"]): item
        for item in (catalog or [])
    }
    discovered = list(_transcripts(source_home))
    rollouts = _rollout_map(discovered) if not titles_only else None
    indexed_candidates = None
    if not titles_only:
        from codex_migrate.vault_search_index import candidates
        indexed_candidates = candidates(source_home, query.strip(), discovered)
    transcripts = []
    for folder, path, relative in discovered:
        try:
            info = check_info(path.lstat())
        except OSError as error:
            raise MigrationError("Codex conversation history could not be read safely.") from error
        if not stat.S_ISREG(info.st_mode):
            raise MigrationError("A conversation transcript changed while it was being read.")
        transcripts.append((info.st_mtime_ns, folder, path, relative))
    transcripts.sort(key=lambda item: (item[0], item[3]), reverse=True)
    for _, folder, path, relative in transcripts:
        collection = "active" if folder == "sessions" else "archived"
        metadata = catalog_by_path.get((collection, relative))
        aliases = (metadata.get("titles", []) if metadata is not None
                   else indexed.get(filename_id(relative), []))
        current_title = aliases[-1] if aliases else None
        title_match = next((title for title in reversed(aliases)
                            if needle in title.casefold()), None)
        match = None
        if title_match:
            match = VaultMatch(
                collection=collection, transcript=relative, line=0,
                timestamp=None,
                title=current_title,
                snippet="Title: " + _snippet(title_match,
                                              title_match.casefold().find(needle),
                                              len(query.strip())),
            )
        elif not titles_only:
            segments = _lineage_segments(source_home, path, discovered, rollouts)
            if (indexed_candidates is not None
                    and not any(part in indexed_candidates for part, _ in segments)):
                continue
            for record, cursor, line_number in _lineage_records(segments):
                seen = set()
                for text in _strings(record):
                    if text in seen:
                        continue
                    seen.add(text)
                    position = text.casefold().find(needle)
                    if position < 0:
                        continue
                    match = VaultMatch(
                        collection=collection,
                        transcript=relative,
                        line=line_number,
                        timestamp=_timestamp(record),
                        title=current_title,
                        snippet=_snippet(text, position, len(query.strip())),
                        cursor=cursor,
                    )
                    break
                if match is not None:
                    break
        if match is not None:
            if matched_threads >= offset:
                matches.append(match)
                if len(matches) >= limit:
                    return matches
            matched_threads += 1
    return matches


def _find_transcript(source_home: str, collection: str, transcript: str) -> Path:
    if collection not in ("active", "archived"):
        raise ValueError("unknown conversation collection")
    if not transcript or transcript.startswith("/") or "\\" in transcript:
        raise ValueError("invalid conversation identifier")
    folder = "sessions" if collection == "active" else "archived_sessions"
    for candidate_folder, path, relative in _transcripts(source_home):
        if candidate_folder == folder and relative == transcript:
            return path
    raise ValueError("conversation was not found")


def read_thread(
    source_home: str,
    collection: str,
    transcript: str,
    max_text_bytes: int = 25 * 1024 * 1024,
) -> VaultThread:
    """Return message-like text from one exact discovered transcript."""
    path = _find_transcript(source_home, collection, transcript)
    entries: List[ThreadEntry] = []
    total = 0
    for record, _, _ in _lineage_records(_lineage_segments(source_home, path)):
        seen = set()
        for text in _strings(record):
            if text in seen:
                continue
            seen.add(text)
            encoded_size = len(text.encode("utf-8"))
            if total + encoded_size > max_text_bytes:
                raise MigrationError("This conversation is too large for the browser export. The original transcript was not changed.")
            total += encoded_size
            entries.append(ThreadEntry(
                timestamp=_timestamp(record),
                role=_first_named_string(record, "role"),
                text=text,
            ))
    return VaultThread(collection, transcript, entries)


def read_thread_page(
    source_home: str, collection: str, transcript: str, cursor: int = 0,
    max_entries: int = 100, max_text_bytes: int = 1024 * 1024,
    expected_query: str = "",
):
    """Read one bounded page of a verified Vault browse copy by byte offset."""
    if not isinstance(cursor, int) or cursor < 0 or cursor > 1 << 63:
        raise ValueError("invalid conversation cursor")
    if not 1 <= max_entries <= 100 or not 1 <= max_text_bytes <= 1024 * 1024:
        raise ValueError("invalid conversation page budget")
    if not isinstance(expected_query, str) or len(expected_query) > 500:
        raise ValueError("invalid conversation search match")
    path = _find_transcript(source_home, collection, transcript)
    entries: List[ThreadEntry] = []
    total = 0
    segments = _lineage_segments(source_home, path)
    if cursor > sum(length for _, length in segments):
        raise MigrationError("A saved conversation changed while opening it.")
    next_cursor = None
    records = _lineage_records(segments, cursor, stable=True)
    try:
        for record, start, _ in records:
            if expected_query and start == cursor and not any(
                    expected_query.casefold() in body.casefold()
                    for body in _strings(record)):
                raise MigrationError("This conversation changed since the search. Search again.")
            seen = set()
            new_entries = []
            new_bytes = 0
            for body in _strings(record):
                if body in seen:
                    continue
                seen.add(body)
                new_bytes += len(body.encode("utf-8"))
                new_entries.append(ThreadEntry(
                    timestamp=_timestamp(record),
                    role=_first_named_string(record, "role"), text=body,
                ))
            if (expected_query and start == cursor
                    and (len(new_entries) > max_entries
                         or total + new_bytes > max_text_bytes)):
                matched = next(entry.text for entry in new_entries
                               if expected_query.casefold() in entry.text.casefold())
                position = matched.casefold().find(expected_query.casefold())
                excerpt = _snippet(matched, position, len(expected_query), width=1000)
                new_entries = [ThreadEntry(
                    timestamp=_timestamp(record),
                    role=_first_named_string(record, "role"),
                    text=excerpt, excerpted=True,
                )]
                new_bytes = len(excerpt.encode("utf-8"))
            if (len(entries) + len(new_entries) > max_entries
                    or total + new_bytes > max_text_bytes):
                if not entries:
                    raise MigrationError("This message is too large to preview. Export the saved conversation instead.")
                next_cursor = start
                break
            entries.extend(new_entries)
            total += new_bytes
    finally:
        records.close()
    return VaultThread(collection, transcript, entries), next_cursor


def markdown(thread: VaultThread) -> str:
    """Create a portable, plain Markdown representation of a thread."""
    lines = [
        "# Codex conversation",
        "",
        "- Collection: %s" % thread.collection,
        "- Transcript: `%s`" % thread.transcript.replace("`", "\\`"),
        "",
    ]
    for index, entry in enumerate(thread.entries, start=1):
        heading = entry.role.strip().title() if entry.role and entry.role.strip() else "Entry %d" % index
        lines.extend(("## %s" % heading, ""))
        if entry.timestamp:
            lines.extend(("_%s_" % entry.timestamp, ""))
        lines.extend((entry.text, ""))
    return "\n".join(lines).rstrip() + "\n"


def markdown_chunks(source_home: str, collection: str, transcript: str):
    """Stream an exact transcript as Markdown without buffering its full body.

    Intended for an already verified, private Vault browse copy. The caller
    must keep that copy alive until the iterator is exhausted.
    """
    path = _find_transcript(source_home, collection, transcript)
    segments = _lineage_segments(source_home, path)
    header = "# Codex conversation\n\n- Collection: %s\n- Transcript: `%s`\n\n" % (
        collection, transcript.replace("`", "\\`"))
    yield header.encode("utf-8")
    index = 0
    for record, _, _ in _lineage_records(segments, stable=True):
        seen = set()
        for body in _strings(record):
            if body in seen:
                continue
            seen.add(body)
            index += 1
            role = _first_named_string(record, "role")
            heading = role.strip().title() if role and role.strip() else "Entry %d" % index
            timestamp = _timestamp(record)
            prefix = "## %s\n\n" % heading
            if timestamp:
                prefix += "_%s_\n\n" % timestamp
            yield (prefix + body + "\n\n").encode("utf-8")
