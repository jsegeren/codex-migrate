"""Migration state machine: inspect, stage, pause, resume, finalize, verify."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import platform
import re
import secrets
import shlex
import subprocess
import threading
from typing import Dict, List, Optional, Sequence, Tuple

from codex_migrate.config import MigrationConfig
from codex_migrate.conversations import conversation_verification_script
from codex_migrate.errors import MigrationError
from codex_migrate.exclusions import CODEX_EXCLUDES
from codex_migrate.skills import SkillExport, discover_personal_skills, skill_verification_script
from codex_migrate.backup import BACKUP_FUNCTIONS, size_command, verification_receipt
from codex_migrate.inventory import Inventory, collect
from codex_migrate.security import redact
from codex_migrate.state import StateStore
from codex_migrate.transport import SSHTransport, TransferProcess


def codex_running() -> bool:
    result = subprocess.run(
        ["/bin/ps", "-axo", "comm="],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    return any(
        Path(line.strip()).name in ("ChatGPT", "Codex")
        for line in result.stdout.splitlines()
        if line.strip()
    )


class MigrationEngine:
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
            if self._thread and self._thread.is_alive():
                raise MigrationError("A migration action is already running")
            self.state.update(status="running", phase="inspecting",
                              message="Inspecting both Macs. Safe to stop.", error=None)
            self._start(self._run_inspection)

    def _run_inspection(self) -> None:
        self.preflight()
        self._restore_requested_stop()

    def reconcile_startup(self) -> None:
        current = self.state.read()
        if current.get("status") != "running":
            return
        if current.get("phase") == "installing":
            self.state.update(
                status="failed",
                message=(
                    "The previous process ended during installation. Destination rollback was "
                    "attempted; review the pending backup, then Resume to rebuild staging."
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
                        "Shutdown interrupted installation. Destination rollback was attempted; "
                        "review the pending backup, then Resume."
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
        remote = self.transport.check()
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
        target_codex = shlex.quote(self.config.target_codex)
        target_home = shlex.quote(self.config.target_home)
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
        self.transport.run_remote(
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

    def _transfers(self) -> List[Tuple[str, str, Sequence[str], str, bool]]:
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
            message="Staging is current. Quit Codex on both Macs, then choose Finalize.",
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
                self._safe_directory_script(self.config.target_staging, destination)
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
                "inspecting", "staging", "final_delta"
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
        if codex_running():
            self.state.update(
                status="waiting",
                phase="close_source_codex",
                message="Quit Codex on this Mac, then choose Finalize again.",
            )
            return
        remote_running = self._remote_codex_state()
        if remote_running != "CLOSED":
            self.state.update(
                status="waiting",
                phase="close_target_codex",
                message="Quit Codex on the target Mac, then choose Finalize again.",
            )
            return
        self.state.update(
            status="running",
            phase="final_delta",
            message="Refreshing the final delta while both Codex apps are closed.",
            error=None,
        )
        self._prepare_staging()
        self._copy_all()
        if self._restore_requested_stop():
            return
        if codex_running():
            self.state.update(
                status="waiting",
                phase="close_source_codex",
                message="Codex reopened on this Mac. Quit it, then choose Finalize again.",
                staging_complete=True,
            )
            return
        if self._remote_codex_state() != "CLOSED":
            self.state.update(
                status="waiting",
                phase="close_target_codex",
                message="Codex reopened on the target Mac. Quit it, then choose Finalize again.",
                staging_complete=True,
            )
            return
        self.state.update(
            status="running",
            phase="installing",
            message="Backing up the destination, installing, and verifying.",
            current_item="Destination installation",
        )
        receipt = self._install_and_verify()
        self.state.update(
            status="complete",
            phase="verified",
            message=self.completion_message(),
            current_item=None,
            bytes_staged=self.state.read().get("bytes_total", 0),
            percent=100.0,
            warning=self.completion_warning(),
            receipt=receipt,
            pending_backup=None,
            error=None,
        )

    def completion_message(self) -> str:
        return "Migration installed and verified. You may open Codex on the new Mac."

    def completion_warning(self) -> Optional[str]:
        source_user = Path(self.config.source_home).name
        target_user = Path(self.config.target_home).name
        if source_user != target_user:
            return (
                "Home-directory names differ. Run the compatibility command shown in Recovery "
                "before resuming older chats."
            )
        return None

    def _remote_codex_state(self) -> str:
        return self.transport.run_remote(
            "if ps -axo comm= | awk -F/ "
            "'$NF == \"ChatGPT\" || $NF == \"Codex\" { found=1 } "
            "END { exit found ? 0 : 1 }'; "
            "then echo OPEN; else echo CLOSED; fi\n"
        ).stdout.strip()

    def _backup_targets(self) -> List[str]:
        return [self.config.target_codex] + [
            self.config.target_home + "/" + str(Path(root).relative_to(self.config.source_home))
            for root in self.config.workspace_roots
        ] + [skill.destination for skill in self._skill_plan()]

    def _install_and_verify(self) -> Dict[str, object]:
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
                "  if test -L {target}; then cp -P {target} {backup}; else cp -c -R {target} {backup}; fi\n"
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
                "  elif test -e {backup}; then cp -c -R {backup} {target}; fi\n"
                "fi".format(
                    safe_parent=safe_parent,
                    target=shlex.quote(target_root),
                    backup=shlex.quote(backup_root),
                )
            )
        self.state.update(pending_backup=backup,
                          message="Checking conversation contents, then backing up, installing and verifying. Keep both Macs connected.")
        conversation_checks = conversation_verification_script(self.config.source_codex)
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
test ! -e {staging}/.codex/installation_id
test ! -e {backup}
if ps -axo comm= | awk -F/ '$NF == "ChatGPT" || $NF == "Codex" {{ found=1 }} END {{ exit found ? 0 : 1 }}'; then
  echo 'Codex reopened on the destination' >&2
  exit 70
fi
{workspace_preconditions}
{skill_stage_checks}
verify_conversations() {{
{conversation_checks}
}}
verify_conversations {staging}/.codex 2>/dev/null || {{ echo 'Conversation content verification failed. Keep staging and backups; Resume to refresh the copy.' >&2; exit 74; }}
backup_required=$({backup_size})
backup_space {home} "$((backup_required + {reserve}))"
mkdir -p {backup}
cp -c -R {codex} {backup}/.codex
verify_backup {codex} {backup}/.codex
mkdir -p {backup}/home-relative
{workspace_backups}
backup_space {home} {reserve}
{backup_receipt}
auth_before=$(shasum -a 256 {codex}/auth.json | awk '{{print $1}}')
installation_before=$(shasum -a 256 {codex}/installation_id | awk '{{print $1}}')
rollback_needed=1
rollback() {{
  rollback_exit_code=$?
  if test "$rollback_needed" = 1; then
    set +e
    rm -rf {codex}
    cp -c -R {backup}/.codex {codex}
    {workspace_rollbacks}
    echo 'Installation failed; destination rollback was attempted.' >&2
  fi
  exit "$rollback_exit_code"
}}
trap rollback EXIT
rm -rf {codex}
mv {staging}/.codex {codex}
cp -p {backup}/.codex/auth.json {codex}/auth.json
cp -p {backup}/.codex/installation_id {codex}/installation_id
{workspace_installs}
{skill_installed_checks}
verify_conversations {codex} 2>/dev/null || {{ echo 'Conversation content verification failed after installation; rollback will be attempted.' >&2; exit 74; }}
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
rollback_needed=0
trap - EXIT
printf 'INSTALLED=1\\nACTIVE=%s\\nARCHIVED=%s\\nAUTH_PRESERVED=1\\nINSTALLATION_ID_PRESERVED=1\\nBACKUP_VERIFIED=1\\nCONVERSATION_CONTENT_VERIFIED=1\\nPERSONAL_SKILLS_VERIFIED={skill_count}\\nBACKUP=%s\\n' "$active" "$archived" {backup}
""".format(
            backup_functions=BACKUP_FUNCTIONS,
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
        )
        output = self.transport.run_remote(script, timeout=3600).stdout
        if _value(output, "INSTALLED") != "1":
            raise MigrationError("Destination installation did not produce a valid receipt")
        if _value(output, "BACKUP_VERIFIED") != "1":
            raise MigrationError("Destination backup verification receipt is missing")
        if _value(output, "CONVERSATION_CONTENT_VERIFIED") != "1":
            raise MigrationError("Conversation content verification receipt is missing")
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
        if self.config.source_home == self.config.target_home:
            return None
        return "sudo ln -s %s %s" % (
            shlex.quote(self.config.target_home),
            shlex.quote(self.config.source_home),
        )


def _value(text: str, key: str) -> Optional[str]:
    prefix = key + "="
    for line in text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :]
    return None
