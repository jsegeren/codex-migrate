"""Selective, repeatable exports for small migration components."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import secrets
import shlex
import sys
from typing import Dict, List, Sequence

from codex_migrate.config import MigrationConfig
from codex_migrate.destination_lock import locked_destination_script
from codex_migrate.transaction import transaction_commands, rollback_checks, recovery_preflight_script
from codex_migrate.cancellation import Cancellation
from codex_migrate.backup import (
    BACKUP_FUNCTIONS, MIN_RESERVE_BYTES, size_command, verification_receipt,
)
from codex_migrate.migration import MigrationEngine, MigrationError, _value
from codex_migrate.processes import require_codex_closed_script
from codex_migrate.transport import SSHTransport
from codex_migrate.skills import (
    SkillExport, discover_personal_skills, discover_workspace_skills, skill_verification_script,
)


SUPPORTED_COMPONENTS = ("personal-skills", "workspace-skills")


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
        home = Path(self.config.target_home)
        checks = ["test -d %s" % shlex.quote(str(home))]
        checks.extend("test ! -L %s" % shlex.quote(str(path)) for path in (home, *home.parents))
        self.transport.run_remote("set -eu\n" + "\n".join(checks) + "\n"
                                  + recovery_preflight_script(self.config.target_home))

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
        staging_script = (
            "set -eu\numask 077\n%s\n"
            "printf '%%s\\n' %s > %s\n"
            % (
                MigrationEngine._safe_directory_script(self.config.target_home, staging),
                shlex.quote(migration_id),
                shlex.quote(str(Path(staging) / ".codex-migrate-owner")),
            )
        )
        self.transport.run_remote(locked_destination_script(self.config.target_home, staging_script))
        for index, item in enumerate(exports):
            staged_item = str(Path(staging) / "items" / str(index))
            self.transport.run_remote(
                locked_destination_script(self.config.target_home,
                    MigrationEngine._safe_directory_script(staging, staged_item))
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
        backup: str = "",
    ) -> Dict[str, object]:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = backup or str(
            Path(self.config.target_home)
            / ("Codex-Migrate-Component-Backup-" + timestamp)
        )
        preconditions = []
        backups = []
        installs = []
        rollbacks = []
        verifications = []
        mappings = []
        stage_verifications = []
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
                + MigrationEngine._safe_directory_script(staging, str(Path(staged_item).parent))
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
                "  cp -c -Rp {destination} {backup_item}\n"
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
                "    cp -c -Rp {backup_item} {destination}\n"
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
            # Freeze once and verify both staging and installation against the
            # same source bytes. Explicit top-level exit preserves zsh rollback.
            function = "verify_component_%d" % index
            checks = skill_verification_script(item, self.config.source_home)
            failure = " || { echo 'Skill verification failed. Keep staging and backups; review and retry.' >&2; exit 74; }"
            stage_verifications.append("%s() {\n%s\n}\n%s %s%s" % (
                function, checks, function, shlex.quote(staged_item), failure))
            verifications.append("%s %s%s" % (function, shlex.quote(destination), failure))
        begin_transaction, installed_transaction, restored_transaction, clear_transaction = transaction_commands(
            self.config.target_home, backup, mappings)
        script = """set -eu
setopt NULL_GLOB
umask 077
{backup_functions}
{target_home_chain}
{codex_process_guard}
test -d {staging}
test ! -L {staging}
{staging_chain}
test -f {marker}
test ! -L {marker}
test "$(cat {marker})" = {migration_id}
test ! -e {backup}
test ! -L {backup}
{preconditions}
{stage_verifications}
{codex_process_guard}
backup_required=$({backup_size})
backup_space {home} "$((backup_required + {reserve}))"
mkdir -p {backup}/items {backup}/existed
{backups}
backup_space {home} {reserve}
{backup_receipt}
{codex_process_guard}
{begin_transaction}
{codex_process_guard}
rollback_needed=1
rollback() {{
  rollback_exit_code=$?
  if test "$rollback_needed" = 1; then
    set +e
    rollback_verified=0
    if cm_transaction check-backup; then
      {rollbacks}
      {rollback_verification}
    fi
    if test "$rollback_verified" = 1; then
      {restored_transaction} || rollback_verified=0
    fi
    if test "$rollback_verified" = 1; then
      {clear_transaction} || rollback_verified=0
    fi
    if test "$rollback_verified" = 1; then
      echo 'Component installation failed; destination rollback was verified.' >&2
    else
      echo 'Component installation failed and rollback is unconfirmed. Keep Codex closed, staging and backups intact, and contact support.' >&2
    fi
  fi
  exit "$rollback_exit_code"
}}
trap rollback EXIT
{installs}
{verifications}
{installed_transaction}
rollback_needed=0
trap - EXIT
rm -rf {staging}
{clear_transaction}
printf 'INSTALLED=1\\nITEMS=%s\\nBACKUP_VERIFIED=1\\nBACKUP=%s\\n' {item_count} {backup}
""".format(
            backup_functions=BACKUP_FUNCTIONS,
            begin_transaction=begin_transaction,
            installed_transaction=installed_transaction,
            restored_transaction=restored_transaction,
            clear_transaction=clear_transaction,
            rollback_verification=rollback_checks(mappings),
            codex_process_guard=require_codex_closed_script(self.config.target_home),
            backup_size=size_command([item.destination for item in exports]),
            backup_receipt=verification_receipt(backup, mappings),
            home=shlex.quote(self.config.target_home),
            reserve=MIN_RESERVE_BYTES,
            target_home_chain=MigrationEngine._safe_directory_script(
                "/", self.config.target_home
            ),
            staging=shlex.quote(staging),
            staging_chain=MigrationEngine._safe_directory_script(self.config.target_home, staging),
            marker=shlex.quote(str(Path(staging) / ".codex-migrate-owner")),
            migration_id=shlex.quote(migration_id),
            backup=shlex.quote(backup),
            preconditions="\n".join(preconditions),
            stage_verifications="\n".join(stage_verifications),
            backups="\n".join(backups),
            rollbacks="\n".join(rollbacks),
            installs="\n".join(installs),
            verifications="\n".join(verifications),
            item_count=len(exports),
        )
        output = self.transport.run_remote(
            locked_destination_script(self.config.target_home, script), timeout=600
        ).stdout
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
