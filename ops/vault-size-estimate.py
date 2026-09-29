"""Read-only aggregate sizing for a Vault and a readable text archive.

This operator-only tool never creates a snapshot or index. It prints aggregate
counts only; it does not print transcript paths, content, or digests. The text
figure is a *reading-copy estimate*, not a Codex-restorable backup.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import time
from typing import Dict, Union
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_migrate.vault import _strings, _transcripts  # noqa: E402
from codex_migrate.vault_attachments import attachment_files  # noqa: E402
from codex_migrate.vault_identity import MAX_RECORD_BYTES  # noqa: E402
from codex_migrate.vault_paginated import (  # noqa: E402
    encoded_item, open_paginated_source, source_fingerprint,
)


CHUNK_SIZE = 4 * 1024 * 1024
AES_GCM_OVERHEAD = 28  # 12-byte nonce plus 16-byte tag, per unique object.
COMPRESSION_LZFSE = 2049


def _encoder():
    library = ctypes.CDLL("/usr/lib/libcompression.dylib")
    function = library.compression_encode_buffer
    function.argtypes = (
        ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t,
        ctypes.c_void_p, ctypes.c_int,
    )
    function.restype = ctypes.c_size_t
    return function


def _encoded_size(data: bytes, encode) -> tuple[int, bool]:
    if len(data) < 1024:
        return len(data), False
    source = (ctypes.c_uint8 * len(data)).from_buffer_copy(data)
    target = (ctypes.c_uint8 * len(data))()
    size = encode(target, len(data), source, len(data), None, COMPRESSION_LZFSE)
    if size and size + 64 < len(data):
        return size, True
    return len(data), False


def _record_text(raw: bytes) -> bytes:
    try:
        record = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("a transcript contains unreadable JSON; no text estimate was produced") from error
    seen = set()
    pieces = []
    for value in _strings(record):
        if value in seen:
            continue
        seen.add(value)
        pieces.append(value.encode("utf-8") + b"\n")
    return b"".join(pieces)


def estimate(source_home: str, exclude_recent_seconds: int = 0,
             storage_only: bool = False,
             include_extra_sources: bool = False,
             extra_sources_only: bool = False) -> Dict[str, Union[int, str, bool]]:
    """Read the same transcript trees/chunk boundaries as Vault backup.

    The first-backup object byte count models an empty Vault and excludes
    refs/manifests and file-system allocation overhead. Optional full-scope
    sizing includes attachment files and encoded paginated conversation items.
    The text estimate covers only transcripts and is not a restorable copy.
    """
    include_extra_sources = include_extra_sources or extra_sources_only
    if include_extra_sources and not storage_only:
        raise ValueError("full-scope sizing requires storage-only mode")
    encode = _encoder()
    seen_chunks: set[bytes] = set()
    totals = {
        "transcripts": 0,
        "raw_transcript_bytes": 0,
        "unique_chunks": 0,
        "duplicate_chunks": 0,
        "empty_vault_object_bytes": 0,
        "readable_text_bytes": 0,
        "readable_text_gzip_bytes": 0,
        "readable_record_source_bytes": 0,
        "unreadable_or_oversized_records": 0,
        "unreadable_or_oversized_bytes": 0,
        "skipped_recent_transcripts": 0,
        "skipped_recent_bytes": 0,
        "attachments": 0,
        "raw_attachment_bytes": 0,
        "paginated_threads": 0,
        "raw_paginated_bytes": 0,
        "paginated_source_changed": False,
    }

    def count_chunk(chunk: bytes) -> None:
        digest = hashlib.sha256(chunk).digest()
        if digest in seen_chunks:
            totals["duplicate_chunks"] += 1
        else:
            seen_chunks.add(digest)
            stored, _ = _encoded_size(chunk, encode)
            totals["empty_vault_object_bytes"] += stored + AES_GCM_OVERHEAD
            totals["unique_chunks"] += 1

    text_compressor = None if storage_only else zlib.compressobj(level=6, wbits=31)
    recent_cutoff_ns = time.time_ns() - exclude_recent_seconds * 1_000_000_000
    for _, path, _ in ([] if extra_sources_only else _transcripts(source_home)):
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("a transcript is not a regular file")
        if exclude_recent_seconds and before.st_mtime_ns >= recent_cutoff_ns:
            totals["skipped_recent_transcripts"] += 1
            totals["skipped_recent_bytes"] += before.st_size
            continue
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino, opened.st_size) != (
                    before.st_dev, before.st_ino, before.st_size):
                raise ValueError("a transcript changed before sizing")
            pending = b""
            skipping = 0
            observed = 0
            while True:
                chunk = stream.read(CHUNK_SIZE)
                if not chunk:
                    break
                observed += len(chunk)
                count_chunk(chunk)
                if storage_only:
                    continue
                if skipping:
                    end = chunk.find(b"\n")
                    if end < 0:
                        skipping += len(chunk)
                        continue
                    skipping += end + 1
                    totals["unreadable_or_oversized_records"] += 1
                    totals["unreadable_or_oversized_bytes"] += skipping
                    skipping = 0
                    chunk = chunk[end + 1:]
                records = (pending + chunk).split(b"\n")
                pending = records.pop()
                if len(pending) > MAX_RECORD_BYTES:
                    skipping = len(pending)
                    pending = b""
                for raw in records:
                    if len(raw) + 1 > MAX_RECORD_BYTES:
                        totals["unreadable_or_oversized_records"] += 1
                        totals["unreadable_or_oversized_bytes"] += len(raw) + 1
                        continue
                    try:
                        text = _record_text(raw)
                    except ValueError:
                        totals["unreadable_or_oversized_records"] += 1
                        totals["unreadable_or_oversized_bytes"] += len(raw) + 1
                        continue
                    totals["readable_record_source_bytes"] += len(raw) + 1
                    totals["readable_text_bytes"] += len(text)
                    totals["readable_text_gzip_bytes"] += len(text_compressor.compress(text))
            if not storage_only and skipping:
                totals["unreadable_or_oversized_records"] += 1
                totals["unreadable_or_oversized_bytes"] += skipping
            elif not storage_only and pending:
                try:
                    text = _record_text(pending)
                except ValueError:
                    totals["unreadable_or_oversized_records"] += 1
                    totals["unreadable_or_oversized_bytes"] += len(pending)
                else:
                    totals["readable_record_source_bytes"] += len(pending)
                    totals["readable_text_bytes"] += len(text)
                    totals["readable_text_gzip_bytes"] += len(text_compressor.compress(text))
            after = os.fstat(stream.fileno())
            if observed != before.st_size or (
                before.st_dev, before.st_ino, before.st_size,
                before.st_mtime_ns, before.st_ctime_ns,
            ) != (
                after.st_dev, after.st_ino, after.st_size,
                after.st_mtime_ns, after.st_ctime_ns,
            ):
                raise ValueError("a transcript changed while being sized")
        totals["raw_transcript_bytes"] += observed
        totals["transcripts"] += 1
    if include_extra_sources:
        for _, path, _ in attachment_files(source_home):
            before = path.lstat()
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as stream:
                opened = os.fstat(stream.fileno())
                if (opened.st_dev, opened.st_ino, opened.st_size) != (
                        before.st_dev, before.st_ino, before.st_size):
                    raise ValueError("an attachment changed before sizing")
                observed = 0
                while True:
                    chunk = stream.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    observed += len(chunk)
                    count_chunk(chunk)
                after = os.fstat(stream.fileno())
                if observed != before.st_size or (
                        before.st_dev, before.st_ino, before.st_size,
                        before.st_mtime_ns, before.st_ctime_ns,
                ) != (
                        after.st_dev, after.st_ino, after.st_size,
                        after.st_mtime_ns, after.st_ctime_ns,
                ):
                    raise ValueError("an attachment changed while being sized")
            totals["raw_attachment_bytes"] += observed
            totals["attachments"] += 1

        database_before = source_fingerprint(source_home)
        if database_before is not None:
            # The sandboxed reader is a fresh Python process. The operator
            # script must make this checkout's source package visible to it.
            prior_pythonpath = os.environ.get("PYTHONPATH")
            os.environ["PYTHONPATH"] = str(ROOT / "src") + (
                os.pathsep + prior_pythonpath if prior_pythonpath else "")
            try:
                with open_paginated_source(source_home) as source:
                    for thread_id in source.thread_ids():
                        pending = bytearray()
                        observed = 0
                        for item in source.items(thread_id):
                            record = encoded_item(item)
                            observed += len(record)
                            remaining = memoryview(record)
                            while remaining:
                                count = min(CHUNK_SIZE - len(pending), len(remaining))
                                pending.extend(remaining[:count])
                                remaining = remaining[count:]
                                if len(pending) == CHUNK_SIZE:
                                    count_chunk(bytes(pending))
                                    pending.clear()
                        if not observed:
                            raise ValueError("a paginated thread changed while being sized")
                        if pending:
                            count_chunk(bytes(pending))
                        totals["raw_paginated_bytes"] += observed
                        totals["paginated_threads"] += 1
            finally:
                if prior_pythonpath is None:
                    os.environ.pop("PYTHONPATH", None)
                else:
                    os.environ["PYTHONPATH"] = prior_pythonpath
            totals["paginated_source_changed"] = (
                source_fingerprint(source_home) != database_before)
    if text_compressor is not None:
        totals["readable_text_gzip_bytes"] += len(text_compressor.flush())
    totals["readable_text_estimate_complete"] = (
        not storage_only
        and totals["unreadable_or_oversized_records"] == 0
        and totals["skipped_recent_transcripts"] == 0
    )
    totals["estimate_complete"] = (totals["skipped_recent_transcripts"] == 0
                                    and not totals["paginated_source_changed"])
    totals["scope"] = (
        "Codex attachments and paginated history only"
        if extra_sources_only else
        "active and archived JSONL transcripts, Codex attachments, and paginated history"
        if include_extra_sources else
        "active and archived JSONL transcripts only"
    )
    totals["object_size_warning"] = (
        "Encrypted objects in an empty Vault; excludes manifests, refs, and file-system overhead."
    )
    totals["readable_text_warning"] = (
        "Not computed in storage-only mode."
        if storage_only else
        "Gzipped recognized text is a hypothetical reading copy, not a restorable backup."
    )
    totals["storage_only"] = storage_only
    totals["include_extra_sources"] = include_extra_sources
    totals["extra_sources_only"] = extra_sources_only
    return totals


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-home", required=True,
                        help="explicit Mac home directory; never printed")
    parser.add_argument("--exclude-recent-seconds", type=int, default=0,
                        help="omit recently modified transcripts and report their aggregate bytes")
    parser.add_argument("--storage-only", action="store_true",
                        help="skip readable-text estimation while preserving exact object sizing")
    parser.add_argument("--include-extra-sources", action="store_true",
                        help="with --storage-only, include Codex attachments and paginated history")
    parser.add_argument("--extra-sources-only", action="store_true",
                        help="with --storage-only, size only attachments and paginated history")
    args = parser.parse_args()
    try:
        if args.exclude_recent_seconds < 0:
            raise ValueError("recent exclusion must be nonnegative")
        print(json.dumps(estimate(args.source_home, args.exclude_recent_seconds,
                                  storage_only=args.storage_only,
                                  include_extra_sources=args.include_extra_sources,
                                  extra_sources_only=args.extra_sources_only),
                         sort_keys=True))
    except Exception as error:
        # No transcript path, text, or hash may escape through an exception.
        print("Sizing stopped safely (%s); no aggregate was produced." %
              type(error).__name__, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
