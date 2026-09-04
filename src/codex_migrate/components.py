"""Selective, repeatable exports for small migration components."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import secrets
import shlex
import sys
from typing import Dict, Iterable, List, Sequence

from codex_migrate.config import MigrationConfig
from codex_migrate.cancellation import Cancellation
from codex_migrate.backup import (
    BACKUP_FUNCTIONS, MIN_RESERVE_BYTES, size_command, verification_receipt,
)
from codex_migrate.migration import MigrationEngine, MigrationError, _value
from codex_migrate.transport import SSHTransport


SUPPORTED_COMPONENTS = ("personal-skills", "workspace-skills")
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
    resolved = path.resolve(strict=True)
    if not _inside(resolved, source_home):
        raise MigrationError("Skill path resolves outside the source home: %s" % path)
    if not resolved.is_dir() or not (resolved / "SKILL.md").is_file():
        raise MigrationError("Skill is missing a regular SKILL.md file: %s" % path)
    for current, directories, files in os.walk(str(resolved), followlinks=False):
        for name in directories + files:
            candidate = Path(current) / name
            if not candidate.is_symlink():
                continue
            try:
                target = candidate.resolve(strict=True)
            except FileNotFoundError as error:
                raise MigrationError(
                    "Skill contains a broken symbolic link: %s" % candidate
                ) from error
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


def discover_personal_skills(source_home: str, target_home: str) -> List[SkillExport]:
    """Discover user-wide skills, preferring the current documented root."""
    source = Path(source_home).resolve()
    selected: Dict[str, SkillExport] = {}
    roots = (
        (source / ".codex/skills", "legacy-user"),
        (source / ".agents/skills", "user"),
    )
    for root, scope in roots:
        if not root.exists():
            continue
        resolved_root = root.resolve(strict=True)
        if not _inside(resolved_root, source):
            raise MigrationError("Skill root resolves outside the source home: %s" % root)
        if not resolved_root.is_dir():
            raise MigrationError("Skill root is not a directory: %s" % root)
        for candidate in sorted(resolved_root.iterdir(), key=lambda item: item.name):
            if candidate.name == ".system" or not SKILL_NAME.fullmatch(candidate.name):
                continue
            try:
                resolved = _validated_skill(candidate, source)
            except FileNotFoundError:
                continue
            selected[candidate.name] = SkillExport(
                name=candidate.name,
                source=str(resolved),
                destination=str(Path(target_home) / ".agents/skills" / candidate.name),
                scope=scope,
            )
    return [selected[name] for name in sorted(selected)]


def _walk_workspace_skill_dirs(root: Path) -> Iterable[Path]:
    ignored = {".git", "node_modules", ".next", "dist", "build", "coverage"}
    for current, directories, _files in os.walk(str(root), followlinks=False):
        directories[:] = [name for name in directories if name not in ignored]
        current_path = Path(current)
        if current_path.name == "skills" and current_path.parent.name == ".agents":
            for candidate in sorted(current_path.iterdir(), key=lambda item: item.name):
                if SKILL_NAME.fullmatch(candidate.name):
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
            try:
                resolved = _validated_skill(candidate, source)
            except FileNotFoundError:
                continue
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


class ComponentExporter:
    """Stage, back up, and install selected skill components over strict SSH."""

    def __init__(self, config: MigrationConfig, components: Sequence[str],
                 cancellation=None) -> None:
        self.cancellation = cancellation or Cancellation()
        self.config = config.validate()
        unknown = sorted(set(components) - set(SUPPORTED_COMPONENTS))
        if unknown:
            raise ValueError("unsupported components: %s" % ", ".join(unknown))
        self.components = tuple(dict.fromkeys(components))
        if not self.components:
            raise ValueError("select at least one component")
        self.transport = SSHTransport(self.config)

    def discover(self) -> List[SkillExport]:
        exports: List[SkillExport] = []
        if "personal-skills" in self.components:
            exports.extend(
                discover_personal_skills(self.config.source_home, self.config.target_home)
            )
        if "workspace-skills" in self.components:
            exports.extend(
                discover_workspace_skills(
                    self.config.source_home,
                    self.config.target_home,
                    self.config.workspace_roots,
                )
            )
        destinations = [item.destination for item in exports]
        if len(destinations) != len(set(destinations)):
            raise MigrationError("Selected components resolve to duplicate destinations")
        return exports

    def _preflight(self) -> None:
        remote = self.transport.check()
        expected_user = self.config.target.split("@", 1)[0]
        if _value(remote, "USER") != expected_user:
            raise MigrationError("SSH user does not match the configured destination user")
        if _value(remote, "HOME") != self.config.target_home:
            raise MigrationError("SSH home does not match the configured destination home")
        if _value(remote, "FILESYSTEM") != "apfs":
            raise MigrationError("The destination home must be on APFS for rollback backups")

    def run(self) -> Dict[str, object]:
        exports = self.discover()
        result: Dict[str, object] = {
            "components": list(self.components),
            "items": [item.as_dict() for item in exports],
            "item_count": len(exports),
            "applied": False,
        }
        if not self.config.apply:
            return result
        if not exports:
            raise MigrationError("No matching skill components were found")
        self._preflight()
        incoming_bytes = 0
        def unreadable(error):
            raise error
        for item in exports:
            for current, directories, files in os.walk(item.source, onerror=unreadable):
                incoming_bytes += 4096 * (1 + len(directories))
                for name in files:
                    info = (Path(current) / name).stat()
                    incoming_bytes += max(info.st_size, info.st_blocks * 512)
        self.transport.run_remote(
            "set -eu\n" + BACKUP_FUNCTIONS
            + "backup_required=$(%s)\nbackup_space %s \"$((backup_required + %d))\"\n"
            % (size_command([item.destination for item in exports]),
               shlex.quote(self.config.target_home), incoming_bytes + MIN_RESERVE_BYTES),
            timeout=300,
        )
        migration_id = secrets.token_hex(16)
        staging = str(
            Path(self.config.target_home)
            / "Codex-Migrate-Component-Staging"
            / migration_id
        )
        self.transport.run_remote(
            "set -eu\numask 077\n%s\n"
            "printf '%%s\\n' %s > %s\n"
            % (
                MigrationEngine._safe_directory_script(self.config.target_home, staging),
                shlex.quote(migration_id),
                shlex.quote(str(Path(staging) / ".codex-migrate-owner")),
            )
        )
        for index, item in enumerate(exports):
            staged_item = str(Path(staging) / "items" / str(index))
            self.transport.run_remote(
                MigrationEngine._safe_directory_script(staging, staged_item)
            )
            process = self.transport.rsync_process(
                item.source,
                staged_item,
                copy_links=True,
            )
            process.start()
        # A stop request must not kill SSH while destination paths are being
        # replaced. Complete this transaction (or its rollback) and then exit.
        with self.cancellation.replacement():
            print("Backing up, installing and verifying skills. Stop requests will "
                  "wait for this phase to finish.", file=sys.stderr, flush=True)
            receipt = self._install(exports, staging, migration_id)
        result.update(receipt)
        result["applied"] = True
        return result

    def _install(
        self,
        exports: Sequence[SkillExport],
        staging: str,
        migration_id: str,
    ) -> Dict[str, object]:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = str(
            Path(self.config.target_home)
            / ("Codex-Migrate-Component-Backup-" + timestamp)
        )
        preconditions = []
        backups = []
        installs = []
        rollbacks = []
        verifications = []
        mappings = []
        for index, item in enumerate(exports):
            destination = item.destination
            parent = str(Path(destination).parent)
            staged_item = str(Path(staging) / "items" / str(index))
            backup_item = str(Path(backup) / "items" / str(index))
            mappings.append((destination, backup_item))
            existed = str(Path(backup) / "existed" / str(index))
            safe_parent = MigrationEngine._safe_directory_script(
                self.config.target_home,
                parent,
            )
            workspace_requirement = ""
            if item.scope == "workspace":
                workspace_root = destination.split("/.agents/skills/", 1)[0]
                workspace_requirement = (
                    "test -d {workspace}\n"
                    "test ! -L {workspace}\n".format(
                        workspace=shlex.quote(workspace_root)
                    )
                )
            preconditions.append(
                workspace_requirement
                + safe_parent
                + "test -d {stage}\n"
                "test ! -L {stage}\n"
                "test -f {stage}/SKILL.md\n"
                "test ! -L {stage}/SKILL.md".format(stage=shlex.quote(staged_item))
            )
            backups.append(
                "if test -L {destination}; then\n"
                "  : > {existed}\n"
                "  cp -P {destination} {backup_item}\n"
                "  verify_backup {destination} {backup_item}\n"
                "elif test -e {destination}; then\n"
                "  test -d {destination}\n"
                "  test ! -L {destination}\n"
                "  : > {existed}\n"
                "  cp -c -R {destination} {backup_item}\n"
                "  verify_backup {destination} {backup_item}\n"
                "fi".format(
                    destination=shlex.quote(destination),
                    existed=shlex.quote(existed),
                    backup_item=shlex.quote(backup_item),
                )
            )
            installs.append(
                "rm -rf {destination}\n"
                "mv {stage} {destination}".format(
                    destination=shlex.quote(destination),
                    stage=shlex.quote(staged_item),
                )
            )
            rollbacks.append(
                "rm -rf {destination}\n"
                "if test -f {existed}; then\n"
                "  if test -L {backup_item}; then\n"
                "    cp -P {backup_item} {destination}\n"
                "  else\n"
                "    cp -c -R {backup_item} {destination}\n"
                "  fi\n"
                "fi".format(
                    destination=shlex.quote(destination),
                    existed=shlex.quote(existed),
                    backup_item=shlex.quote(backup_item),
                )
            )
            verifications.append(
                "test -f {destination}/SKILL.md\n"
                "test ! -L {destination}/SKILL.md".format(
                    destination=shlex.quote(destination)
                )
            )
        script = """set -eu
