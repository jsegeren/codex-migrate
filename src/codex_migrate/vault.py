"""Read-only inspection and search for local Codex conversation history.

This reads the two transcript trees and the known paginated-history schema,
never authentication or installation identity files. Search is streaming and
creates no derived copy or index.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
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


class AmbiguousLineage(MigrationError):
    """Multiple physical rollouts could supply one thread's inherited text."""


@dataclass(frozen=True)
class VaultSummary:
    active_transcripts: int
    archived_transcripts: int
    transcript_bytes: int
    paginated_threads: int = 0
    paginated_database_bytes: int = 0
    paginated_database_present: bool = False

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
            if not parents:
                raise MigrationError("A conversation fork's parent is missing or ambiguous.")
            if len(parents) != 1:
                raise AmbiguousLineage("A conversation fork's parent is missing or ambiguous.")
            prefix = resolve(parents[0], boundary, ordinal, seen | {candidate})
        return prefix + [(candidate, length)]

    return resolve(path, None, None, set())


def _session_payload(path: Path) -> Optional[Dict[str, object]]:
    """Read only the bounded rollout header; never inspect private body text."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise MigrationError("A conversation lineage is not a regular file.")
            raw = handle.readline(MAX_RECORD_BYTES + 1)
        if len(raw) > MAX_RECORD_BYTES:
            raise MigrationError("A conversation header is too large to inspect safely.")
        header = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise MigrationError("A conversation header contains unreadable JSON.") from error
    except OSError as error:
        raise MigrationError("A conversation header could not be inspected safely.") from error
    if not isinstance(header, dict) or header.get("type") != "session_meta":
        return None
    payload = header.get("payload")
    return payload if isinstance(payload, dict) else None


def _selected_rollouts(discovered: List[Tuple[str, Path, str]]) -> Dict[str, List[Path]]:
    selected: Dict[str, List[Path]] = {}
    for _, path, _ in discovered:
        payload = _session_payload(path)
        if payload is not None:
            thread_id = canonical_id(payload.get("id"))
            if thread_id:
                selected.setdefault(thread_id, []).append(path)
    return selected


def _paginated_ranges(source_home: str, thread_id: str,
                      discovered: Optional[List[Tuple[str, Path, str]]] = None,
                      selected: Optional[Dict[str, List[Path]]] = None,
                      rollouts: Optional[Dict[str, List[Path]]] = None):
    """Return Codex-visible (rollout ID, start ordinal, exclusive end) ranges.

    Database rows belong to physical rollouts, while a fork inherits bounded
    ancestor ranges. Missing or ambiguous lineage fails closed; a database-only
    thread without a rollout keeps its exact-ID rows.
    """
    if canonical_id(thread_id) != thread_id:
        raise ValueError("invalid paginated conversation identifier")
    discovered = discovered if discovered is not None else list(_transcripts(source_home))
    selected = selected if selected is not None else _selected_rollouts(discovered)
    paths = selected.get(thread_id, [])
    if not paths:
        return [(thread_id, 0, None)]
    if len(paths) != 1:
        raise AmbiguousLineage("A paginated conversation has ambiguous selected rollouts.")
    segments = _lineage_segments(source_home, paths[0], discovered, rollouts)
    headers = [_session_payload(path) for path, _ in segments]
    ranges = []
    for index, (path, _) in enumerate(segments):
        rollout_id = filename_id(path.name)
        if not rollout_id or headers[index] is None:
            raise MigrationError("A paginated conversation has invalid rollout metadata.")
        base = headers[index].get("history_base")
        start = base["end_ordinal_exclusive"] + 1 if isinstance(base, dict) else 1
        next_base = (headers[index + 1].get("history_base")
                     if index + 1 < len(headers) else None)
        end = (next_base["end_ordinal_exclusive"]
               if isinstance(next_base, dict) else None)
        if end is not None and end < start:
            raise MigrationError("A paginated conversation has invalid ordinal bounds.")
        ranges.append((rollout_id, start, end))
    return ranges


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
    from codex_migrate.vault_paginated import source_footprint

    paginated_threads, paginated_bytes, paginated_present = source_footprint(source_home)
    return VaultSummary(active, archived, total, paginated_threads,
                        paginated_bytes, paginated_present)


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
    warnings: Optional[List[str]] = None,
) -> List[VaultMatch]:
    """Find title matches first; report skipped ambiguous lineages to callers."""
    def skipped_ambiguous() -> None:
        if warnings is not None and "ambiguous_lineage" not in warnings:
            warnings.append("ambiguous_lineage")
    needle = query.strip().casefold()
    if not needle:
        raise ValueError("search query must not be empty")
    if limit < 1 or limit > 500:
        raise ValueError("search limit must be between 1 and 500")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0 or offset > 100000:
        raise ValueError("search offset must be between 0 and 100000")
    matches: List[VaultMatch] = []
    matched_threads = 0
    indexed = {}
    if catalog is None:
        try:
            indexed = title_index(source_home)
        except MigrationError:
            if titles_only:
                raise
            # A damaged optional title index must not hide intact transcript text.
    catalog_by_path = {
        (item["collection"], item["path"]): item
        for item in (catalog or [])
    }
    discovered = list(_transcripts(source_home))
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
    prepared = []
    for _, folder, path, relative in transcripts:
        collection = "active" if folder == "sessions" else "archived"
        metadata = catalog_by_path.get((collection, relative))
        aliases = (metadata.get("titles", []) if metadata is not None
                   else indexed.get(filename_id(relative), []))
        current_title = aliases[-1] if aliases else None
        title_match = next((title for title in reversed(aliases)
                            if needle in title.casefold()), None)
        prepared.append((path, relative, collection, current_title, title_match))
    # An old title must be findable without scanning gigabytes of newer body
    # text first. A title hit represents its thread once; body search below
    # skips it rather than adding a misleading duplicate result.
    for _, relative, collection, current_title, title_match in prepared:
        if title_match is None:
            continue
        match = VaultMatch(
            collection=collection, transcript=relative, line=0,
            timestamp=None, title=current_title,
            snippet="Title: " + _snippet(title_match,
                                          title_match.casefold().find(needle),
                                          len(query.strip())),
        )
        if matched_threads >= offset:
            matches.append(match)
            if len(matches) >= limit:
                return matches
        matched_threads += 1
    if titles_only:
        return matches
    selected_rollouts = _selected_rollouts(discovered)
    rollouts = _rollout_map(discovered)
    paginated_catalog_ids = _paginated_catalog_ids(catalog)
    # Backup v3 keeps database-derived items separate from rollouts. Search
    # their authenticated, restored files without claiming the two sources
    # are interchangeable or creating a plaintext persistent index.
    for metadata in (item for item in (catalog or [])
                     if item.get("collection") == "paginated"):
        transcript = metadata["path"]
        aliases = metadata.get("titles") or []
        title = aliases[-1] if aliases else None
        title_match = next((alias for alias in reversed(aliases)
                            if needle in alias.casefold()), None)
        found = (VaultMatch(collection="paginated", transcript=transcript,
                            line=0, timestamp=None, title=title,
                            snippet="Title: " + title_match)
                 if title_match else None)
        if found is None:
            try:
                for index, group in _paginated_entries(
                        source_home, transcript, discovered=discovered,
                        selected=selected_rollouts, rollouts=rollouts,
                        available=paginated_catalog_ids):
                    for entry in group:
                        position = entry.text.casefold().find(needle)
                        if position >= 0:
                            found = VaultMatch(
                                collection="paginated", transcript=transcript,
                                line=index + 1, timestamp=entry.timestamp, title=title,
                                snippet=_snippet(entry.text, position, len(query.strip())),
                                cursor=index)
                            break
                    if found is not None:
                        break
            except AmbiguousLineage:
                skipped_ambiguous()
                continue
        if found is not None:
            if matched_threads >= offset:
                matches.append(found)
                if len(matches) >= limit:
                    return matches
            matched_threads += 1
    if catalog is None:
        database = Path(source_home) / ".codex/thread_history_1.sqlite"
        try:
            database.lstat()
        except FileNotFoundError:
            pass
        except OSError as error:
            raise MigrationError("Codex paginated history could not be inspected safely.") from error
        else:
            from codex_migrate.vault_paginated import open_paginated_source
            from codex_migrate.vault_search_index import paginated_candidates

            with open_paginated_source(source_home) as source:
                # Decide whether the index is current only after pinning the
                # SQLite read view. A write between an earlier index check and
                # this BEGIN could otherwise hide a newly added message.
                indexed_rollouts = paginated_candidates(source_home, query.strip())
                for thread_id in source.thread_ids_recent():
                    transcript = thread_id + ".jsonl"
                    aliases = indexed.get(thread_id, [])
                    title = aliases[-1] if aliases else None
                    title_match = next((alias for alias in reversed(aliases)
                                        if needle in alias.casefold()), None)
                    found = (VaultMatch(collection="paginated", transcript=transcript,
                                        line=0, timestamp=None, title=title,
                                        snippet="Title: " + title_match)
                             if title_match else None)
                    if found is None:
                        try:
                            ranges = _paginated_ranges(
                                source_home, thread_id, discovered, selected_rollouts, rollouts)
                        except AmbiguousLineage:
                            skipped_ambiguous()
                            continue
                        if (indexed_rollouts is not None
                                and not any(rollout_id in indexed_rollouts
                                            for rollout_id, _, _ in ranges)):
                            continue
                        items = (item for rollout_id, start, end in ranges
                                 for item in source.items_range(rollout_id, start, end))
                        for index, group in _paginated_item_entries(items):
                            for entry in group:
                                position = entry.text.casefold().find(needle)
                                if position >= 0:
                                    found = VaultMatch(
                                        collection="paginated", transcript=transcript,
                                        line=index + 1, timestamp=entry.timestamp,
                                        title=title,
                                        snippet=_snippet(entry.text, position,
                                                         len(query.strip())), cursor=index)
                                    break
                            if found is not None:
                                break
                    if found is not None:
                        if matched_threads >= offset:
                            matches.append(found)
                            if len(matches) >= limit:
                                return matches
                        matched_threads += 1
    from codex_migrate.vault_search_index import candidates
    indexed_candidates = candidates(source_home, query.strip(), discovered)
    for path, relative, collection, current_title, title_match in prepared:
        if title_match is not None:
            continue
        match = None
        try:
            segments = _lineage_segments(source_home, path, discovered, rollouts)
        except AmbiguousLineage:
            skipped_ambiguous()
            continue
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


def _paginated_item_entries(items):
    """Render database items as message-like text without synthetic rollouts."""
    for index, item in enumerate(items):
        record = json.loads(item.item_json)
        try:
            timestamp = datetime.fromtimestamp(
                item.created_at_ms / 1000, timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            timestamp = None
        role = {"userMessage": "User", "agentMessage": "Assistant"}.get(
            item.item_type, item.item_type)
        seen = set()
        entries = []
        for body in _strings(record):
            if body in seen:
                continue
            seen.add(body)
            entries.append(ThreadEntry(timestamp=timestamp, role=role, text=body))
        yield index, entries


def _paginated_catalog_ids(catalog):
    if catalog is None:
        return None
    ids = set()
    for item in catalog:
        if not isinstance(item, dict) or item.get("collection") != "paginated":
            continue
        path = item.get("path")
        if isinstance(path, str) and path.endswith(".jsonl"):
            thread_id = path[:-6]
            if canonical_id(thread_id) == thread_id:
                ids.add(thread_id)
    return ids


def _paginated_entries(source_home: str, transcript: str, live: bool = False,
                       discovered=None, selected=None, rollouts=None, catalog=None,
                       available=None):
    """Read either live SQLite or a separately restored database projection."""
    from codex_migrate.vault_paginated import open_paginated_source, restored_items

    if not isinstance(transcript, str) or not transcript.endswith(".jsonl"):
        raise ValueError("invalid paginated conversation identifier")
    thread_id = transcript[:-6]
    ranges = _paginated_ranges(source_home, thread_id, discovered, selected, rollouts)
    if live:
        with open_paginated_source(source_home) as source:
            items = (item for rollout_id, start, end in ranges
                     for item in source.items_range(rollout_id, start, end))
            yield from _paginated_item_entries(items)
    else:
        if available is None:
            available = _paginated_catalog_ids(catalog)
        if available is not None and thread_id not in available:
            raise MigrationError("This paginated conversation is not in the selected backup.")
        items = (item for rollout_id, start, end in ranges
                 if available is None or rollout_id in available
                 for item in restored_items(source_home, rollout_id, start, end))
        yield from _paginated_item_entries(items)


def read_thread(
    source_home: str,
    collection: str,
    transcript: str,
    max_text_bytes: int = 25 * 1024 * 1024,
    live_paginated: bool = False,
    catalog: Optional[List[Dict[str, object]]] = None,
) -> VaultThread:
    """Return message-like text from one exact discovered transcript."""
    if collection == "paginated":
        entries: List[ThreadEntry] = []
        total = 0
        for _, group in _paginated_entries(source_home, transcript, live_paginated,
                                           catalog=catalog):
            for entry in group:
                total += len(entry.text.encode("utf-8"))
                if total > max_text_bytes:
                    raise MigrationError("This paginated conversation is too large for browser export.")
                entries.append(entry)
        return VaultThread(collection, transcript, entries)
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
    live_paginated: bool = False,
    catalog: Optional[List[Dict[str, object]]] = None,
):
    """Read one bounded page of a live or verified Vault conversation."""
    if not isinstance(cursor, int) or cursor < 0 or cursor > 1 << 63:
        raise ValueError("invalid conversation cursor")
    if not 1 <= max_entries <= 100 or not 1 <= max_text_bytes <= 1024 * 1024:
        raise ValueError("invalid conversation page budget")
    if not isinstance(expected_query, str) or len(expected_query) > 500:
        raise ValueError("invalid conversation search match")
    if collection == "paginated":
        entries: List[ThreadEntry] = []
        total = 0
        next_cursor = None
        matched_cursor = False
        seen_count = 0
        for index, group in _paginated_entries(source_home, transcript, live_paginated,
                                                catalog=catalog):
            seen_count = index + 1
            if index < cursor:
                continue
            if index == cursor:
                matched_cursor = True
                if expected_query and not any(expected_query.casefold() in entry.text.casefold()
                                              for entry in group):
                    raise MigrationError("This conversation changed since the search. Search again.")
            group_bytes = sum(len(entry.text.encode("utf-8")) for entry in group)
            if len(entries) + len(group) > max_entries or total + group_bytes > max_text_bytes:
                if not entries:
                    if not group:
                        raise MigrationError("This paginated record is too large to preview safely.")
                    matching = (next(entry for entry in group
                                     if expected_query.casefold() in entry.text.casefold())
                                if expected_query else next((entry for entry in group
                                                             if entry.text), group[0]))
                    position = (matching.text.casefold().find(expected_query.casefold())
                                if expected_query else 0)
                    excerpt = _snippet(matching.text, position, len(expected_query), width=1000)
                    excerpt = excerpt.encode("utf-8")[:max_text_bytes].decode(
                        "utf-8", errors="ignore")
                    entries.append(ThreadEntry(
                        timestamp=matching.timestamp, role=matching.role,
                        text=excerpt,
                        excerpted=True))
                    next_cursor = index + 1
                else:
                    next_cursor = index
                break
            entries.extend(group)
            total += group_bytes
        if (cursor > seen_count or (expected_query and not matched_cursor)):
            raise MigrationError("The saved paginated conversation changed while opening it.")
        return VaultThread(collection, transcript, entries), next_cursor
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
                    if expected_query and start == cursor:
                        raise MigrationError("The search match exceeds the preview budget. Download Markdown for the full conversation.")
                    if not new_entries:
                        raise MigrationError("This conversation record is too large to preview safely.")
                    first = next((entry for entry in new_entries if entry.text), new_entries[0])
                    excerpt = first.text[:1000].encode("utf-8")[:max_text_bytes].decode(
                        "utf-8", errors="ignore")
                    new_entries = [ThreadEntry(
                        timestamp=first.timestamp, role=first.role,
                        text=excerpt, excerpted=True,
                    )]
                    new_bytes = len(excerpt.encode("utf-8"))
                else:
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


def markdown_chunks(source_home: str, collection: str, transcript: str,
                    live_paginated_source=None, catalog=None):
    """Stream an exact transcript as Markdown without buffering its full body.

    For a saved source, the caller keeps the verified private browse copy alive.
    For a live paginated source, the caller keeps one pinned read transaction
    alive until the iterator is exhausted.
    """
    if collection == "paginated":
        if not isinstance(transcript, str) or not transcript.endswith(".jsonl"):
            raise ValueError("invalid paginated conversation identifier")
        thread_id = transcript[:-6]
        if canonical_id(thread_id) != thread_id:
            raise ValueError("invalid paginated conversation identifier")
        if live_paginated_source is not None:
            ranges = _paginated_ranges(source_home, thread_id)
            items = (item for rollout_id, start, end in ranges
                     for item in live_paginated_source.items_range(rollout_id, start, end))
            groups = _paginated_item_entries(items)
        else:
            groups = _paginated_entries(source_home, transcript, catalog=catalog)
        label = "live Codex paginated source" if live_paginated_source is not None else "saved paginated source"
        header = "# Codex conversation (%s)\n\n- Collection: paginated\n- Thread: `%s`\n\n" % (label,
            transcript.replace("`", "\\`"))
        yield header.encode("utf-8")
        for _, group in groups:
            for entry in group:
                prefix = "## %s\n\n" % (entry.role or "Entry")
                if entry.timestamp:
                    prefix += "_%s_\n\n" % entry.timestamp
                yield (prefix + entry.text + "\n\n").encode("utf-8")
        return
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


def markdown_source_stamp(source_home: str, collection: str, transcript: str,
                          catalog=None):
    """Bind a prepared export to the exact transcript lineage it measured."""
    if collection == "paginated":
        from codex_migrate.vault_paginated import restored_path

        if not isinstance(transcript, str) or not transcript.endswith(".jsonl"):
            raise ValueError("invalid paginated conversation identifier")
        thread_id = transcript[:-6]
        discovered = list(_transcripts(source_home))
        selected = _selected_rollouts(discovered)
        ranges = _paginated_ranges(source_home, thread_id, discovered, selected,
                                   _rollout_map(discovered))
        available = _paginated_catalog_ids(catalog)
        if available is not None and thread_id not in available:
            raise MigrationError("This paginated conversation is not in the selected backup.")
        stamp = []
        for rollout_id, _, _ in ranges:
            if available is not None and rollout_id not in available:
                continue
            path = restored_path(source_home, rollout_id)
            info = check_info(path.lstat())
            stamp.append((str(path), info.st_dev, info.st_ino, info.st_size,
                          info.st_mtime_ns, info.st_ctime_ns))
        paths = selected.get(thread_id, [])
        if paths:
            for path, length in _lineage_segments(source_home, paths[0], discovered):
                info = check_info(path.lstat())
                if not stat.S_ISREG(info.st_mode) or info.st_size < length:
                    raise MigrationError("A paginated conversation changed before export.")
                stamp.append((str(path), length, info.st_dev, info.st_ino,
                              info.st_size, info.st_mtime_ns, info.st_ctime_ns))
        return tuple(stamp)
    path = _find_transcript(source_home, collection, transcript)
    stamp = []
    for segment, length in _lineage_segments(source_home, path):
        try:
            info = check_info(segment.lstat())
        except OSError as error:
            raise MigrationError("A conversation changed before export.") from error
        if not stat.S_ISREG(info.st_mode) or info.st_size < length:
            raise MigrationError("A conversation changed before export.")
        stamp.append((str(segment), length, info.st_dev, info.st_ino,
                      info.st_size, info.st_mtime_ns, info.st_ctime_ns))
    return tuple(stamp)
