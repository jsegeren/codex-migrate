import tempfile
import subprocess
import shutil
import unittest
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from process_fixtures import closed_codex_script

from codex_migrate.config import MigrationConfig
from codex_migrate.inventory import Inventory, TreeSummary
from codex_migrate.migration import (
    CODEX_EXCLUDES,
    MigrationEngine,
    MigrationError,
    codex_running,
)
from codex_migrate.state import StateStore


class MigrationTests(unittest.TestCase):
    def test_process_detection_accepts_explicit_open_result(self):
        result = SimpleNamespace(stdout="OPEN\n", returncode=0)
        with patch("codex_migrate.processes.subprocess.run", return_value=result):
            self.assertTrue(codex_running())

    def test_remote_process_state_rejects_ambiguous_success_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = MigrationConfig(target="person@host.local", source_home="/Users/person",
                                     target_home="/Users/person").validate()
            engine = MigrationEngine(config, StateStore(temporary))
            for output in ("", "UNKNOWN", "CLOSED\nOPEN", "private process path"):
                with self.subTest(output=output), patch.object(engine.transport, "run_remote",
                    return_value=SimpleNamespace(stdout=output)):
                    with self.assertRaisesRegex(MigrationError, "finalization is blocked") as raised:
                        engine._remote_codex_state()
                    self.assertNotIn("private process path", str(raised.exception))

    def test_startup_reconciliation_keeps_staging_resumable(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = MigrationConfig(
                target="person@host.local",
                source_home="/Users/person",
                target_home="/Users/person",
            ).validate()
            state = StateStore(temporary)
            state.update(status="running", phase="staging", staging_complete=False)
            MigrationEngine(config, state).reconcile_startup()
            current = state.read()
            self.assertEqual(current["status"], "interrupted")
            self.assertIn("Resume", current["message"])
            self.assertFalse(current["staging_complete"])

    def test_startup_reconciliation_flags_interrupted_install(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = MigrationConfig(
                target="person@host.local",
                source_home="/Users/person",
                target_home="/Users/person",
            ).validate()
            state = StateStore(temporary)
            state.update(
                status="running",
                phase="installing",
                staging_complete=True,
                pending_backup="/Users/person/Codex-Migrate-Backup-test",
            )
            MigrationEngine(config, state).reconcile_startup()
            current = state.read()
            self.assertEqual(current["status"], "failed")
            self.assertFalse(current["staging_complete"])
            self.assertIn("rollback is unconfirmed", current["message"])
            self.assertNotIn("rollback was attempted", current["message"])
            self.assertEqual(
                current["pending_backup"],
                "/Users/person/Codex-Migrate-Backup-test",
            )

    def test_shutdown_cancels_transport_and_preserves_resumable_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = MigrationConfig(
                target="person@host.local",
                source_home="/Users/person",
                target_home="/Users/person",
            ).validate()
            state = StateStore(temporary)
            state.update(status="running", phase="staging")
            engine = MigrationEngine(config, state)

            class FakeTransport:
                cancelled = False

                def cancel_all(self):
                    self.cancelled = True

            transport = FakeTransport()
            engine.transport = transport
            engine.shutdown()
            self.assertTrue(transport.cancelled)
            self.assertEqual(state.read()["status"], "interrupted")
            self.assertIn("Resume", state.read()["message"])

    def test_authentication_is_always_excluded(self):
        self.assertIn("/auth.json", CODEX_EXCLUDES)
        self.assertIn("/installation_id", CODEX_EXCLUDES)

    def test_finalize_is_rejected_before_successful_staging(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = MigrationConfig(
                target="person@host.local",
                source_home="/Users/person",
                target_home="/Users/person",
            ).validate()
            engine = MigrationEngine(config, StateStore(temporary))
            with self.assertRaises(MigrationError):
                engine.start_finalize()

    def test_staging_uses_owner_marker_and_removes_protected_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            source_home = str(Path(temporary).resolve())
            config = MigrationConfig(
                target="person@host.local",
                source_home=source_home,
                target_home="/Users/person",
            ).validate()
            state = StateStore(config.state_dir)
            engine = MigrationEngine(config, state)
            scripts = []

            class FakeTransport:
                def run_remote(self, script, timeout=60):
                    scripts.append(script)
                    return SimpleNamespace(stdout="")

            engine.transport = FakeTransport()
            engine._prepare_staging()
            self.assertRegex(state.read()["migration_id"], r"^[0-9a-f]{32}$")
            self.assertIn(".codex-migrate-owner", scripts[0])
            self.assertIn("rm -f", scripts[0])
            self.assertIn(".codex/auth.json", scripts[0])

    def test_compatibility_command_is_generated_only_for_different_homes(self):
        with tempfile.TemporaryDirectory() as temporary:
            same = MigrationConfig(
                target="person@host.local",
                source_home="/Users/person",
                target_home="/Users/person",
            ).validate()
            same_engine = MigrationEngine(same, StateStore(temporary + "/same"))
            self.assertIsNone(same_engine.compatibility_command())

            different = MigrationConfig(
                target="new@host.local",
                source_home="/Users/old",
                target_home="/Users/new",
            ).validate()
            engine = MigrationEngine(different, StateStore(temporary + "/different"))
            self.assertIsNone(engine.compatibility_command())
            engine.state.update(path_compatibility={"status": "missing", "source_home": "/Users/old", "target_home": "/Users/new"})
            self.assertTrue(engine.compatibility_command().startswith("sudo /usr/bin/env "))
            self.assertNotIn("ln -s", engine.compatibility_command())

    def test_same_basename_in_different_roots_still_requires_path_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = MigrationConfig(target="person@host", source_home="/Volumes/old/person", target_home="/Users/person").validate()
            engine = MigrationEngine(config, StateStore(temporary))
            self.assertIsNotNone(engine.completion_warning())
            self.assertIsNone(engine.compatibility_command())

    def test_post_install_path_failure_keeps_receipt_and_requires_recheck(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = MigrationConfig(target="person@host", source_home="/Users/old", target_home="/Users/person").validate()
            state = StateStore(temporary)
            engine = MigrationEngine(config, state)
            receipt = {key: True for key in ("backup_verified", "auth_preserved", "installation_id_preserved", "conversation_content_verified", "codex_state_content_verified", "workspace_content_verified")}
            receipt.update(backup="/Users/person/backup", source_home=config.source_home, target_home=config.target_home)
            for status in ("missing", "unverified", "conflict", "unsupported"):
                report = {"status": status, "message": "Fixture path check " + status}
                with patch("codex_migrate.migration.check_compatibility", return_value=report):
                    engine._complete_installation(receipt)
                self.assertEqual(state.read()["receipt"], receipt)
                self.assertEqual(state.read()["status"], "needs_attention")
                self.assertEqual(state.read()["phase"], "path_compatibility")
                self.assertIsNone(state.read()["pending_backup"])
                for operation in (engine.start_inspection, engine.start_preseed, engine.start_finalize):
                    with self.assertRaisesRegex(MigrationError, "Installation is already verified"):
                        operation()
            with patch("codex_migrate.migration.check_compatibility", return_value={"status": "mapped", "message": "Fixture verified"}):
                engine.start_path_check()
                engine._thread.join(5)
            self.assertEqual(state.read()["status"], "needs_attention")
            self.assertEqual(state.read()["git_verification"]["status"], "unavailable")
            self.assertIn("baseline", state.read()["git_verification"]["message"])
            self.assertEqual(state.read()["receipt"], receipt)
            self.assertIsNone(state.read()["warning"])
            with patch("codex_migrate.migration.check_compatibility", return_value={"status": "conflict", "message": "Changed alias"}):
                engine._run_path_check()
            self.assertEqual(state.read()["status"], "needs_attention")
            self.assertEqual(state.read()["receipt"], receipt)
            for bad in (None, {}, {"backup_verified": True}, dict(receipt, source_home="/Users/other")):
                state.update(receipt=bad)
                with patch("codex_migrate.migration.check_compatibility", return_value={"status": "mapped", "message": "Fixture verified"}):
                    engine._run_path_check()
                self.assertEqual(state.read()["status"], "needs_attention")
                self.assertIn("Installation evidence", state.read()["message"])

    def test_interrupted_path_check_reopens_without_losing_installation(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = MigrationConfig(target="person@host", source_home="/Users/old", target_home="/Users/person").validate()
            state = StateStore(temporary)
            receipt = {"backup_verified": True}
            state.update(status="needs_attention", phase="path_compatibility", receipt=receipt,
                         path_compatibility={"status": "checking"})
            engine = MigrationEngine(config, state)
            engine.reconcile_startup()
            self.assertEqual(state.read()["path_compatibility"]["status"], "unverified")
            self.assertEqual(state.read()["receipt"], receipt)

    def test_path_check_shutdown_cancels_and_suppresses_late_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = MigrationConfig(target="person@host", source_home="/Users/old", target_home="/Users/person").validate()
            state = StateStore(temporary)
            state.update(status="needs_attention", phase="path_compatibility", receipt={"fixture": True})
            engine = MigrationEngine(config, state)
            entered, release = threading.Event(), threading.Event()
            def held(*args):
                entered.set()
                self.assertTrue(release.wait(5))
                return {"status": "mapped", "message": "Late fixture result"}
            with patch("codex_migrate.migration.check_compatibility", held), patch.object(engine.transport, "cancel_all", side_effect=release.set) as cancel:
                engine.start_path_check()
                self.assertTrue(entered.wait(5))
                engine.shutdown()
                cancel.assert_called_once()
                self.assertFalse(engine._thread.is_alive())
            self.assertEqual(state.read()["path_compatibility"]["status"], "unverified")
            self.assertEqual(state.read()["receipt"], {"fixture": True})

    def test_automatic_post_install_path_check_reaps_real_child_on_shutdown(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = MigrationConfig(target="person@host", source_home="/Users/old", target_home="/Users/person").validate()
            state = StateStore(temporary)
            engine = MigrationEngine(config, state)
            spawned = threading.Event()
            real_spawn, children = subprocess.Popen, []
            def spawn(*args, **kwargs):
                child = real_spawn(["/bin/sleep", "30"], **kwargs)
                children.append(child)
                spawned.set()
                return child
            with patch.object(engine.transport, "machine_guard", return_value=""), patch("codex_migrate.transport.subprocess.Popen", spawn):
                engine._start(lambda: engine._complete_installation({"fixture": True}))
                self.assertTrue(spawned.wait(5))
                engine.shutdown()
            self.assertFalse(engine._thread.is_alive())
            self.assertEqual(engine.transport._active_remote, [])
            for child in children:
                self.assertIsNotNone(child.poll())
            self.assertEqual(state.read()["path_compatibility"]["status"], "unverified")
            self.assertEqual(state.read()["receipt"], {"fixture": True})

    def test_safe_stop_is_not_overwritten_by_transfer_exit(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = MigrationConfig(
                target="person@host.local",
                source_home="/Users/person",
                target_home="/Users/person",
            ).validate()
            state = StateStore(temporary)
            engine = MigrationEngine(config, state)
            state.update(migration_id="a" * 32)
            engine._cancel_requested = True
            state.update(status="cancelled", message="Stopped safely", error=None)

            def fail():
                raise RuntimeError("rsync exited with status 15")

            engine._guarded(fail)
            self.assertEqual(state.read()["status"], "cancelled")
            self.assertEqual(state.read()["message"], "Stopped safely")
            self.assertIsNone(state.read()["error"])

    def test_pause_refuses_to_claim_installation_is_paused(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = MigrationConfig(
                target="person@host.local",
                source_home="/Users/person",
                target_home="/Users/person",
            ).validate()
            state = StateStore(temporary)
            state.update(status="running", phase="installing")
            engine = MigrationEngine(config, state)
            with self.assertRaises(MigrationError):
                engine.pause()

    def test_install_script_backs_up_and_exactly_syncs_workspaces(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = MigrationConfig(
                target="person@host.local",
                source_home="/Users/source",
                target_home="/Users/person",
                workspace_roots=["/Users/source/Git"],
            ).validate()
            state = StateStore(temporary)
            state.update(migration_id="c" * 32)
            engine = MigrationEngine(config, state)
            scripts = []

            class FakeTransport:
                def run_remote(self, script, timeout=60):
                    scripts.append(script)
                    return SimpleNamespace(
                        stdout=(
                            "INSTALLED=1\nACTIVE=1\nARCHIVED=1\n"
                            "AUTH_PRESERVED=1\nINSTALLATION_ID_PRESERVED=1\n"
                            "BACKUP_VERIFIED=1\n"
                            "CONVERSATION_CONTENT_VERIFIED=1\n"
                            "CODEX_STATE_CONTENT_VERIFIED=1\n"
                            "WORKSPACE_CONTENT_VERIFIED=1\nWORKSPACE_ROOTS_VERIFIED=1\n"
                            "BACKUP=/Users/person/backup\n"
                        )
                    )

            engine.transport = FakeTransport()
            engine.inventory = lambda: Inventory(
                platform="Darwin",
                source_home="/Users/source",
                codex_present=True,
                active_sessions=TreeSummary("sessions", 1, 1, True),
                archived_sessions=TreeSummary("archived", 1, 1, True),
                codex_bytes=1,
                workspace_roots=[],
                git_repositories=1,
                unreadable_paths=[],
            )
            with patch("codex_migrate.migration.conversation_verification_script", return_value="return 0"), \
                 patch("codex_migrate.migration.require_source_storage"), \
                 patch("codex_migrate.migration.require_project_storage"), \
                 patch("codex_migrate.git_verification.source_plan", return_value={"roots": ["/Users/source/Git"], "repositories": []}), \
                 patch("codex_migrate.migration.freeze_tree", return_value="a" * 64):
                receipt = engine._install_and_verify()
            self.assertTrue(receipt["auth_preserved"])
            self.assertIn("cp -c -Rp /Users/person/Git", scripts[0])
            self.assertIn("mv /Users/person/Codex-Migrate-Staging/.codex", scripts[0])
            self.assertIn("mv /Users/person/Codex-Migrate-Staging/home-relative/Git", scripts[0])
            self.assertIn("cp -p", scripts[0])
            syntax = subprocess.run(
                ["/bin/zsh", "-n"],
                input=scripts[0],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(syntax.returncode, 0, syntax.stderr)

    def test_local_apfs_install_preserves_target_identity_and_rollback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source_home = root / "Source Home"
            target_home = root / "Target Home"
            source_codex = source_home / ".codex"
            target_codex = target_home / ".codex"
            source_workspace = source_home / "My Projects"
            target_workspace = target_home / "My Projects"
            stage = target_home / "Codex-Migrate-Staging"

            (source_codex / "sessions/2026/01/01").mkdir(parents=True)
            (source_codex / "sessions/2026/01/01/chat.jsonl").write_text(
                "{}\n", encoding="utf-8"
            )
            source_workspace.mkdir(parents=True)
            (source_workspace / "unfinished.txt").write_text("source", encoding="utf-8")
            target_codex.mkdir(parents=True)
            (target_codex / "auth.json").write_text("new-auth", encoding="utf-8")
            (target_codex / "installation_id").write_text("new-install", encoding="utf-8")
            (target_codex / "destination-only.txt").write_text("old", encoding="utf-8")
            target_workspace.mkdir(parents=True)
            (target_workspace / "destination-only.txt").write_text("old", encoding="utf-8")

            shutil.copytree(source_codex, stage / ".codex")
            shutil.copytree(source_workspace, stage / "home-relative/My Projects")

            config = MigrationConfig(
                target="person@host.local",
                source_home=str(source_home),
                target_home=str(target_home),
                workspace_roots=[str(source_workspace)],
            ).validate()
            state = StateStore(config.state_dir)
            state.update(migration_id="b" * 32)
            (stage / ".codex-migrate-owner").write_text("%s\n" % ("b" * 32))
            engine = MigrationEngine(config, state)

            class LocalTransport:
                def run_remote(self, script, timeout=60):
                    result = subprocess.run(
                        ["/bin/zsh", "-s"],
                        input=closed_codex_script(script),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=timeout,
                        check=False,
                    )
                    if result.returncode:
                        raise RuntimeError(
                            result.stderr
                            or result.stdout
                            or "local migration script failed (%d)" % result.returncode
                        )
                    return result

            engine.transport = LocalTransport()
            receipt = engine._install_and_verify()

            self.assertEqual((target_codex / "auth.json").read_text(), "new-auth")
            self.assertEqual((target_codex / "installation_id").read_text(), "new-install")
            self.assertTrue((target_codex / "sessions/2026/01/01/chat.jsonl").is_file())
            self.assertFalse((target_codex / "destination-only.txt").exists())
            self.assertEqual((target_workspace / "unfinished.txt").read_text(), "source")
            backup = Path(receipt["backup"])
            self.assertEqual((backup / ".codex/destination-only.txt").read_text(), "old")
            self.assertEqual(
                (backup / "home-relative/My Projects/destination-only.txt").read_text(),
                "old",
            )

    def test_failed_install_automatically_restores_codex_and_workspace(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source_home = root / "source"
            target_home = root / "target"
            source_codex = source_home / ".codex"
            target_codex = target_home / ".codex"
            source_workspace = source_home / "Git"
            target_workspace = target_home / "Git"
            stage = target_home / "Codex-Migrate-Staging"

            (source_codex / "sessions").mkdir(parents=True)
            (source_codex / "sessions/chat.jsonl").write_text("{}\n", encoding="utf-8")
            (source_codex / "state_5.sqlite").write_text("not a database", encoding="utf-8")
            source_workspace.mkdir(parents=True)
            (source_workspace / "new.txt").write_text("new", encoding="utf-8")
            target_codex.mkdir(parents=True)
            (target_codex / "auth.json").write_text("target-auth", encoding="utf-8")
            (target_codex / "installation_id").write_text("target-id", encoding="utf-8")
            (target_codex / "old.txt").write_text("old-codex", encoding="utf-8")
            target_workspace.mkdir(parents=True)
            (target_workspace / "old.txt").write_text("old-workspace", encoding="utf-8")
            shutil.copytree(source_codex, stage / ".codex")
            shutil.copytree(source_workspace, stage / "home-relative/Git")

            config = MigrationConfig(
                target="person@host.local",
                source_home=str(source_home),
                target_home=str(target_home),
                workspace_roots=[str(source_workspace)],
            ).validate()
            state = StateStore(config.state_dir)
            state.update(migration_id="d" * 32)
            (stage / ".codex-migrate-owner").write_text("%s\n" % ("d" * 32))
            engine = MigrationEngine(config, state)

            class LocalTransport:
                def run_remote(self, script, timeout=60):
                    result = subprocess.run(
                        ["/bin/zsh", "-s"],
                        input=closed_codex_script(script),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=timeout,
                        check=False,
                    )
                    if result.returncode:
                        raise RuntimeError(result.stderr or "injected install failure")
                    return result

            engine.transport = LocalTransport()
            with self.assertRaises(RuntimeError):
                engine._install_and_verify()

            self.assertEqual((target_codex / "auth.json").read_text(), "target-auth")
            self.assertEqual((target_codex / "old.txt").read_text(), "old-codex")
            self.assertEqual((target_workspace / "old.txt").read_text(), "old-workspace")
            self.assertFalse((target_workspace / "new.txt").exists())
            self.assertTrue(Path(state.read()["pending_backup"]).is_dir())


if __name__ == "__main__":
    unittest.main()
