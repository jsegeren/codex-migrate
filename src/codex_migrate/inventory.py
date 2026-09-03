"""Bounded, content-free inventory of local Codex state and workspaces."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path
import platform
import subprocess
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class TreeSummary:
    path: str
    files: int
    bytes: int
    readable: bool


@dataclass(frozen=True)
class Inventory:
    platform: str
    source_home: str
    codex_present: bool
    active_sessions: TreeSummary
    archived_sessions: TreeSummary
    codex_bytes: int
    workspace_roots: List[TreeSummary]
    git_repositories: int
    unreadable_paths: List[str]

    @property
    def estimated_transfer_bytes(self) -> int:
        return self.codex_bytes + sum(item.bytes for item in self.workspace_roots)

    def as_dict(self) -> Dict[str, object]:
        value = asdict(self)
        value["estimated_transfer_bytes"] = self.estimated_transfer_bytes
        return value


def _tree_summary(
    root: Path,
    counted_suffix: str = "",
) -> Tuple[TreeSummary, List[str]]:
    if not root.exists():
        return TreeSummary(str(root), 0, 0, False), []
    files = 0
    total = 0
    unreadable: List[str] = []
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(str(current)) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            if not counted_suffix or entry.name.endswith(counted_suffix):
                                files += 1
                            total += entry.stat(follow_symlinks=False).st_size
                        elif entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            if not counted_suffix or entry.name.endswith(counted_suffix):
                                files += 1
                            total += entry.stat(follow_symlinks=False).st_size
                    except (OSError, PermissionError):
                        unreadable.append(entry.path)
        except (OSError, PermissionError):
            unreadable.append(str(current))
    return TreeSummary(str(root), files, total, not unreadable), unreadable


def _disk_usage(path: Path) -> int:
    if not path.exists():
        return 0
    result = subprocess.run(
        ["/usr/bin/du", "-sk", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        timeout=300,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return 0
    return int(result.stdout.split()[0]) * 1024


def _count_git_repositories(roots: List[Path]) -> int:
    repositories = 0
    ignored = {
        "node_modules",
        ".next",
        ".cache",
        "Library",
        "Applications",
        "dist",
        "build",
        "coverage",
    }
    for root in roots:
        if not root.is_dir():
            continue
        for current, directories, files in os.walk(str(root), followlinks=False):
            directories[:] = [item for item in directories if item not in ignored]
            if ".git" in directories or ".git" in files:
                repositories += 1
                if ".git" in directories:
                    directories.remove(".git")
    return repositories


def collect(source_home: str, workspace_roots: List[str]) -> Inventory:
    home = Path(source_home)
    codex = home / ".codex"
    active, active_unreadable = _tree_summary(codex / "sessions", ".jsonl")
    archived, archived_unreadable = _tree_summary(codex / "archived_sessions", ".jsonl")
    roots = [Path(item) for item in workspace_roots]
    root_summaries: List[TreeSummary] = []
    unreadable = active_unreadable + archived_unreadable
    for root in roots:
        summary, root_unreadable = _tree_summary(root)
        summary = TreeSummary(summary.path, summary.files, _disk_usage(root), summary.readable)
        root_summaries.append(summary)
        unreadable.extend(root_unreadable)
    return Inventory(
        platform=platform.system(),
        source_home=str(home),
        codex_present=codex.is_dir(),
        active_sessions=active,
        archived_sessions=archived,
        codex_bytes=_disk_usage(codex),
        workspace_roots=root_summaries,
        git_repositories=_count_git_repositories(roots),
        unreadable_paths=unreadable[:100],
    )
