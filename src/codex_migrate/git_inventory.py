"""Read-only Git storage dependency inventory. Never runs Git or reads objects."""

from dataclasses import dataclass, field
import os
from pathlib import Path
import stat
from typing import Callable, Dict, List

from codex_migrate.exclusions import codex_path_excluded
from codex_migrate.source_availability import require_local, walk_local


@dataclass
class GitReport:
    repositories: List[Dict[str, object]] = field(default_factory=list)
    missing_paths: List[str] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def inspect_git(source_home: str, workspace_roots: List[str], checkpoint: Callable[[], None]) -> GitReport:
    home = Path(source_home).resolve()
    roots = [Path(path).resolve() for path in workspace_roots]
    codex = home / ".codex"
    report = GitReport()
    missing = set()
    seen_repositories = set()
    seen_metadata = set()
    seen_objects = set()
    seen_link_trees = set()
    seen_link_paths = set()

    def inside(path, root):
        return path == root or root in path.parents

    def resolve(path):
        checkpoint()
        try:
            resolved = path.resolve()
        except (OSError, RuntimeError):
            report.issues.append("Cannot resolve Git metadata path: %s" % path)
            return None
        if not inside(resolved, home):
            report.issues.append("Git dependency is outside the supported source home: %s" % path)
            return None
        preserve_links(path)
        return resolved

    def preserve_links(path):
        # A -> B -> C needs B as well as C: the copied link still names B.
        # Also inspect ancestor aliases used by gitfiles and alternates.
        if path in seen_link_paths:
            return
        seen_link_paths.add(path)
        for entry in list(reversed(path.parents)) + [path]:
            checkpoint()
            if not entry.is_symlink():
                continue
            try:
                parent = entry.parent.resolve()
                if not inside(parent, home):
                    report.issues.append("Git dependency uses an alias outside the supported source home: %s" % entry)
                    continue
                require(parent)
                value = Path(os.readlink(entry))
                target = value if value.is_absolute() else entry.parent / value
                preserve_links(target)
            except (OSError, RuntimeError):
                report.issues.append("Cannot inspect Git dependency alias: %s" % entry)

    def covered(path):
        if any(inside(path, root) for root in roots):
            return True
        return inside(path, codex) and not codex_path_excluded(path.relative_to(codex))

    def require(path):
        if not covered(path):
            # Selecting the main checkout preserves its working files as well
            # as shared history; do not suggest copying only its .git folder.
            missing.add(str(path.parent if path.name == ".git" or path.is_file() else path))

    def metadata_links(root):
        # Git can use symlinks for refs, HEAD, index, object files, or whole
        # metadata subtrees. rsync preserves links, not their external targets.
        # Walk names only; never read object/index contents or run Git hooks.
        if root in seen_link_trees or not root.is_dir():
            return
        seen_link_trees.add(root)
        for current, directories, files in walk_local(root, onerror=unreadable):
            checkpoint()
            for name in directories + files:
                checkpoint()
                link = Path(current) / name
                if not link.is_symlink():
                    continue
                target = resolve(link)
                if target is None:
                    continue
                if not target.exists():
                    report.issues.append("Git metadata link target is missing: %s" % link)
                    continue
                require(target)
                metadata_links(target)

    def pointer(path, allow_empty=False):
        checkpoint()
        require_local(path)
        try:
            if path.parent.resolve() != path.parent:
                raise ValueError("Pointer has a symbolic-link parent")
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > 65536:
                    raise ValueError("Unsupported pointer")
                raw = stream.read(65537)
            if len(raw) > 65536:
                raise ValueError("Pointer grew")
            value = raw.decode("utf-8").removesuffix("\n")
            if (not value and not allow_empty) or "\x00" in value or "\r" in value:
                raise ValueError("Invalid pointer")
            return value
        except (OSError, ValueError, UnicodeError):
            report.issues.append("Unreadable or unsupported Git pointer: %s" % path)
            return None

    def location(value, base):
        if "\n" in value or value.startswith('"'):
            report.issues.append("Unsupported quoted or multiline Git dependency beneath: %s" % base)
            return None
        return resolve(Path(value) if Path(value).is_absolute() else base / value)

    def objects(path):
        path = resolve(path)
        if path is None or path in seen_objects:
            return
        seen_objects.add(path)
        require(path)
        if not path.is_dir():
            report.issues.append("Git object storage is missing: %s" % path)
            return
        metadata_links(path)
        alternate_file = path / "info/alternates"
        if alternate_file.exists() or alternate_file.is_symlink():
            value = pointer(alternate_file, allow_empty=True)
            if value is not None:
                for line in value.split("\n"):
                    if not line:
                        continue
                    alternate = location(line, path)
                    if alternate is not None:
                        objects(alternate)

    def metadata(path):
        path = resolve(path)
        if path is None or path in seen_metadata:
            return
        seen_metadata.add(path)
        require(path)
        if not path.is_dir():
            report.issues.append("Git metadata directory is missing: %s" % path)
            return
        metadata_links(path)
        if not (path / "HEAD").is_file():
            report.issues.append("Git metadata has no readable HEAD file: %s" % path)
        common_file = path / "commondir"
        if common_file.exists() or common_file.is_symlink():
            value = pointer(common_file)
            common = location(value, path) if value is not None else None
            if common == path:
                report.issues.append("Git common directory points to itself: %s" % path)
            elif common is not None:
                metadata(common)
        else:
            objects(path / "objects")
        registrations = path / "worktrees"
        if registrations.exists() or registrations.is_symlink():
            if registrations.is_symlink() or not registrations.is_dir():
                report.issues.append("Unsupported Git worktree registrations: %s" % registrations)
                return
            try:
                require_local(registrations)
                entries = list(registrations.iterdir())
            except OSError:
                report.issues.append("Cannot read Git worktree registrations: %s" % registrations)
                return
            for entry in entries:
                checkpoint()
                if entry.is_symlink() or not entry.is_dir():
                    report.issues.append("Unsupported Git worktree registration: %s" % entry)
                    continue
                value = pointer(entry / "gitdir")
                gitfile = location(value, entry) if value is not None else None
                if gitfile is not None:
                    worktree = gitfile.parent
                    if not worktree.is_dir():
                        report.warnings.append("Registered worktree is already absent on the source: %s" % worktree)
                    else:
                        require(worktree)

    def repository(path, marker=None):
        if path in seen_repositories:
            return
        seen_repositories.add(path)
        kind = "storage" if marker is None else "checkout"
        gitdir = path
        if marker is not None:
            if marker.is_symlink():
                gitdir = resolve(marker)
            elif marker.is_dir():
                gitdir = marker
            else:
                kind = "linked"
                value = pointer(marker)
                if value is None:
                    return
                if not value.startswith("gitdir: "):
                    report.issues.append("Invalid Git directory pointer: %s" % marker)
                    return
                gitdir = location(value[len("gitdir: "):], path)
        if gitdir is None:
            return
        report.repositories.append({"path": str(path), "git_dir": str(gitdir), "kind": kind})
        metadata(gitdir)

    def unreadable(error):
        report.issues.append("Git discovery could not read a selected directory: %s" % error.filename)

    managed = codex / "worktrees"
    scan_roots = roots + ([managed] if managed.exists() or managed.is_symlink() else [])
    for root in scan_roots:
        if not inside(root, home):
            report.issues.append("Git discovery root is outside the supported source home: %s" % root)
            continue
        if root.is_symlink():
            report.issues.append("Git discovery root is a symbolic link: %s" % root)
            continue
        for current, directories, files in walk_local(root, onerror=unreadable):
            checkpoint()
            path = Path(current)
            if inside(path, codex) and codex_path_excluded(path.relative_to(codex)):
                directories[:] = []
                continue
            if ".git" in directories or ".git" in files:
                repository(path, path / ".git")
                directories[:] = [name for name in directories if name != ".git"]
            elif "HEAD" in files and "objects" in directories and "refs" in directories:
                repository(path)
                directories[:] = []
    report.repositories.sort(key=lambda item: item["path"])
    report.missing_paths = sorted(path for path in missing
                                  if not any(inside(Path(path), Path(other))
                                             for other in missing if other != path))
    return report
