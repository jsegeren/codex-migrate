"""Bounded local inventory with storage screening and content-free reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import os
from pathlib import Path
import platform
import subprocess
import time
from typing import Callable, Dict, List, Tuple
from codex_migrate.transport import _stop_process
from codex_migrate.skills import SkillExport, discover_personal_skills
from codex_migrate.git_inventory import inspect_git
from codex_migrate.storage_scope import require_source_storage
from codex_migrate.filename_safety import check_name, check_tree_names


def _continue() -> None:
    pass


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
    personal_skills: List[SkillExport] = field(default_factory=list)
    personal_skill_bytes: int = 0
    git_details: List[Dict[str, object]] = field(default_factory=list)
    git_missing_paths: List[str] = field(default_factory=list)
    git_issues: List[str] = field(default_factory=list)
    git_warnings: List[str] = field(default_factory=list)

    @property
    def estimated_transfer_bytes(self) -> int:
        return (self.codex_bytes + self.personal_skill_bytes
                + sum(item.bytes for item in self.workspace_roots))

    def as_dict(self) -> Dict[str, object]:
        value = asdict(self)
        value["estimated_transfer_bytes"] = self.estimated_transfer_bytes
        return value


def _tree_summary(
    root: Path,
    counted_suffix: str = "",
    checkpoint: Callable[[], None] = _continue,
) -> Tuple[TreeSummary, List[str]]:
    if not root.exists():
        return TreeSummary(str(root), 0, 0, False), []
    files = 0
    total = 0
    unreadable: List[str] = []
    stack = [root]
    while stack:
        checkpoint()
        current = stack.pop()
        try:
            seen = set()
            with os.scandir(str(current)) as entries:
                for entry in entries:
                    checkpoint()
                    check_name(entry.name, seen)
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


def _disk_usage(path: Path, checkpoint: Callable[[], None] = _continue) -> int:
    checkpoint()
    if not path.exists():
        return 0
    process = subprocess.Popen(
        ["/usr/bin/du", "-sk", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        start_new_session=True,
    )
    started = time.monotonic()
    try:
        while True:
            checkpoint()
            try:
                output, _ = process.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                if time.monotonic() - started >= 300:
                    raise
    except BaseException:
        _stop_process(process)
        raise
    if process.returncode != 0 or not output.strip():
        return 0
    return int(output.split()[0]) * 1024


def collect(source_home: str, workspace_roots: List[str],
            checkpoint: Callable[[], None] = _continue,
            target_home: str = "") -> Inventory:
    home = Path(source_home)
    require_source_storage(str(home), checkpoint)
    skills = discover_personal_skills(source_home, target_home or source_home)
    skill_bytes = 0
    def unreadable_skill(error):
        raise error
    for skill in skills:
        for current, directories, files in os.walk(skill.source, onerror=unreadable_skill):
            checkpoint()
            skill_bytes += 4096 * (1 + len(directories))
            for name in files:
                checkpoint()
                info = (Path(current) / name).stat()
                skill_bytes += max(info.st_size, info.st_blocks * 512)
    codex = home / ".codex"
    if codex.exists():
        check_tree_names(codex, checkpoint, codex=True)
    active, active_unreadable = _tree_summary(codex / "sessions", ".jsonl", checkpoint)
    archived, archived_unreadable = _tree_summary(codex / "archived_sessions", ".jsonl", checkpoint)
    roots = [Path(item) for item in workspace_roots]
    root_summaries: List[TreeSummary] = []
    unreadable = active_unreadable + archived_unreadable
    for root in roots:
        summary, root_unreadable = _tree_summary(root, checkpoint=checkpoint)
        summary = TreeSummary(summary.path, summary.files, _disk_usage(root, checkpoint), summary.readable)
        root_summaries.append(summary)
        unreadable.extend(root_unreadable)
    git = inspect_git(source_home, workspace_roots, checkpoint)
    return Inventory(
        platform=platform.system(),
        source_home=str(home),
        codex_present=codex.is_dir(),
        active_sessions=active,
        archived_sessions=archived,
        codex_bytes=_disk_usage(codex, checkpoint),
        workspace_roots=root_summaries,
        git_repositories=len(git.repositories),
        unreadable_paths=unreadable[:100],
        personal_skills=skills,
        personal_skill_bytes=skill_bytes,
        git_details=git.repositories,
        git_missing_paths=git.missing_paths,
        git_issues=git.issues,
        git_warnings=git.warnings,
    )
