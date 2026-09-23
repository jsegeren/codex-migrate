"""Disposable PreCompact probe; records metadata only, never transcript text."""

import hashlib
import json
import os
from pathlib import Path
import sys


def main():
    event = json.load(sys.stdin)
    if event.get("hook_event_name") != "PreCompact":
        raise ValueError("unexpected hook event")
    path = event.get("transcript_path")
    size = digest = None
    if isinstance(path, str) and path:
        handle = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            file_hash = hashlib.sha256()
            size = 0
            with os.fdopen(handle, "rb", closefd=False) as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    size += len(chunk)
                    file_hash.update(chunk)
            digest = file_hash.hexdigest()
        finally:
            os.close(handle)
    receipt = {
        "event": "PreCompact",
        "session_id": event.get("session_id"),
        "trigger": event.get("trigger"),
        "transcript_present": isinstance(path, str) and bool(path),
        "transcript_size": size,
        "transcript_sha256": digest,
    }
    receipt_path = Path(os.environ["VAULT_PROBE_RECEIPT"])
    descriptor = os.open(receipt_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(receipt, output, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    print(json.dumps({"continue": os.environ.get("VAULT_PROBE_STOP") != "1",
                      "stopReason": "Disposable compaction was stopped by a test hook."}))


if __name__ == "__main__":
    main()
