"""Codex transfer exclusions shared by copying and dependency coverage checks."""

import fnmatch
from pathlib import Path


CODEX_EXCLUDES = (
    "/auth.json", "/installation_id", "/ipc/", "/thread-writer-locks/",
    "/process_manager/", "/mcp-oauth-locks/", "/logs/", "/logs_*.sqlite*",
    "/sqlite/logs_*.sqlite*", "/.tmp/", "/tmp/", "/cache/", "/caches/",
    "/packages/", "/standalone/", "/node_repl/", "/fsmonitor--daemon.ipc",
    "/*.sock", "/*.socket", "/.DS_Store", "/..codex-global-state.json.tmp-*",
)


def codex_path_excluded(relative: Path) -> bool:
    # Match the same root-anchored paths as rsync. Never apply runtime names
    # such as "cache" or "logs" inside complete workspaces or Git metadata.
    for pattern in CODEX_EXCLUDES:
        components = pattern.strip("/").split("/")
        if len(relative.parts) >= len(components) and all(
                fnmatch.fnmatchcase(part, component)
                for part, component in zip(relative.parts, components)):
            return True
    return False
