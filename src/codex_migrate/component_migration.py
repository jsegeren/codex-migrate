"""Skills-only browser migrations using the existing transfer state machine."""

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re

from codex_migrate.backup import BACKUP_FUNCTIONS, MIN_RESERVE_BYTES, size_command
from codex_migrate.components import ComponentExporter
from codex_migrate.migration import MigrationEngine, MigrationError


class ComponentMigrationEngine(MigrationEngine):
    """Reuse pause/resume, scope confirmation and finalization; replace only skills.

    Unlike the one-shot CLI exporter, the browser stages first and requires a
    separate Finalize action. Both Codex apps must be closed for finalization.
    """

    def __init__(self, config, state, components):
        exporter = ComponentExporter(config, components)
        self.components = tuple(sorted(exporter.components))
        scope = {"source_home": exporter.config.source_home,
                 "target": exporter.config.target,
                 "target_home": exporter.config.target_home,
                 "workspace_roots": sorted(exporter.config.workspace_roots),
                 "components": self.components}
        digest = hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()[:24]
        config = replace(exporter.config, staging_name="Codex-Migrate-Skills-" + digest)
        super().__init__(config, state)
        self.exporter = ComponentExporter(self.config, self.components)
        self.state.update(migration_mode="skills", components=list(self.components))

    def _discover(self):
        self._inspection_checkpoint()
        for root in self.config.workspace_roots:
            if not Path(root).is_dir():
                raise MigrationError("Workspace root does not exist: %s" % root)
        if "workspace-skills" in self.components and not self.config.workspace_roots:
            raise MigrationError("Select workspace folders to discover project skills")
        exports = self.exporter.discover()
        self._inspection_checkpoint()
        return exports

    def _skill_plan(self):
        current = self._discover()
        if self._personal_skills is None:
            self._personal_skills = current
        elif self._personal_skills != current:
            raise MigrationError("Skill selection changed. Resume and review the new scope before finalizing.")
        return current

    def preflight(self, require_full_staging_space=True):
        if platform.system() != "Darwin":
            raise MigrationError("Codex Migrate currently supports macOS sources only")
        exports = self._discover()
        if not exports:
            raise MigrationError("No matching custom skills were found. Review your selected components and folders.")
        self._personal_skills = exports
        self.exporter.transport = self.transport
        self.exporter._preflight()
        self._inspection_checkpoint()
        incoming = 0
        def unreadable(error):
            raise error
        for item in exports:
            for current, directories, files in os.walk(item.source, onerror=unreadable):
                self._inspection_checkpoint()
                incoming += 4096 * (1 + len(directories))
                for name in files:
                    self._inspection_checkpoint()
                    info = (Path(current) / name).stat()
                    incoming += max(info.st_size, info.st_blocks * 512)
        backup_bytes = int(self.transport.run_remote(
            "set -eu\n" + BACKUP_FUNCTIONS + size_command(self._backup_targets()) + "\n",
            timeout=300,
        ).stdout.strip())
        if backup_bytes < 0:
            raise MigrationError("Invalid destination backup size")
        free = self.transport.remote_free_bytes(self.config.target_home)
        self._inspection_checkpoint()
        previous = self.state.read()
        staged = 0
        if previous.get("config") == self.config.to_public_dict():
            staged = self.transport.remote_bytes(self.config.target_staging)
        required = backup_bytes + MIN_RESERVE_BYTES + max(0, incoming - staged)
        self.state.update(
            inventory={"skill_exports": [item.as_dict() for item in exports]},
            config=self.config.to_public_dict(), bytes_total=incoming, bytes_staged=staged,
            destination_bytes_free=free, destination_bytes_required=required,
            backup_bytes_required=backup_bytes, reserve_bytes=MIN_RESERVE_BYTES,
            space_check="passed" if free >= required else "blocked",
        )
        if free < required:
            raise MigrationError("Not enough destination space for skill staging and verified backups. Free space and retry; there is no backup bypass.")
        route = self.transport.route()
        self._inspection_checkpoint()
        return self.state.update(
            status="ready", phase="preflight_complete", route=route, error=None,
            warning=None, message="Skills inspected. Review the listed destinations, then stage the selected skills. Conversations and whole repositories are not included.",
        )

    def _prepare_staging(self):
        super()._prepare_staging(include_codex=False)

    def _transfers(self):
        return [(item.source, str(Path(self.config.target_staging) / "items" / str(index)),
                 (), "Skill · " + item.name, True)
                for index, item in enumerate(self._skill_plan())]

    def _backup_targets(self):
        return [item.destination for item in self._skill_plan()]

    def _prepare_install(self):
        # Selective repairs verify their skills, not whole workspaces.
        return None

    def _install_and_verify(self, prepared_workspaces=None):
        items = self._skill_plan()
        migration_id = self.state.read().get("migration_id")
        if not isinstance(migration_id, str) or not re.fullmatch(r"[0-9a-f]{32}", migration_id):
            raise MigrationError("Staging ownership marker is missing from local state")
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = str(Path(self.config.target_home) / ("Codex-Migrate-Component-Backup-" + timestamp))
        self.state.update(pending_backup=backup)
        self.exporter.transport = self.transport
        receipt = self.exporter._install(items, self.config.target_staging, migration_id, backup=backup)
        receipt.update(items=[item.as_dict() for item in items], item_count=len(items),
                       skills_verified=len(items), components=list(self.components), applied=True)
        return receipt

    def compatibility_command(self):
        return None

    def completion_message(self):
        return "Selected skills installed and verified. You may reopen Codex. Conversations and whole repositories were not migrated."

    def completion_warning(self):
        return None
