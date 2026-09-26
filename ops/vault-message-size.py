"""Read-only sizing of a proposed conversation-only off-device archive.

The selection is intentionally narrow: original ``response_item`` records
whose payload is a user or assistant message. It omits tool calls/results,
reasoning, events, media stored elsewhere, and Codex-restoration state. This
is a size measurement, not a backup or a claim that the selection is complete.
Only aggregate counts leave the process; transcript text and paths do not.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys
import zlib


MAX_RECORD_BYTES = 128 * 1024 * 1024
READ_BLOCK = 1024 * 1024
FOLDERS = ("sessions", "archived_sessions")


def _skip_record(stream) -> int:
    """Consume the tail of a too-large record without retaining it."""
    consumed = 0
    while True:
        block = stream.readline(READ_BLOCK)
        consumed += len(block)
        if not block or block.endswith(b"\n"):
            return consumed


def _is_message(record: object) -> bool:
    if not isinstance(record, dict) or record.get("type") != "response_item":
        return False
    payload = record.get("payload")
    return (isinstance(payload, dict) and payload.get("type") == "message"
            and payload.get("role") in ("user", "assistant"))


def estimate(source_home: str) -> dict[str, int | bool | str]:
    codex = Path(source_home) / ".codex"
    if codex.is_symlink() or not codex.is_dir():
        raise ValueError("Codex source is absent or linked")
    totals: dict[str, int | bool | str] = {
        "transcripts": 0,
        "source_bytes": 0,
        "message_records": 0,
        "message_source_bytes": 0,
        "message_gzip_bytes": 0,
        "unclassified_records": 0,
        "unclassified_bytes": 0,
        "changed_transcripts": 0,
        "changed_bytes": 0,
        "scope": "user/assistant response_item message records only",
        "complete": True,
    }
    for folder in FOLDERS:
        root = codex / folder
        if not root.exists():
            continue
        if root.is_symlink() or not root.is_dir():
            raise ValueError("Conversation folder is linked or not a directory")
        for current, directories, files in os.walk(root, followlinks=False):
            base = Path(current)
            if base.is_symlink() or any((base / name).is_symlink() for name in directories):
                raise ValueError("Conversation tree contains a linked directory")
            for name in files:
                if not name.endswith(".jsonl"):
                    continue
                path = base / name
                before = path.lstat()
                if not stat.S_ISREG(before.st_mode):
                    raise ValueError("Conversation tree contains a nonregular transcript")
                descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(descriptor, "rb") as stream:
                    opened = os.fstat(stream.fileno())
                    if (opened.st_dev, opened.st_ino, opened.st_size) != (
                            before.st_dev, before.st_ino, before.st_size):
                        raise ValueError("Transcript changed before sizing")
                    compressor = zlib.compressobj(level=6, wbits=31)
                    file_bytes = 0
                    file_messages = 0
                    while True:
                        line = stream.readline(MAX_RECORD_BYTES + 1)
                        if not line:
                            break
                        file_bytes += len(line)
                        if len(line) > MAX_RECORD_BYTES:
                            oversized_bytes = len(line)
                            if not line.endswith(b"\n"):
                                remainder = _skip_record(stream)
                                file_bytes += remainder
                                oversized_bytes += remainder
                            totals["unclassified_records"] += 1
                            totals["unclassified_bytes"] += oversized_bytes
                            totals["complete"] = False
                            continue
                        # This cheap prefix filter avoids decoding the bulk of
                        # tool output. The parser below makes the real decision.
                        if b'"response_item"' not in line or b'"message"' not in line:
                            continue
                        try:
                            record = json.loads(line)
                        except (UnicodeError, json.JSONDecodeError):
                            totals["unclassified_records"] += 1
                            totals["unclassified_bytes"] += len(line)
                            totals["complete"] = False
                            continue
                        if _is_message(record):
                            file_messages += 1
                            totals["message_records"] += 1
                            totals["message_source_bytes"] += len(line)
                            totals["message_gzip_bytes"] += len(compressor.compress(line))
                    if file_messages:
                        totals["message_gzip_bytes"] += len(compressor.flush())
                    after = os.fstat(stream.fileno())
                totals["transcripts"] += 1
                totals["source_bytes"] += file_bytes
                if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
                    before.st_ctime_ns) != (after.st_dev, after.st_ino, after.st_size,
                                           after.st_mtime_ns, after.st_ctime_ns):
                    totals["changed_transcripts"] += 1
                    totals["changed_bytes"] += file_bytes
                    totals["complete"] = False
    return totals


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-home", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(estimate(args.source_home), sort_keys=True))
    except Exception as error:
        # Paths, content, and digests must not escape through an exception.
        print("Sizing stopped safely (%s); no aggregate was produced." %
              type(error).__name__, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
