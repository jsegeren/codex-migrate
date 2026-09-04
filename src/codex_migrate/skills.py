"""Shared, home-confined custom-skill discovery for full and selective migration."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
import hashlib
from pathlib import Path
import re
import shlex
import stat
from typing import Dict, Iterable, List, Sequence

from codex_migrate.errors import MigrationError
from codex_migrate.config import path_key
from codex_migrate.filename_safety import check_names


SKILL_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True)
class SkillExport:
    name: str
    source: str
    destination: str
    scope: str

    def as_dict(self) -> Dict[str, str]:
        return asdict(self)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _validated_skill(path: Path, source_home: Path) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except (FileNotFoundError, RuntimeError) as error:
        raise MigrationError("Skill path is missing or has a broken symbolic link: %s" % path) from error
    if not _inside(resolved, source_home):
        raise MigrationError("Skill path resolves outside the source home: %s" % path)
    if not resolved.is_dir() or not (resolved / "SKILL.md").is_file():
        raise MigrationError("Skill is missing a regular SKILL.md file: %s" % path)
    ssh = source_home / ".ssh"
    protected_ssh = (path_key(str(ssh)), path_key(str(ssh.resolve())))
    protected_files = set()
    protected_inodes = set()
    for name in (".codex/auth.json", ".codex/installation_id"):
        path = source_home / name
        protected_files.update((path_key(str(path)), path_key(str(path.resolve()))))
        try:
            info = path.stat()
        except FileNotFoundError:
            continue
        # Metadata only: never open or hash protected credentials, including
        # when a hard link disguises one as a skill file.
        protected_inodes.add((info.st_dev, info.st_ino))
    def unreadable(error):
        raise error
    for current, directories, files in os.walk(str(resolved), followlinks=False, onerror=unreadable):
        check_names(directories + files)
        for name in directories + files:
            candidate = Path(current) / name
            try:
                target = candidate.resolve(strict=True)
            except (FileNotFoundError, RuntimeError) as error:
                raise MigrationError("Skill contains a broken symbolic link: %s" % candidate) from error
            key = path_key(str(target))
            info = target.stat()
            if (any(key[:len(root)] == root for root in protected_ssh)
                    or key in protected_files or (info.st_dev, info.st_ino) in protected_inodes):
                raise MigrationError("Skill references protected authentication material")
            if not (target.is_dir() or stat.S_ISREG(target.stat().st_mode)):
                raise MigrationError("Skill contains an unsupported special file: %s" % candidate)
            if not candidate.is_symlink():
                continue
            if not _inside(target, source_home):
                raise MigrationError(
                    "Skill contains a symbolic link outside the source home: %s" % candidate
                )
            if target.is_dir():
                raise MigrationError(
                    "Nested directory symlinks are not supported in exported skills: %s"
                    % candidate
                )
    return resolved


def skill_verification_script(skill: SkillExport, source_home: str) -> str:
    """Verify a materialized skill's exact regular-file bytes and directory tree.

    No contents or checksum values are printed. The same frozen script is used
    against staging and installed data within the backup/rollback transaction.
    """
    root = _validated_skill(Path(skill.source), Path(source_home).resolve())
    checks = []
    file_count = 0
    directory_count = 0
    def unreadable(error):
        raise error
    for current, directories, files in os.walk(str(root), onerror=unreadable):
        directory_count += 1
        relative = Path(current).relative_to(root)
        checks.append('test -d "$1"/%s' % shlex.quote(str(relative)))
        for name in sorted(files):
            path = Path(current) / name
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            target = '"$1"/' + shlex.quote(str(relative / name))
            checks.append("test -f %s" % target)
            checks.append("test \"$(/usr/bin/shasum -a 256 -- %s | /usr/bin/awk '{print $1}')\" = %s"
                          % (target, shlex.quote(digest.hexdigest())))
            file_count += 1
    target = '"$1"'
    checks.insert(0, "test ! -L %s" % target)
    for kind, count in (("f", file_count), ("d", directory_count), ("l", 0)):
        checks.append("test \"$(/usr/bin/find %s -type %s | /usr/bin/wc -l | /usr/bin/tr -d ' ')\" = %d"
                      % (target, kind, count))
    checks.append("test \"$(/usr/bin/find %s | /usr/bin/wc -l | /usr/bin/tr -d ' ')\" = %d"
                  % (target, file_count + directory_count))
    # zsh ERR_EXIT inside a function bypasses the caller's EXIT rollback trap.
    # Return explicitly and let the top-level caller exit under that trap.
    return "\n".join(check + " || return 74" for check in checks)


def discover_personal_skills(source_home: str, target_home: str) -> List[SkillExport]:
    """Discover user-wide skills, preferring the current documented root."""
    source = Path(source_home).resolve()
    selected: Dict[str, SkillExport] = {}
    roots = (
        (source / ".codex/skills", "legacy-user"),
        (source / ".agents/skills", "user"),
    )
    for root, scope in roots:
        if not root.exists() and not root.is_symlink():
            continue
        resolved_root = root.resolve(strict=True)
        if not _inside(resolved_root, source):
            raise MigrationError("Skill root resolves outside the source home: %s" % root)
        if not resolved_root.is_dir():
            raise MigrationError("Skill root is not a directory: %s" % root)
        for candidate in sorted(resolved_root.iterdir(), key=lambda item: item.name):
            if not _skill_candidate(candidate):
                continue
            resolved = _validated_skill(candidate, source)
            if any(name != candidate.name and name.casefold() == candidate.name.casefold() for name in selected):
                raise MigrationError("Skill names differ only by capitalization; resolve the ambiguous selection before transfer")
            selected[candidate.name] = SkillExport(
                name=candidate.name,
                source=str(resolved),
                destination=str(Path(target_home) / ".agents/skills" / candidate.name),
                scope=scope,
            )
    return [selected[name] for name in sorted(selected)]


def _skill_candidate(candidate: Path) -> bool:
    if candidate.name.casefold() == ".system":
        return False
    if not candidate.is_dir() and not candidate.is_symlink():
        return False
    if not SKILL_NAME.fullmatch(candidate.name):
        raise MigrationError(
            "Unsupported skill directory name: %s. Use letters, numbers, dots, "
            "underscores or hyphens before migrating; the skill was not silently skipped."
            % candidate
        )
    return True


def _walk_workspace_skill_dirs(root: Path) -> Iterable[Path]:
    ignored = {".git", "node_modules", ".next", "dist", "build", "coverage"}
    for current, directories, _files in os.walk(str(root), followlinks=False):
        directories[:] = [name for name in directories if name not in ignored]
        current_path = Path(current)
        if current_path.name == "skills" and current_path.parent.name == ".agents":
            for candidate in sorted(current_path.iterdir(), key=lambda item: item.name):
                if _skill_candidate(candidate):
                    yield candidate
            directories[:] = []


def discover_workspace_skills(
    source_home: str,
    target_home: str,
    workspace_roots: Sequence[str],
) -> List[SkillExport]:
    source = Path(source_home).resolve()
    exports: List[SkillExport] = []
    seen = set()
    for workspace in workspace_roots:
        root = Path(workspace).resolve()
        for candidate in _walk_workspace_skill_dirs(root):
            if not candidate.is_dir() and not candidate.is_symlink():
                continue
            resolved = _validated_skill(candidate, source)
            relative = candidate.relative_to(source)
            destination = str(Path(target_home) / relative)
            if destination in seen:
                continue
            seen.add(destination)
            exports.append(
                SkillExport(
                    name=candidate.name,
                    source=str(resolved),
                    destination=destination,
                    scope="workspace",
                )
            )
    return sorted(exports, key=lambda item: item.destination)