setopt NULL_GLOB
umask 077
{backup_functions}
{target_home_chain}
test -d {staging}
test ! -L {staging}
test "$(cat {marker})" = {migration_id}
test ! -e {backup}
{preconditions}
backup_required=$({backup_size})
backup_space {home} "$((backup_required + {reserve}))"
mkdir -p {backup}/items {backup}/existed
{backups}
backup_space {home} {reserve}
{backup_receipt}
rollback_needed=1
rollback() {{
  rollback_exit_code=$?
  if test "$rollback_needed" = 1; then
    set +e
    {rollbacks}
    echo 'Component installation failed; destination rollback was attempted.' >&2
  fi
  exit "$rollback_exit_code"
}}
trap rollback EXIT
{installs}
{verifications}
rollback_needed=0
trap - EXIT
rm -rf {staging}
printf 'INSTALLED=1\\nITEMS=%s\\nBACKUP_VERIFIED=1\\nBACKUP=%s\\n' {item_count} {backup}
""".format(
            backup_functions=BACKUP_FUNCTIONS,
            backup_size=size_command([item.destination for item in exports]),
            backup_receipt=verification_receipt(backup, mappings),
            home=shlex.quote(self.config.target_home),
            reserve=MIN_RESERVE_BYTES,
            target_home_chain=MigrationEngine._safe_directory_script(
                "/", self.config.target_home
            ),
            staging=shlex.quote(staging),
            marker=shlex.quote(str(Path(staging) / ".codex-migrate-owner")),
            migration_id=shlex.quote(migration_id),
            backup=shlex.quote(backup),
            preconditions="\n".join(preconditions),
            backups="\n".join(backups),
            rollbacks="\n".join(rollbacks),
            installs="\n".join(installs),
            verifications="\n".join(verifications),
            item_count=len(exports),
        )
        output = self.transport.run_remote(script, timeout=600).stdout
        if _value(output, "INSTALLED") != "1":
            raise MigrationError("Component installation did not produce a valid receipt")
        if _value(output, "BACKUP_VERIFIED") != "1":
            raise MigrationError("Component backup verification receipt is missing")
        if int(_value(output, "ITEMS") or -1) != len(exports):
            raise MigrationError("Component verification count mismatch")
        return {
            "backup": _value(output, "BACKUP"),
            "backup_verified": True,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
