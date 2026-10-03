"""Shared source-loss decisions for hosted staging and read-only review.

These comparisons never authorize publication, deletion, or a new baseline.
Their input is a decrypted authenticated prior catalog plus an inspected source.
"""

from collections import Counter
import re
from typing import Sequence


_HEX = re.compile(r"[0-9a-f]{64}\Z")


def missing_verified_threads(previous: Sequence[dict], current: Sequence[dict]) -> list:
    """Verified ID is identity; moving between history sources is not loss."""
    history = ("active", "archived", "paginated")
    before = {item.get("thread_id") for item in previous
              if item.get("collection") in history and
              item.get("identity_state") == "verified" and item.get("thread_id")}
    after = {item.get("thread_id") for item in current
             if item.get("collection") in history and
             item.get("identity_state") == "verified" and item.get("thread_id")}
    return sorted(before - after)


def missing_unidentified_transcripts(previous: Sequence[dict],
                                     current: Sequence[dict]) -> list:
    """Count identical-byte moves; never merge indistinguishable copies."""
    collections = ("active", "archived")
    before_paths = {(item.get("collection"), item.get("path"))
                    for item in previous if item.get("collection") in collections}
    now = {(item.get("collection"), item.get("path")) for item in current
           if item.get("collection") in collections}
    remaining = Counter(
        item.get("sha256") for item in current
        if item.get("collection") in collections and
           (item.get("collection"), item.get("path")) not in before_paths)
    missing = []
    for item in previous:
        if (item.get("collection") not in collections or
                item.get("identity_state") == "verified" or
                (item.get("collection"), item.get("path")) in now):
            continue
        digest = item.get("sha256")
        if not isinstance(digest, str) or not _HEX.fullmatch(digest) or not remaining[digest]:
            missing.append({"collection": item["collection"], "path": item["path"]})
        else:
            remaining[digest] -= 1
    return sorted(missing, key=lambda item: (item["collection"], item["path"]))


def _missing_verified_threads(previous: Sequence[dict], current: Sequence[dict]) -> bool:
    return bool(missing_verified_threads(previous, current))


def _missing_unidentified_transcripts(previous: Sequence[dict],
                                      current: Sequence[dict]) -> bool:
    return bool(missing_unidentified_transcripts(previous, current))
