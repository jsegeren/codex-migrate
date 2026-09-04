"""Migration state machine: inspect, stage, pause, resume, finalize, verify."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import platform
import os
import re
import secrets
import shlex
import subprocess
import threading
from typing import Dict, List, Optional, Sequence, Tuple

from codex_migrate.config import MigrationConfig
from codex_migrate.compatibility import READY as PATHS_READY, check_compatibility, compatibility_command
from codex_migrate.conversations import conversation_verification_script
from codex_migrate.errors import MigrationError
from codex_migrate.exclusions import CODEX_EXCLUDES
from codex_migrate.skills import SkillExport, discover_personal_skills, skill_verification_script
from codex_migrate.backup import BACKUP_FUNCTIONS, size_command, verification_receipt
from codex_migrate.destination_lock import locked_destination_script
from codex_migrate.transaction import transaction_commands, rollback_checks, recovery_preflight_script
from codex_migrate.inventory import Inventory, collect
from codex_migrate.security import redact
from codex_migrate.processes import codex_running, process_state_script, require_codex_closed_script
from codex_migrate.state import StateStore
from codex_migrate.transport import SSHTransport, TransferProcess
from codex_migrate.workspaces import (WORKSPACE_TIMEOUT, check_local_tools, freeze_tree,
                                      remote_tool_check, remote_tree_function, tree_check,
                                      validate_codex_identity_names)


class MigrationEngine:
    requires_home_compatibility = True

    def __init__(self, config: MigrationConfig, state: StateStore) -> None:
        self.config = config.validate()
        self.state = state
        self.transport = SSHTransport(config)
        self._thread: Optional[threading.Thread] = None
        self._process: Optional[TransferProcess] = None
        self._cancel_requested = False
        self._pause_requested = False
        self._lock = threading.RLock()
        self._personal_skills: Optional[List[SkillExport]] = None
        self._recovery_cancelled = False
        self._path_cancelled = False

    def inventory(self) -> Inventory:
        # Personal skills are installed individually, never by replacing .agents.
        # Reject intersecting workspace replacements rather than allow two writers
        # to the same destination in one rollback transaction.
        skill_root = Path(self.config.source_home) / ".agents/skills"
        for root in map(Path, self.config.workspace_roots):
            if root == skill_root or root in skill_root.parents or skill_root in root.parents:
                raise MigrationError(
                    "Personal skills are included automatically. Remove the workspace "
                    "selection overlapping .agents/skills; select project folders instead."
                )
        result = collect(self.config.source_home, self.config.workspace_roots,
                         self._inspection_checkpoint, self.config.target_home)
        self._personal_skills = result.personal_skills
        return result

    def _skill_plan(self) -> List[SkillExport]:
        current = discover_personal_skills(self.config.source_home, self.config.target_home)
        if self._personal_skills is None:
            self._personal_skills = current
        elif current != self._personal_skills:
            raise MigrationError("Personal skill selection changed. Inspect and resume before installing.")
        return current

    def _inspection_checkpoint(self) -> None:
        if self._cancel_requested:
            raise MigrationError("Inspection stopped")

    def start_inspection(self) -> None:
        with self._lock:
            self._require_ready_for_migration()
            if self._thread and self._thread.is_alive():
                raise MigrationError("A migration action is already running")
            self.state.update(status="running", phase="inspecting",
                              message="Inspecting both Macs. Safe to stop.", error=None)
            self._start(self._run_inspection)

    def _run_inspection(self) -> None:
        self.preflight()
        self._restore_requested_stop()

    def start_recovery_check(self) -> None:
        with self._lock:
            if (self._thread and self._thread.is_alive()) or self.state.read().get("status") == "running":
                raise MigrationError("Wait for the current migration action to finish")
            self._recovery_cancelled = False
            self.state.update(recovery={"status": "checking", "message":
                "Checking destination recovery evidence and backup contents. This can take time; safe to stop. No files will be replaced."})
            self._start(self._run_recovery_check)

    def _run_recovery_check(self) -> None:
        from codex_migrate.recovery import inspect_recovery
        from codex_migrate.reconciliation import reconcile_recovery
        current = self.state.read()
        attempt = current.get("recovery_attempt")
        reconciling = (current.get("phase") in ("restoring", "restored", "recovery_required")
                       or attempt is not None and (not isinstance(attempt, dict) or attempt.get("resolved") is not True))
        try:
            if reconciling:
                report = reconcile_recovery(self.config, self.transport, attempt["reference"], lambda: self._recovery_cancelled)
            else:
                report = inspect_recovery(self.config, self.transport, lambda: self._recovery_cancelled)
        except Exception:
            report = {"status": "failed", "message":
                "Recovery could not be verified. Keep destination Codex closed, staging and backups intact, and contact support. No recovery changes were made."}
        with self._lock:
            if not self._recovery_cancelled:
                self._publish_recovery(report, reconciling)

    def _require_recovery_resolved(self) -> None:
        from codex_migrate.recovery import recovery_reference
        from codex_migrate.reconciliation import _validate_result
        current = self.state.read()
        attempt = current.get("recovery_attempt")
        protected = current.get("phase") in ("restoring", "restored", "recovery_required")
        if attempt is None and not protected:
            return
        try:
            if not isinstance(attempt, dict) or attempt.get("resolved") is not True or attempt.get("outcome") != "restore_verified":
                raise ValueError("Restoration unresolved")
            reference = recovery_reference(self.config.target_home, attempt["inspection"])
            if reference != attempt["reference"]:
                raise ValueError("Mismatched recovery reference")
            proof = attempt["proof"]
            _validate_result(proof, reference)
            if proof["status"] != "restore_verified" or current.get("phase") in ("restoring", "recovery_required"):
                raise ValueError("Unverified recovery state")
        except (KeyError, TypeError, ValueError) as error:
            raise MigrationError("Check recovery and resolve the previous restoration before starting another migration action") from error

    def _require_ready_for_migration(self) -> None:
        self._require_recovery_resolved()
        if self.state.read().get("phase") == "path_compatibility":
            raise MigrationError("Installation is already verified. Resolve Home-path compatibility and check home paths before starting another migration.")

    def _publish_recovery(self, report, reconciling=False) -> None:
        report["checked_at"] = datetime.now(timezone.utc).isoformat()
        changes = {"recovery": report}
        if reconciling:
            saved = self.state.read().get("recovery_attempt")
            attempt = dict(saved) if isinstance(saved, dict) else {}
            resolved = report["status"] == "restore_verified"
            attempt.update(resolved=resolved, outcome=report["status"],
                           proof={key: value for key, value in report.items() if key not in ("message", "checked_at")} if resolved else None)
            changes.update(recovery_attempt=attempt, staging_complete=False, receipt=None,
                           status="interrupted" if resolved else "failed",
                           phase="restored" if resolved else "recovery_required",
                           current_item=None, message=report["message"], error=None if resolved else "Restoration needs review")
            if resolved:
                changes["pending_backup"] = None
        self.state.update(**changes)

    def start_restore_recovery(self, transaction_id) -> None:
        from codex_migrate.recovery import recovery_reference
        with self._lock:
            current = self.state.read()
            if not self.config.apply:
                raise MigrationError("Changes are disabled; enable them before restoring")
            if (self._thread and self._thread.is_alive()) or current.get("status") == "running":
                raise MigrationError("Wait for the current action to finish")
            report = current.get("recovery", {})
            attempt = current.get("recovery_attempt")
            if report.get("status") == "backup_verified":
                inspection = report
            elif report.get("status") in ("restore_incomplete", "restore_pending_cleanup") and isinstance(attempt, dict):
                inspection = attempt["inspection"]
            else:
                raise MigrationError("Check recovery and review the backup before confirming restoration")
            reference = recovery_reference(self.config.target_home, inspection)
            if not isinstance(transaction_id, str) or transaction_id != reference["transaction_id"]:
                raise MigrationError("Recovery selection changed; check and confirm it again")
            attempt = {"reference": reference, "inspection": inspection, "resolved": False, "outcome": "restoring"}
            self.state.update(recovery_attempt=attempt, status="running", phase="restoring", error=None,
                              current_item="Destination backup restoration",
                              staging_complete=False, recovery={"status": "restoring", "message":
                                  "Preserving current destination files and restoring the backup. This protected step can take time; keep both Macs connected and destination Codex closed."},
                              message="Restoring the previous destination. Protected step; keep both Macs connected.")
            try:
                self.state.sync_recovery_checkpoint()
            except Exception as error:
                self.state.update(status="failed", phase="recovery_required", recovery={"status": "restore_unconfirmed",
                                  "message": "The recovery checkpoint could not be saved safely. No restore request was sent. Check recovery before retrying."},
                                  message="Recovery checkpoint could not be saved. No restore request was sent.")
                raise MigrationError("Could not safely save the recovery checkpoint; restoration was not started") from error
            self._start(self._run_restore_recovery)

    def _run_restore_recovery(self) -> None:
        from codex_migrate.restore import restore_recovery
        from codex_migrate.reconciliation import reconcile_recovery
        attempt = self.state.read()["recovery_attempt"]
        try:
            restore_recovery(self.config, self.transport, attempt["inspection"])
            report = reconcile_recovery(self.config, self.transport, attempt["reference"])
        except Exception:
            report = {"status": "restore_unconfirmed", "message":
                      "Restoration is not confirmed. The destination may still be working. Keep Codex closed there and choose Check recovery; do not start another migration."}
        with self._lock:
            self._publish_recovery(report, True)

    def stop_recovery_check(self) -> None:
        with self._lock:
            if self.state.read().get("recovery", {}).get("status") != "checking":
                raise MigrationError("No recovery check is running")
            self._recovery_cancelled = True
            self.transport.cancel_all()
            self.state.update(recovery={"status": "stopped", "message":
                "Check stopped locally; no result is being claimed. A destination check may still be finishing. Wait if the next attempt reports busy. No recovery changes were made."})

    def reconcile_startup(self) -> None:
        current = self.state.read()
        if current.get("path_compatibility", {}).get("status") == "checking":
            self.state.update(path_compatibility={"status": "unverified", "message":
                "The previous path check ended without a result. Check home paths again; no path changes were requested."})
        if current.get("recovery", {}).get("status") == "restoring" or current.get("phase") == "restoring":
            self.state.update(status="failed", phase="recovery_required", staging_complete=False,
                              message="Restoration outcome is unconfirmed. Keep destination Codex closed and choose Check recovery.",
                              recovery={"status": "restore_unconfirmed", "message":
                                  "The previous restore request ended without a confirmed result. The destination may still be working. Keep Codex closed there and choose Check recovery."})
            return
        if current.get("recovery", {}).get("status") == "checking":
            self.state.update(recovery={"status": "stopped", "message":
                "The previous recovery check ended without a result. No recovery changes were made. Check again when ready."})
        if current.get("status") != "running":
            return
        if current.get("phase") == "installing":
            self.state.update(
                status="failed",
                message=(
                    "The previous process ended during installation. The destination may still be "
                    "working, and rollback is unconfirmed. Keep Codex closed there and review recovery evidence before retrying."
                ),
                error="Previous process ended during installation",
                staging_complete=False,
            )
        else:
            self.state.update(
                status="interrupted",
                message="The previous process ended. Staged data was kept; Resume will continue.",
                error=None,
            )

    def shutdown(self) -> None:
        with self._lock:
            if self.state.read().get("phase") == "restoring" and self.state.read().get("status") == "running":
                raise MigrationError("Restoration is a protected step; wait for its result before quitting")
            recovery_checking = self.state.read().get("recovery", {}).get("status") == "checking"
            paths_checking = self.state.read().get("path_compatibility", {}).get("status") == "checking"
            if paths_checking:
                self._path_cancelled = True
                self.transport.cancel_all()
                self.state.update(path_compatibility={"status": "unverified", "message":
                    "Path check stopped. No path changes were requested. Check home paths again when ready."})
                thread = self._thread
            if recovery_checking:
                self.stop_recovery_check()
                thread = self._thread
        if recovery_checking or paths_checking:
            if thread and thread.is_alive() and thread is not threading.current_thread():
                thread.join(timeout=10)
            return
        with self._lock:
            current = self.state.read()
            if current.get("status") != "running":
                return
            self._cancel_requested = True
            if self._process:
                self._process.cancel()
            self.transport.cancel_all()
            phase = current.get("phase")
            if phase == "installing":
                self.state.update(
                    status="failed",
                    message=(
                        "Shutdown interrupted installation. The destination may still be working, "
                        "and rollback is unconfirmed. Keep Codex closed there and review recovery evidence before retrying."
                    ),
                    error="Installation interrupted by shutdown",
                    staging_complete=False,
                )
            else:
                self.state.update(
                    status="interrupted",
                    message="Stopped for shutdown. Staged data was kept; Resume will continue.",
                    error=None,
                )
            thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=10)

    def preflight(self, require_full_staging_space: bool = True) -> Dict[str, object]:
        with self._lock:
            self._require_ready_for_migration()
            if (
                self._thread
                and self._thread.is_alive()
                and threading.current_thread() is not self._thread
            ):
                raise MigrationError("A migration action is already running")
        if platform.system() != "Darwin":
            raise MigrationError("Codex Migrate currently supports macOS sources only")
        if not Path(self.config.source_codex).is_dir():
            raise MigrationError("No .codex directory exists in the source home")
        if Path(self.config.source_codex).is_symlink():
            raise MigrationError("The source .codex directory must not be a symbolic link")
        validate_codex_identity_names(self.config.source_codex)
        if not Path(self.config.source_codex, "sessions").is_dir():
            raise MigrationError("No local Codex sessions directory was found")
        for root in self.config.workspace_roots:
            if not Path(root).is_dir():
                raise MigrationError("Workspace root does not exist: %s" % root)
        inventory = self.inventory()
        self.state.update(inventory=inventory.as_dict())
        if inventory.git_issues:
            raise MigrationError("Git dependency inspection needs review before transfer: "
                                 + "; ".join(inventory.git_issues[:5]))
        if inventory.git_missing_paths:
            raise MigrationError("Git dependencies are outside the selected workspace folders. "
                                 "Restart setup, add these folders to the selection, and inspect again: "
                                 + "; ".join(inventory.git_missing_paths[:10]))
        check_local_tools()
        remote = self.transport.check()
        self.transport.run_remote(remote_tool_check())
        self._inspection_checkpoint()
        expected_user = self.config.target.split("@", 1)[0]
        actual_user = _value(remote, "USER")
        actual_home = _value(remote, "HOME")
        filesystem = _value(remote, "FILESYSTEM")
        if actual_user != expected_user:
            raise MigrationError("SSH user mismatch: expected %s, got %s" % (expected_user, actual_user))
        if actual_home != self.config.target_home:
            raise MigrationError(
                "Target home mismatch: SSH reports %s, configured %s"
                % (actual_home, self.config.target_home)
            )
        if filesystem != "apfs":
            raise MigrationError(
                "The destination home must be on APFS for copy-on-write rollback backups"
            )
        paths = check_compatibility(self.config, self.transport, lambda: self._cancel_requested)
        self.state.update(path_compatibility=paths)
        if paths["status"] not in PATHS_READY | {"missing"}:
            raise MigrationError(paths["message"])
        target_codex = shlex.quote(self.config.target_codex)
        target_home = shlex.quote(self.config.target_home)
        self.transport.run_remote(recovery_preflight_script(self.config.target_home))
        result = self.transport.run_remote(
            "set -eu\n"
            "test -d %s\n"
            "test ! -L %s\n"
            "test -d %s\n"
            "test ! -L %s\n"
            "test -f %s/auth.json\n"
            "test ! -L %s/auth.json\n"
            "test -f %s/installation_id\n"
            "test ! -L %s/installation_id\n"
            "printf 'TARGET_CODEX_READY=1\\n'\n"
            % (
                target_home,
                target_home,
                target_codex,
                target_codex,
                target_codex,
                target_codex,
                target_codex,
                target_codex,
            )
        )
        if _value(result.stdout, "TARGET_CODEX_READY") != "1":
            raise MigrationError("Open and sign in to Codex once on the target Mac first")
        self._inspection_checkpoint()
        backup_bytes = int(self.transport.run_remote(
            "set -eu\n" + BACKUP_FUNCTIONS + size_command(self._backup_targets()) + "\n",
            timeout=300,
        ).stdout.strip())
        if backup_bytes < 0:
            raise MigrationError("Invalid destination backup size")
        available_bytes = self.transport.remote_free_bytes(self.config.target_home)
        self._inspection_checkpoint()
        reserve_bytes = min(
            20 * 1024**3,
            max(2 * 1024**3, inventory.estimated_transfer_bytes // 20),
        )
        previous = self.state.read()
        same_config = previous.get("config") == self.config.to_public_dict()
        staged_bytes = 0
        if same_config and require_full_staging_space:
            staged_bytes = self.transport.remote_bytes(self.config.target_staging)
        elif same_config:
            staged_bytes = int(previous.get("bytes_staged") or 0)
        remaining_bytes = max(0, inventory.estimated_transfer_bytes - staged_bytes)
        required_bytes = backup_bytes + reserve_bytes + (
            remaining_bytes if require_full_staging_space else 0
        )
        self.state.update(
            destination_bytes_free=available_bytes,
            destination_bytes_required=required_bytes,
            backup_bytes_required=backup_bytes,
            reserve_bytes=reserve_bytes,
            space_check="passed" if available_bytes >= required_bytes else "blocked",
        )
        if available_bytes < required_bytes:
            raise MigrationError(
                "Installation blocked: not enough destination space for staging, backup, "
                "and safety reserve. Need %d bytes free, found %d. "
                "Free space on the destination and retry; there is no backup bypass."
                % (required_bytes, available_bytes)
            )
        if inventory.unreadable_paths:
            warning = "%d unreadable paths will need review" % len(inventory.unreadable_paths)
        else:
            warning = None
        if inventory.git_warnings:
            warning = "; ".join(filter(None, [warning] + inventory.git_warnings[:5]))
        route = self.transport.route()
        self._inspection_checkpoint()
        state = self.state.update(
            status="ready",
            phase="preflight_complete",
            message="Both Macs passed preflight. Ready to stage a resumable copy.",
            bytes_total=inventory.estimated_transfer_bytes,
            bytes_staged=staged_bytes,
            destination_bytes_free=available_bytes,
            destination_bytes_required=required_bytes,
            route=route,
            warning=warning,
            inventory=inventory.as_dict(),
            config=self.config.to_public_dict(),
            error=None,
        )
        return state

    def start_preseed(self) -> None:
        self._require_ready_for_migration()
        current = self.state.read()
        if current.get("status") not in (
            "idle",
            "ready",
            "paused",
            "cancelled",
            "failed",
            "interrupted",
        ):
            raise MigrationError("The current migration state cannot start or resume staging")
        self._start(self._run_preseed)

    def start_finalize(self) -> None:
        self._require_ready_for_migration()
        current = self.state.read()
        allowed = current.get("status") == "ready_to_finalize" or (
            current.get("status") == "waiting"
            and current.get("phase") in ("close_source_codex", "close_target_codex")
        )
        if not allowed or not current.get("staging_complete"):
            raise MigrationError("Finish staging successfully before finalization")
        self._start(self._run_finalize)

    def _start(self, target) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise MigrationError("A migration action is already running")
            self._cancel_requested = False
            self._pause_requested = False
            self._thread = threading.Thread(target=self._guarded, args=(target,), daemon=True)
            self._thread.start()

    def _guarded(self, target) -> None:
        try:
            target()
        except Exception as error:  # surfaced through owner-only state, never raw secrets
            message = redact(
                str(error),
                [self.config.ssh.identity_file or "", self.config.ssh.known_hosts_file or ""],
            )
            if self._pause_requested or self._cancel_requested:
                current = self.state.read()
                if current.get("status") == "running" and current.get("phase") == "verifying_sources":
                    self._restore_requested_stop()
                return
            current = self.state.read()
            changes = {"status": "failed", "message": message, "error": message}
            if current.get("phase") == "installing":
                changes["staging_complete"] = False
            self.state.update(**changes)
        finally:
            self._process = None

    def _prepare_staging(self, include_codex: bool = True) -> None:
        staging = shlex.quote(self.config.target_staging)
        migration_id = self.state.read().get("migration_id")
        if not isinstance(migration_id, str) or not re.fullmatch(r"[0-9a-f]{32}", migration_id):
            migration_id = secrets.token_hex(16)
            self.state.update(migration_id=migration_id)
        marker = shlex.quote(str(Path(self.config.target_staging) / ".codex-migrate-owner"))
        script = (
            "set -eu\numask 077\n"
            "if test -e {staging}; then\n"
            "  test -d {staging}\n"
            "  test ! -L {staging}\n"
            "  test -f {marker}\n"
            "  test ! -L {marker}\n"
            "  test \"$(cat {marker})\" = {migration_id}\n"
            "else\n"
            "  mkdir {staging}\n"
            "  printf '%s\\n' {migration_id} > {marker}\n"
            "fi\n"
            "{codex_preparation}"
            "chmod 700 {staging}\n".format(
                staging=staging,
                marker=marker,
                migration_id=shlex.quote(migration_id),
                codex_preparation=(
                    "test ! -L {s}/.codex\n"
                    "test ! -L {s}/home-relative\n"
                    "mkdir -p {s}/.codex {s}/home-relative\n"
                    "rm -f {s}/.codex/auth.json {s}/.codex/installation_id\n"
                ).format(s=staging) if include_codex else "",
            )
        )
        self.transport.run_remote(locked_destination_script(self.config.target_home, script))

    def _transfers(self) -> List[Tuple[str, str, Sequence[str], str, bool]]:
        validate_codex_identity_names(self.config.source_codex)
        staging = self.config.target_staging
        transfers: List[Tuple[str, str, Sequence[str], str, bool]] = [
            (self.config.source_codex, staging + "/.codex", CODEX_EXCLUDES, "Codex state", False)
        ]
        source_home = self.config.source_home.rstrip("/")
        for root in self.config.workspace_roots:
            relative = root[len(source_home) + 1 :]
            transfers.append(
                (root, staging + "/home-relative/" + relative, (), "Workspace · %s" % relative, False)
            )
        for skill in self._skill_plan():
            transfers.append((skill.source, staging + "/personal-skills/" + skill.name,
                              (), "Personal skill · " + skill.name, True))
        return transfers

    def _run_preseed(self) -> None:
        if not self.config.apply:
            raise MigrationError("Planning mode is read-only; restart with --apply to transfer")
        self.state.update(
            status="running",
            phase="inspecting",
            message="Checking both Macs before staging begins.",
            error=None,
            staging_complete=False,
        )
        self.preflight()
        if self._restore_requested_stop():
            return
        self._prepare_staging()
        if self._restore_requested_stop():
            return
        self.state.update(
            status="running",
            phase="staging",
            message="Staging a resumable copy. Source data is not modified.",
            error=None,
        )
        self._copy_all()
        if self._restore_requested_stop():
            return
        self.state.update(
            status="ready_to_finalize",
            phase="staged",
            message="Staging is current. Close Codex app and CLI sessions in both migration accounts, then choose Finalize.",
            current_item=None,
            percent=min(99.0, self.state.read().get("percent", 0.0)),
            staging_complete=True,
            staged_personal_skills=[skill.as_dict() for skill in self._skill_plan()],
        )

    def _copy_all(self) -> None:
        transfers = self._transfers()
        for index, (source, destination, excludes, label, copy_links) in enumerate(transfers, 1):
            if self._cancel_requested:
                return
            self.state.update(
                current_item=label,
                message="Copying %s (%d of %d). Safe to pause." % (label, index, len(transfers)),
            )
            self.transport.run_remote(
                locked_destination_script(self.config.target_home,
                    self._safe_directory_script(self.config.target_staging, destination))
            )
            if copy_links:
                self._skill_plan()  # Revalidate aliases before dereferencing them.
            process = self.transport.rsync_process(source, destination, excludes,
                                                   copy_links=copy_links)
            self._process = process
            if self._pause_requested or self._cancel_requested:
                self._process = None
                return
            monitor_stop = threading.Event()
            monitor = threading.Thread(
                target=self._monitor_staging,
                args=(monitor_stop,),
                daemon=True,
            )
            monitor.start()
            try:
                process.start(self._handle_rsync_output)
            finally:
                monitor_stop.set()
                monitor.join(timeout=3)
                self._process = None
        self._update_staged_bytes()

    def _handle_rsync_output(self, line: str) -> None:
        if "to-check=" in line or "to-chk=" in line:
            self.state.update(detail=line[-240:])

    def _monitor_staging(self, stop: threading.Event) -> None:
        while not stop.wait(30):
            try:
                self._update_staged_bytes()
            except Exception:
                pass

    def _update_staged_bytes(self) -> None:
        staged = self.transport.remote_bytes(self.config.target_staging)
        total = max(1, int(self.state.read().get("bytes_total") or 1))
        percent = min(99.0, staged * 100.0 / total)
        self.state.update(bytes_staged=staged, percent=round(percent, 2))

    def pause(self) -> None:
        with self._lock:
            current = self.state.read()
            if current.get("status") != "running" or current.get("phase") not in (
                "staging",
                "final_delta",
            ):
                raise MigrationError("Pause is available only while files are being copied")
            self._pause_requested = True
            if self._process:
                self._process.cancel()
            self.state.update(
                status="paused",
                phase="staging",
                message="Paused. Staged data is preserved and resumable.",
            )

    def resume(self) -> None:
        with self._lock:
            if self.state.read().get("status") not in (
                "paused",
                "cancelled",
                "failed",
                "interrupted",
            ):
                raise MigrationError("Resume is unavailable in the current migration state")
            if self._thread and self._thread.is_alive():
                raise MigrationError("Pause is still settling; try Resume again in a moment")
            self._pause_requested = False
            self._cancel_requested = False
            self.start_preseed()

    def cancel(self) -> None:
        with self._lock:
            current = self.state.read()
            stoppable = current.get("status") == "running" and current.get("phase") in (
                "inspecting", "staging", "final_delta", "verifying_sources"
            )
            already_paused = (
                current.get("status") == "paused" and current.get("phase") == "staging"
            )
            if not stoppable and not already_paused:
                raise MigrationError("Safe stop is available only before installation begins")
            self._cancel_requested = True
            self._pause_requested = False
            if self._process:
                self._process.cancel()
            if current.get("phase") == "inspecting":
                self.transport.cancel_all()
            self.state.update(
                status="cancelled",
                phase="staging",
                message="Stopped. Staged data was kept; Resume will continue from it.",
            )

    def _restore_requested_stop(self) -> bool:
        if self._pause_requested:
            self.state.update(
                status="paused",
                phase="staging",
                message="Paused. Staged data is preserved and resumable.",
                error=None,
            )
            return True
        if self._cancel_requested:
            self.state.update(
                status="cancelled",
                phase="staging",
                message="Stopped. Staged data was kept; Resume will continue from it.",
                error=None,
            )
            return True
        return False

    def _run_finalize(self) -> None:
        if not self.config.apply:
            raise MigrationError("Planning mode is read-only; restart with --apply to finalize")
        staged_skills = self.state.read().get("staged_personal_skills")
        if staged_skills is None:
            raise MigrationError("Staging has no personal-skill scope record. Choose Resume to refresh staging before finalizing.")
        confirmed_skills = [skill.as_dict() for skill in self._skill_plan()]
        if confirmed_skills != staged_skills:
            raise MigrationError("Personal skill selection changed since staging. Choose Resume to refresh and review the new scope before finalizing.")
        self.preflight(require_full_staging_space=False)
        if [skill.as_dict() for skill in self._skill_plan()] != staged_skills:
            raise MigrationError("Personal skill selection changed during inspection. Resume and review the new scope before finalizing.")
        if codex_running(self.config.source_home):
            self.state.update(
                status="waiting",
                phase="close_source_codex",
                message="Close Codex app and CLI sessions in the source account, then choose Finalize again.",
            )
            return
        remote_running = self._remote_codex_state()
        if remote_running != "CLOSED":
            self.state.update(
                status="waiting",
                phase="close_target_codex",
                message="Close Codex app and CLI sessions in the destination account, then choose Finalize again.",
            )
            return
        self.state.update(
            status="running",
            phase="final_delta",
            message="Refreshing the final delta with Codex closed in both migration accounts.",
            error=None,
        )
        self._prepare_staging()
        self._copy_all()
        if self._restore_requested_stop():
            return
        prepared_workspaces = self._prepare_install()
        if self._restore_requested_stop():
            return
        if codex_running(self.config.source_home):
            self.state.update(
                status="waiting",
                phase="close_source_codex",
                message="Codex reopened in the source account. Close its app and CLI sessions, then choose Finalize again.",
                staging_complete=True,
            )
            return
        if self._remote_codex_state() != "CLOSED":
            self.state.update(
                status="waiting",
                phase="close_target_codex",
                message="Codex reopened in the destination account. Close its app and CLI sessions, then choose Finalize again.",
                staging_complete=True,
            )
            return
        with self._lock:
            if self._restore_requested_stop():
                return
            self.state.update(
                status="running",
                phase="installing",
                message="Verifying destination contents, backing up, installing and checking again. This protected phase can take time; keep both Macs connected.",
                current_item="Destination verification and installation",
            )
        receipt = self._install_and_verify(prepared_workspaces)
        self._complete_installation(receipt)

    def _complete_installation(self, receipt) -> None:
        # Save installation evidence before a fallible post-install SSH check.
        # A lost path-check reply must not masquerade as a failed installation.
        with self._lock:
            self._path_cancelled = self._cancel_requested
            self.state.update(
                status="needs_attention" if self.requires_home_compatibility else "complete",
                phase="path_compatibility" if self.requires_home_compatibility else "verified",
                message="Files installed and verified. Checking home-path compatibility before opening old work." if self.requires_home_compatibility else self.completion_message(),
                current_item=None,
                bytes_staged=self.state.read().get("bytes_total", 0),
                percent=100.0,
                warning=self.completion_warning(),
                receipt=receipt,
                pending_backup=None,
                error=None,
            )
            if self.requires_home_compatibility:
                self.state.update(path_compatibility={"status": "unverified" if self._path_cancelled else "checking",
                    "message": "Check home paths before opening old work." if self._path_cancelled else "Checking destination home paths. No files are being changed."})
        if self.requires_home_compatibility and not self._path_cancelled:
            self._run_path_check()

    def start_path_check(self) -> None:
        with self._lock:
            if not self.requires_home_compatibility:
                raise MigrationError("A skills-only repair does not change home-path compatibility")
            self._require_recovery_resolved()
            if (self._thread and self._thread.is_alive()) or self.state.read().get("status") == "running":
                raise MigrationError("Wait for the current migration action to finish")
            self._path_cancelled = False
            self.state.update(path_compatibility={"status": "checking", "message": "Checking destination home paths. No files are being changed."})
            self._start(self._run_path_check)

    def _run_path_check(self) -> None:
        report = check_compatibility(self.config, self.transport, lambda: self._path_cancelled)
        with self._lock:
            if self._path_cancelled:
                return
            current = self.state.read()
            changes = {"path_compatibility": report}
            if current.get("phase") in ("path_compatibility", "verified"):
                receipt = current.get("receipt")
                valid_receipt = (isinstance(receipt, dict)
                    and all(receipt.get(key) is True for key in ("backup_verified", "auth_preserved", "installation_id_preserved", "conversation_content_verified", "codex_state_content_verified", "workspace_content_verified"))
                    and receipt.get("source_home") == self.config.source_home
                    and receipt.get("target_home") == self.config.target_home)
                ready = valid_receipt and report["status"] in PATHS_READY
                changes.update(status="complete" if ready else "needs_attention",
                               phase="verified" if ready else "path_compatibility",
                               message=self.completion_message() if ready else "Files were installed and verified, but old home paths are not ready. Check the Home-path compatibility panel before opening old work." if valid_receipt else "Installation evidence could not be validated. Keep the backup and current files intact and contact support.",
                               warning=None if ready else report["message"] if valid_receipt else "A home-path check does not prove installation succeeded.", error=None)
            self.state.update(**changes)

    def completion_message(self) -> str:
        return "Files installed and verified; home paths checked. Open representative Codex chats and repositories to confirm they work before retiring the old Mac."

    def completion_warning(self) -> Optional[str]:
        if self.config.source_home != self.config.target_home:
            return (
                "Home paths differ. Check Home-path compatibility before resuming older chats."
            )
        return None

    def _remote_codex_state(self) -> str:
        state = self.transport.run_remote(process_state_script(self.config.target_home)).stdout.strip()
        if state not in ("OPEN", "CLOSED"):
            raise MigrationError("Cannot verify destination Codex process state; finalization is blocked")
        return state

    def _backup_targets(self) -> List[str]:
        return [self.config.target_codex] + [
            self.config.target_home + "/" + str(Path(root).relative_to(self.config.source_home))
            for root in self.config.workspace_roots
        ] + [skill.destination for skill in self._skill_plan()]

    def _prepare_install(self):
        roots = [(root, self.config.target_staging + "/home-relative/" + str(Path(root).relative_to(self.config.source_home)),
                  self.config.target_home + "/" + str(Path(root).relative_to(self.config.source_home)))
                 for root in self.config.workspace_roots]
        managed = Path(self.config.source_codex) / "worktrees"
        roots.append((str(managed), self.config.target_staging + "/.codex/worktrees",
                      self.config.target_codex + "/worktrees"))
        prepared = []
        for index, (source, staged, installed) in enumerate(roots, 1):
            with self._lock:
                self._inspection_checkpoint()
                self.state.update(status="running", phase="verifying_sources",
                                  message="Reading source workspace contents (%d of %d). Safe to stop; a stopped check restarts on Finalize." % (index, len(roots)),
                                  current_item="Source workspace verification")
            absent_managed = False
            if source == str(managed):
                try:
                    os.lstat(managed)
                except FileNotFoundError:
                    absent_managed = True
            digest = None if absent_managed else freeze_tree(source, self._inspection_checkpoint)
            prepared.append((staged, installed, digest))
        with self._lock:
            self._inspection_checkpoint()
            self.state.update(status="running", phase="verifying_sources",
                              message="Reading retained Codex state. Safe to stop; a stopped check restarts on Finalize.",
                              current_item="Source Codex state verification")
        return {"workspaces": prepared,
                "codex_state": freeze_tree(self.config.source_codex, self._inspection_checkpoint, codex=True)}

    def _install_and_verify(self, prepared_workspaces=None) -> Dict[str, object]:
        if prepared_workspaces is None:
            prepared_workspaces = self._prepare_install()
        codex_state_digest = prepared_workspaces["codex_state"]
        prepared_workspaces = prepared_workspaces["workspaces"]
        self.state.update(phase="installing")
        recorded_inventory = self.state.read().get("inventory")
        if isinstance(recorded_inventory, dict):
            try:
                expected_active = int(recorded_inventory["active_sessions"]["files"])
                expected_archived = int(recorded_inventory["archived_sessions"]["files"])
            except (KeyError, TypeError, ValueError):
                recorded_inventory = None
        if not isinstance(recorded_inventory, dict):
            source_inventory = self.inventory()
            expected_active = source_inventory.active_sessions.files
            expected_archived = source_inventory.archived_sessions.files
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = str(Path(self.config.target_home) / (self.config.backup_prefix + "-" + timestamp))
        q_home = shlex.quote(self.config.target_home)
        q_codex = shlex.quote(self.config.target_codex)
        q_staging = shlex.quote(self.config.target_staging)
        q_backup = shlex.quote(backup)
        migration_id = self.state.read().get("migration_id")
        if not isinstance(migration_id, str) or not re.fullmatch(r"[0-9a-f]{32}", migration_id):
            raise MigrationError("Staging ownership marker is missing from local state")
        q_marker = shlex.quote(str(Path(self.config.target_staging) / ".codex-migrate-owner"))
        workspace_preconditions = []
        install_workspaces = []
        backup_workspaces = []
        rollback_workspaces = []
        mappings = [(self.config.target_codex, backup + "/.codex")]
        skills = self._skill_plan()
        skill_stage_checks = []
        skill_installed_checks = []
        for index, skill in enumerate(skills):
            stage_skill = self.config.target_staging + "/personal-skills/" + skill.name
            # Hash once: install verification must use the exact same snapshot
            # as staging, even if source files change while SSH is running.
            checks = skill_verification_script(skill, self.config.source_home)
            function = "verify_personal_skill_%d" % index
            failure = " || { echo 'Personal skill verification failed. Keep staging and any backup, then Resume to retry.' >&2; exit 74; }"
            skill_stage_checks.append("%s() {\n%s\n}\n%s %s%s" % (
                function, checks, function, shlex.quote(stage_skill), failure))
            skill_installed_checks.append("%s %s%s" % (function, shlex.quote(skill.destination), failure))
        replacements = []
        for root in self.config.workspace_roots:
            relative = root[len(self.config.source_home.rstrip("/")) + 1 :]
            replacements.append((self.config.target_staging + "/home-relative/" + relative,
                                 self.config.target_home + "/" + relative,
                                 backup + "/home-relative/" + relative, False))
        for skill in skills:
            replacements.append((self.config.target_staging + "/personal-skills/" + skill.name,
                                 skill.destination, backup + "/personal-skills/" + skill.name, True))
        for stage_root, target_root, backup_root, is_skill in replacements:
            mappings.append((target_root, backup_root))
            safe_parent = self._safe_directory_script(
                self.config.target_home,
                str(Path(target_root).parent),
            )
            workspace_preconditions.append(
                safe_parent
                + self._safe_directory_script(self.config.target_staging, str(Path(stage_root).parent))
                +
                "test \"$(stat -f %d {source})\" = "
                "\"$(stat -f %d {target_parent})\"\n"
                "test -d {source}\ntest ! -L {source}\n"
                "{link_check}\n"
                "if test -e {target} && test ! -L {target}; then test -d {target}; fi".format(
                    source=shlex.quote(stage_root),
                    target=shlex.quote(target_root),
                    target_parent=shlex.quote(str(Path(target_root).parent)),
                    link_check="true" if is_skill else "test ! -L " + shlex.quote(target_root),
                )
            )
            backup_workspaces.append(
                safe_parent
                + "if test -e {target} || test -L {target}; then\n"
                "  test ! -L {backup}\n"
                "  mkdir -p {backup_parent}\n"
                "  if test -L {target}; then cp -P {target} {backup}; else cp -c -Rp {target} {backup}; fi\n"
                "  verify_backup {target} {backup}\n"
                "fi".format(
                    target=shlex.quote(target_root),
                    backup=shlex.quote(backup_root),
                    backup_parent=shlex.quote(str(Path(backup_root).parent)),
                )
            )
            install_workspaces.append(
                safe_parent
                + "if test -e {target} || test -L {target}; then rm -rf {target}; fi\n"
                "mv {source} {target}".format(
                    source=shlex.quote(stage_root),
                    target=shlex.quote(target_root),
                    target_parent=shlex.quote(str(Path(target_root).parent)),
                )
            )
            rollback_workspaces.append(
                "if (\n{safe_parent}); then\n"
                "  rm -rf {target}\n"
                "  if test -L {backup}; then cp -P {backup} {target};\n"
                "  elif test -e {backup}; then cp -c -Rp {backup} {target}; fi\n"
                "fi".format(
                    safe_parent=safe_parent,
                    target=shlex.quote(target_root),
                    backup=shlex.quote(backup_root),
                )
            )
        self.state.update(pending_backup=backup,
                          message="Checking all selected workspace and conversation contents, backing up, installing, then checking again. This protected phase can take time; keep both Macs connected.")
        conversation_checks = conversation_verification_script(self.config.source_codex)
        workspace_stage_checks = []
        workspace_installed_checks = []
        for index, (staged, installed, digest) in enumerate(prepared_workspaces):
            for root, checks in ((staged, workspace_stage_checks), (installed, workspace_installed_checks)):
                checks.append("verify_workspace_%d_%s() {\nlocal workspace_digest\n%s\n}\nverify_workspace_%d_%s 2>/dev/null || { echo 'Workspace content verification failed. Keep staging and backups; Resume to refresh the copy.' >&2; exit 74; }" % (
                    index, "staged" if root == staged else "installed", tree_check(root, digest),
                    index, "staged" if root == staged else "installed"))
        begin_transaction, installed_transaction, restored_transaction, clear_transaction = transaction_commands(
            self.config.target_home, backup, mappings)
        script = """set -eu
