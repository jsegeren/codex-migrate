"""Opt-in, read-only preview of intact records in one damaged transcript.

This is not a Codex repair. It reads only an exact discovered JSONL file,
never changes it, and deliberately does not infer missing fork ancestry.
Normal Vault reading and search remain strict.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import stat
from typing import Dict, List

from codex_migrate.errors import MigrationError
from codex_migrate.vault import (
    ThreadEntry, _find_transcript, _first_named_string, _strings, _timestamp,
    _transcripts,
)
from codex_migrate.vault_identity import MAX_RECORD_BYTES, filename_id, title_index

MAX_SCAN_BYTES = 256 * 1024 * 1024
MAX_SALVAGE_RECORD_BYTES = min(MAX_RECORD_BYTES, 16 * 1024 * 1024)


@dataclass(frozen=True)
class SalvagePreview:
    collection: str
    transcript: str
    entries: List[ThreadEntry]
    parsed_records: int
    nul_repaired_records: int
    skipped_records: int
    preview_truncated: bool
    scan_truncated: bool
    physical_file_only: bool = True

    def as_dict(self) -> Dict[str, object]:
        return {
            "collection": self.collection, "transcript": self.transcript,
            "entries": [entry.as_dict() for entry in self.entries],
            "parsed_records": self.parsed_records,
            "nul_repaired_records": self.nul_repaired_records,
            "skipped_records": self.skipped_records,
            "preview_truncated": self.preview_truncated,
            "scan_truncated": self.scan_truncated,
            "physical_file_only": self.physical_file_only,
        }


def _stamp(info: os.stat_result):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns)


def find_transcripts(source_home: str, query: str = "", *, offset: int = 0,
                     limit: int = 50) -> Dict[str, object]:
    """Find physical transcripts by filename or known title, without reading bodies.

    This is a separate opt-in discovery path for damaged files; it does not
    label any candidate corrupt or claim that a title index is complete.
    """
    if (not isinstance(query, str) or len(query) > 200 or
            type(offset) is not int or not 0 <= offset <= 100000 or
            type(limit) is not int or not 1 <= limit <= 100):
        raise ValueError("invalid salvage discovery query")
    discovered = list(_transcripts(source_home))
    try:
        titles = title_index(source_home)
        titles_available = True
    except MigrationError:
        titles = {}
        titles_available = False
    needle = query.strip().casefold()
    found = []
    for folder, path, relative in discovered:
        try:
            info = path.lstat()
        except OSError as error:
            raise MigrationError("Conversation files changed during discovery; retry.") from error
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise MigrationError("A conversation file changed during discovery; retry.")
        aliases = titles.get(filename_id(relative), [])
        if needle and needle not in relative.casefold() and not any(
                needle in title.casefold() for title in aliases):
            continue
        found.append({
            "collection": "active" if folder == "sessions" else "archived",
            "transcript": relative,
            "title": aliases[-1] if aliases else None,
            "modified_ms": info.st_mtime_ns // 1000000,
        })
    found.sort(key=lambda item: (item["modified_ms"], item["transcript"]),
               reverse=True)
    return {"results": found[offset:offset + limit],
            "has_more": len(found) > offset + limit,
            "titles_available": titles_available}


def _drain_record(handle) -> bool:
    """Discard one oversized line within the scan budget; return if it ended."""
    while True:
        remaining = MAX_SCAN_BYTES - handle.tell()
        if remaining <= 0:
            return False
        block = handle.readline(min(1024 * 1024, remaining))
        if not block or block.endswith(b"\n"):
            return True


def preview_damaged_thread(source_home: str, collection: str, transcript: str,
                          *, max_entries: int = 100,
                          max_text_bytes: int = 1024 * 1024) -> SalvagePreview:
    """Preview only parseable records from the selected physical JSONL file.

    A bounded record may be parsed again after NUL bytes are removed from an
    in-memory copy. Other malformed or oversized records are counted and
    skipped, never invented. The result is withheld if the file changes while
    read. This is a preview, not a complete transcript export or Codex resume.
    """
    if (type(max_entries) is not int or type(max_text_bytes) is not int or
            not 1 <= max_entries <= 20000 or
            not 1 <= max_text_bytes <= 25 * 1024 * 1024):
        raise ValueError("invalid salvage preview budget")
    path = _find_transcript(source_home, collection, transcript)
    entries: List[ThreadEntry] = []
    parsed = repaired = skipped = text_bytes = 0
    truncated = scan_truncated = False
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise MigrationError("The selected conversation is not a safe regular file.")
            while True:
                if handle.tell() >= MAX_SCAN_BYTES:
                    scan_truncated = handle.tell() < before.st_size
                    break
                raw = handle.readline(min(MAX_SALVAGE_RECORD_BYTES + 1,
                                          MAX_SCAN_BYTES - handle.tell()))
                if not raw:
                    break
                if (not raw.endswith(b"\n") and handle.tell() >= MAX_SCAN_BYTES
                        and handle.tell() < before.st_size):
                    # This is an incomplete record, not an intact message to
                    # expose just because the scan ended mid-line.
                    scan_truncated = True
                    break
                if len(raw) > MAX_SALVAGE_RECORD_BYTES:
                    skipped += 1
                    if not raw.endswith(b"\n") and not _drain_record(handle):
                        scan_truncated = True
                        break
                    continue
                damaged = b"\x00" in raw
                try:
                    record = json.loads(raw.replace(b"\x00", b"") if damaged else raw)
                except (UnicodeError, json.JSONDecodeError):
                    skipped += 1
                    continue
                if not isinstance(record, dict):
                    skipped += 1
                    continue
                parsed += 1
                repaired += int(damaged)
                seen = set()
                candidate_entries: List[ThreadEntry] = []
                candidate_bytes = 0
                candidate_truncated = False
                try:
                    for text in _strings(record):
                        if text in seen:
                            continue
                        seen.add(text)
                        size = len(text.encode("utf-8"))
                        if (len(entries) + len(candidate_entries) >= max_entries or
                                text_bytes + candidate_bytes + size > max_text_bytes):
                            candidate_truncated = True
                            continue
                        candidate_entries.append(ThreadEntry(
                            timestamp=_timestamp(record),
                            role=_first_named_string(record, "role"), text=text))
                        candidate_bytes += size
                except (RecursionError, UnicodeError):
                    parsed -= 1
                    repaired -= int(damaged)
                    skipped += 1
                    continue
                entries.extend(candidate_entries)
                text_bytes += candidate_bytes
                truncated |= candidate_truncated
            after = os.fstat(handle.fileno())
        if _stamp(before) != _stamp(after) or _stamp(after) != _stamp(path.lstat()):
            raise MigrationError("The conversation changed during salvage; retry from the original.")
    except MigrationError:
        raise
    except OSError as error:
        raise MigrationError("The conversation could not be read safely for salvage.") from error
    return SalvagePreview(collection, transcript, entries, parsed, repaired,
                          skipped, truncated, scan_truncated)


def incomplete_markdown(result: SalvagePreview) -> str:
    """Export only the parseable preview, with conspicuous provenance limits."""
    lines = [
        "# INCOMPLETE Codex transcript salvage",
        "",
        "Read-only extraction from one physical JSONL file. This is not the original",
        "transcript, a complete backup, or a file to install into Codex.",
        "Malformed records were skipped. NUL bytes were removed only from an",
        "in-memory copy; any original bytes they replaced remain lost, even",
        "when the resulting JSON can be read. Missing text cannot be recovered here.",
        "Fork ancestry is not included. The original file was not changed.",
        "",
        "Collection: %s" % result.collection,
        "Transcript: %s" % json.dumps(result.transcript, ensure_ascii=False),
        "Readable records: %d" % result.parsed_records,
        "Parseable after NUL removal (may be incomplete): %d" % result.nul_repaired_records,
        "Skipped records: %d" % result.skipped_records,
        "Preview limit reached: %s" % ("yes" if result.preview_truncated else "no"),
        "Scan limit reached: %s" % ("yes" if result.scan_truncated else "no"),
        "",
    ]
    for index, entry in enumerate(result.entries, 1):
        lines.extend(["---", "", "## Entry %d" % index,
                      "Role: %s" % (entry.role or "unknown"),
                      "Time: %s" % (entry.timestamp or "unknown"),
                      "", entry.text, ""])
    return "\n".join(lines)
