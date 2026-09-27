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
)
from codex_migrate.vault_identity import MAX_RECORD_BYTES

MAX_SCAN_BYTES = 256 * 1024 * 1024


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


def _drain_record(handle) -> bool:
    """Discard one oversized line within the scan budget; return if it ended."""
    while True:
        if handle.tell() >= MAX_SCAN_BYTES:
            return False
        block = handle.readline(1024 * 1024)
        if not block or block.endswith(b"\n"):
            return True


def preview_damaged_thread(source_home: str, collection: str, transcript: str,
                          *, max_entries: int = 100,
                          max_text_bytes: int = 1024 * 1024) -> SalvagePreview:
    """Recover only parseable records from the selected physical JSONL file.

    A bounded record may be parsed again after NUL bytes are removed from an
    in-memory copy. Other malformed or oversized records are counted and
    skipped, never invented. The result is withheld if the file changes while
    read. This is a preview, not a complete transcript export or Codex resume.
    """
    if (type(max_entries) is not int or type(max_text_bytes) is not int or
            not 1 <= max_entries <= 100 or
            not 1 <= max_text_bytes <= 1024 * 1024):
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
                raw = handle.readline(MAX_RECORD_BYTES + 1)
                if not raw:
                    break
                if len(raw) > MAX_RECORD_BYTES:
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