setopt NULL_GLOB
umask 077
{backup_functions}
{target_home_chain}
test -d {home}
test ! -L {home}
test ! -L {codex}
test -f {codex}/auth.json
test ! -L {codex}/auth.json
test -f {codex}/installation_id
test ! -L {codex}/installation_id
test -d {staging}/.codex/sessions
test ! -L {staging}
test ! -L {staging}/.codex
test ! -L {staging}/home-relative
test ! -L {staging}/personal-skills
test -f {marker}
test ! -L {marker}
test "$(cat {marker})" = {migration_id}
test ! -e {staging}/.codex/auth.json
test ! -L {staging}/.codex/auth.json
test ! -e {staging}/.codex/installation_id
test ! -L {staging}/.codex/installation_id
test ! -e {backup}
{codex_process_guard}
{workspace_preconditions}
{workspace_functions}
{workspace_stage_checks}
{codex_state_function}
verify_codex_state() {{
  local workspace_digest
  {codex_state_check}
}}
{skill_stage_checks}
verify_conversations() {{
{conversation_checks}
}}
verify_conversations {staging}/.codex 2>/dev/null || {{ echo 'Conversation content verification failed. Keep staging and backups; Resume to refresh the copy.' >&2; exit 74; }}
verify_codex_state {staging}/.codex 2>/dev/null || {{ echo 'Codex state content verification failed before installation; staging was kept.' >&2; exit 74; }}
{codex_process_guard}
backup_required=$({backup_size})
backup_space {home} "$((backup_required + {reserve}))"
mkdir -p {backup}
cp -c -Rp {codex} {backup}/.codex
verify_backup {codex} {backup}/.codex
mkdir -p {backup}/home-relative
{workspace_backups}
backup_space {home} {reserve}
{backup_receipt}
auth_before=$(shasum -a 256 {codex}/auth.json | awk '{{print $1}}')
installation_before=$(shasum -a 256 {codex}/installation_id | awk '{{print $1}}')
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
      rm -rf {codex}
      cp -c -Rp {backup}/.codex {codex}
      {workspace_rollbacks}
      {rollback_verification}
    fi
    if test "$rollback_verified" = 1; then
      {restored_transaction} || rollback_verified=0
    fi
    if test "$rollback_verified" = 1; then
      {clear_transaction} || rollback_verified=0
    fi
    if test "$rollback_verified" = 1; then
      echo 'Installation failed; destination rollback was verified.' >&2
    else
      echo 'Installation failed and rollback is unconfirmed. Keep Codex closed, staging and backups intact, and contact support.' >&2
    fi
  fi
  exit "$rollback_exit_code"
}}
trap rollback EXIT
rm -rf {codex}
mv {staging}/.codex {codex}
cp -p {backup}/.codex/auth.json {codex}/auth.json
cp -p {backup}/.codex/installation_id {codex}/installation_id
{workspace_installs}
{workspace_installed_checks}
{skill_installed_checks}
verify_conversations {codex} 2>/dev/null || {{ echo 'Conversation content verification failed after installation; rollback will be attempted.' >&2; exit 74; }}
verify_codex_state {codex} 2>/dev/null || {{ echo 'Codex state content verification failed after installation; rollback will be attempted.' >&2; exit 74; }}
auth_after=$(shasum -a 256 {codex}/auth.json | awk '{{print $1}}')
installation_after=$(shasum -a 256 {codex}/installation_id | awk '{{print $1}}')
test "$auth_before" = "$auth_after"
test "$installation_before" = "$installation_after"
active=$(find {codex}/sessions -type f -name '*.jsonl' -print0 | tr -cd '\\000' | wc -c | tr -d ' ')
if test -d {codex}/archived_sessions; then
  archived=$(find {codex}/archived_sessions -type f -name '*.jsonl' -print0 | tr -cd '\\000' | wc -c | tr -d ' ')
