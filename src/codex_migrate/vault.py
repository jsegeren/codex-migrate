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


TRANSCRIPT_FOLDERS = ("sessions", "archived_sessions")
TEXT_KEYS = frozenset(("content", "message", "summary", "text", "title"))


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

    def as_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ThreadEntry:
    timestamp: Optional[str]
    role: Optional[str]
    text: str

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


def search(source_home: str, query: str, limit: int = 25) -> List[VaultMatch]:
    """Search message-like JSON values without retaining a local index."""
    needle = query.strip().casefold()
    if not needle:
        raise ValueError("search query must not be empty")
    if limit < 1 or limit > 500:
        raise ValueError("search limit must be between 1 and 500")
    matches: List[VaultMatch] = []
    for folder, path, relative in _transcripts(source_home):
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
                info = os.fstat(handle.fileno())
                if not stat.S_ISREG(info.st_mode):
                    raise MigrationError("A conversation transcript changed while it was being read.")
                for line_number, line in enumerate(handle, start=1):
                    try:
                        record = json.loads(line)
                    except (UnicodeError, json.JSONDecodeError) as error:
                        raise MigrationError("A conversation transcript contains unreadable JSON; history search stopped.") from error
                    seen = set()
                    for text in _strings(record):
                        if text in seen:
                            continue
                        seen.add(text)
                        position = text.casefold().find(needle)
                        if position < 0:
                            continue
                        matches.append(VaultMatch(
                            collection="active" if folder == "sessions" else "archived",
                            transcript=relative,
                            line=line_number,
                            timestamp=_timestamp(record),
                            snippet=_snippet(text, position, len(query.strip())),
                        ))
                        if len(matches) >= limit:
                            return matches
        except MigrationError:
            raise
        except (OSError, UnicodeError) as error:
            raise MigrationError("Codex conversation history could not be read safely.") from error
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
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise MigrationError("A conversation transcript changed while it was being read.")
            for line in handle:
                try:
                    record = json.loads(line)
                except (UnicodeError, json.JSONDecodeError) as error:
                    raise MigrationError("A conversation transcript contains unreadable JSON; it was not opened.") from error
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
    except MigrationError:
        raise
    except (OSError, UnicodeError) as error:
        raise MigrationError("The conversation could not be read safely.") from error
    return VaultThread(collection, transcript, entries)


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
