"""Read-only, authenticated discovery across dated Vault snapshots."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from codex_migrate.vault_recovery import list_snapshots, snapshot_catalog


def _group_key(file: Dict[str, object]) -> str:
    thread_id = file.get("thread_id")
    if file.get("identity_state") == "verified" and isinstance(thread_id, str):
        return "id:" + thread_id
    # Conflicted or missing IDs must never be merged on title alone.
    return "path:" + str(file["collection"]) + "/" + str(file["path"])


def _versions(vault: str, *, crypto_helper: Optional[str] = None) -> List[Dict[str, object]]:
    versions: List[Dict[str, object]] = []
    for snapshot in list_snapshots(vault, limit=1000):
        for file in snapshot_catalog(
                vault, snapshot=snapshot.snapshot_id, crypto_helper=crypto_helper):
            versions.append({
                "key": _group_key(file),
                "snapshot_id": snapshot.snapshot_id,
                "created_at": snapshot.created_at,
                "collection": file["collection"],
                "transcript": file["path"],
                "thread_id": file["thread_id"],
                "identity_state": file["identity_state"],
                "titles": file["titles"],
                "sha256": file["sha256"],
                "size": file["size"],
                "records": file["records"],
                "assistant_messages": file["assistant_messages"],
                "at_risk": file["at_risk"],
            })
    return versions


def search_titles(
    vault: str, query: str, *, limit: int = 50,
    crypto_helper: Optional[str] = None,
) -> List[Dict[str, object]]:
    needle = query.strip().casefold()
    if not needle:
        raise ValueError("search query must not be empty")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
        raise ValueError("search limit must be between 1 and 100")
    grouped: Dict[str, Dict[str, object]] = {}
    for version in _versions(vault, crypto_helper=crypto_helper):
        key = str(version["key"])
        group = grouped.get(key)
        if group is None:
            group = {**version, "title_history": [], "version_count": 0,
                     "matching_snapshot": None, "_signatures": set()}
            grouped[key] = group
        titles = version["titles"]
        if isinstance(titles, list):
            for title in titles:
                if title not in group["title_history"]:
                    group["title_history"].append(title)
                if needle in title.casefold() and group["matching_snapshot"] is None:
                    group["matching_snapshot"] = version["snapshot_id"]
                    group["matching_title"] = title
                    group["matching_collection"] = version["collection"]
                    group["matching_transcript"] = version["transcript"]
        signature = (str(version["sha256"]), tuple(version["titles"]))
        if signature not in group["_signatures"]:
            group["_signatures"].add(signature)
            group["version_count"] += 1
    found = [group for group in grouped.values() if group["matching_snapshot"]]
    for group in found:
        del group["_signatures"]
    return found[:limit]


def thread_timeline(
    vault: str, key: str, *, crypto_helper: Optional[str] = None,
) -> List[Dict[str, object]]:
    if not isinstance(key, str) or not key or len(key) > 4096 \
            or not (key.startswith("id:") or key.startswith("path:")):
        raise ValueError("invalid Vault thread identity")
    versions = [version for version in _versions(vault, crypto_helper=crypto_helper)
                if version["key"] == key]
    timeline = []
    seen: set[Tuple[str, Tuple[str, ...]]] = set()
    for version in versions:
        signature = (str(version["sha256"]), tuple(version["titles"]))
        if signature in seen:
            continue
        seen.add(signature)
        timeline.append(version)
    return timeline