else
  archived=0
fi
test "$active" = {expected_active}
test "$archived" = {expected_archived}
for db in {codex}/*.sqlite {codex}/sqlite/*.sqlite; do
  if test -f "$db"; then test "$(sqlite3 "$db" 'PRAGMA quick_check(1);')" = ok; fi
done
chmod 700 {codex}
{installed_transaction}
rollback_needed=0
trap - EXIT
{clear_transaction}
printf 'INSTALLED=1\\nACTIVE=%s\\nARCHIVED=%s\\nAUTH_PRESERVED=1\\nINSTALLATION_ID_PRESERVED=1\\nBACKUP_VERIFIED=1\\nCONVERSATION_CONTENT_VERIFIED=1\\nCODEX_STATE_CONTENT_VERIFIED=1\\nWORKSPACE_CONTENT_VERIFIED=1\\nWORKSPACE_ROOTS_VERIFIED={workspace_count}\\nPERSONAL_SKILLS_VERIFIED={skill_count}\\nBACKUP=%s\\n' "$active" "$archived" {backup}
""".format(
            backup_functions=BACKUP_FUNCTIONS,
            begin_transaction=begin_transaction,
            installed_transaction=installed_transaction,
            restored_transaction=restored_transaction,
            clear_transaction=clear_transaction,
            rollback_verification=rollback_checks(mappings),
            codex_process_guard=require_codex_closed_script(self.config.target_home),
            backup_size=size_command(self._backup_targets()),
            reserve=max(2 * 1024**3, int(self.state.read().get("reserve_bytes") or 0)),
            backup_receipt=verification_receipt(backup, mappings),
            home=q_home,
            codex=q_codex,
            staging=q_staging,
            backup=q_backup,
            target_home_chain=self._safe_directory_script("/", self.config.target_home),
            marker=q_marker,
            migration_id=shlex.quote(migration_id),
            expected_active=expected_active,
            expected_archived=expected_archived,
            workspace_preconditions="\n".join(workspace_preconditions),
            workspace_backups="\n".join(backup_workspaces),
            workspace_installs="\n".join(install_workspaces),
            workspace_rollbacks="\n".join(rollback_workspaces),
            skill_stage_checks="\n".join(skill_stage_checks),
            skill_installed_checks="\n".join(skill_installed_checks),
            skill_count=len(skills),
            conversation_checks=conversation_checks,
            workspace_functions=remote_tree_function(),
            codex_state_function=remote_tree_function(codex=True),
            codex_state_check=tree_check("CODEX_STATE_ROOT", codex_state_digest, codex=True).replace("CODEX_STATE_ROOT", '"$1"'),
            workspace_stage_checks="\n".join(workspace_stage_checks),
            workspace_installed_checks="\n".join(workspace_installed_checks),
            workspace_count=sum(digest is not None for _, _, digest in prepared_workspaces),
        )
        output = self.transport.run_remote(
            locked_destination_script(self.config.target_home, script), timeout=WORKSPACE_TIMEOUT
        ).stdout
        if _value(output, "INSTALLED") != "1":
            raise MigrationError("Destination installation did not produce a valid receipt")
        if _value(output, "BACKUP_VERIFIED") != "1":
            raise MigrationError("Destination backup verification receipt is missing")
        if _value(output, "CONVERSATION_CONTENT_VERIFIED") != "1":
            raise MigrationError("Conversation content verification receipt is missing")
        if _value(output, "CODEX_STATE_CONTENT_VERIFIED") != "1":
            raise MigrationError("Codex state content verification receipt is missing")
        workspace_count = sum(digest is not None for _, _, digest in prepared_workspaces)
        if (_value(output, "WORKSPACE_CONTENT_VERIFIED") != "1"
                or _value(output, "WORKSPACE_ROOTS_VERIFIED") != str(workspace_count)):
            raise MigrationError("Workspace content verification receipt is missing or mismatched")
        if skills and _value(output, "PERSONAL_SKILLS_VERIFIED") != str(len(skills)):
            raise MigrationError("Personal skill verification receipt is missing")
        active = int(_value(output, "ACTIVE") or -1)
        archived = int(_value(output, "ARCHIVED") or -1)
        if active != expected_active:
            raise MigrationError("Active conversation count mismatch after install")
        if archived != expected_archived:
            raise MigrationError("Archived conversation count mismatch after install")
        return {
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "active_sessions": active,
            "archived_sessions": archived,
            "auth_preserved": _value(output, "AUTH_PRESERVED") == "1",
            "installation_id_preserved": _value(output, "INSTALLATION_ID_PRESERVED") == "1",
            "backup": _value(output, "BACKUP"),
            "backup_verified": True,
            "conversation_content_verified": True,
            "codex_state_content_verified": True,
            "workspace_content_verified": True,
            "workspace_roots_verified": workspace_count,
            "personal_skills": [skill.as_dict() for skill in skills],
            "personal_skills_verified": len(skills),
            "source_home": self.config.source_home,
            "target_home": self.config.target_home,
        }

    @staticmethod
    def _safe_directory_script(base: str, destination: str) -> str:
        base_path = Path(base)
        destination_path = Path(destination)
        try:
            relative = destination_path.relative_to(base_path)
        except ValueError as error:
            raise MigrationError("destination path escaped its protected root") from error
        lines = [
            "test -d %s" % shlex.quote(str(base_path)),
            "test ! -L %s" % shlex.quote(str(base_path)),
        ]
        current = base_path
        for component in relative.parts:
            current = current / component
            quoted = shlex.quote(str(current))
            lines.append(
                "if test -e {path}; then test -d {path}; test ! -L {path}; "
                "else mkdir {path}; fi".format(path=quoted)
            )
        return "set -eu\n" + "\n".join(lines) + "\n"

    def compatibility_command(self) -> Optional[str]:
        return compatibility_command(self.config, self.state.read().get("path_compatibility"))


def _value(text: str, key: str) -> Optional[str]:
    prefix = key + "="
    for line in text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :]
    return None
