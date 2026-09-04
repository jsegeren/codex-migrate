"""Disposable local browser-engine transactions; SSH never runs in these tests."""

import os
from pathlib import Path
import platform
import shlex
import subprocess
import time
import unittest
from unittest.mock import patch

import test_full_skills as fixtures
from codex_migrate.component_migration import ComponentMigrationEngine
from codex_migrate.migration import MigrationError
from codex_migrate.state import StateStore
from codex_migrate.transport import TransferProcess


@unittest.skipUnless(platform.system() == "Darwin", "APFS browser-engine fixtures")
class ComponentMigrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.FullSkillTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.engine = ComponentMigrationEngine(self.fixture.config, self.fixture.state, ["personal-skills"])
        self.fixture.engine = self.engine
        self.fixture.config = self.engine.config
        self.prefix = ""
        self.rate_limit = None
        owner = self
        self.copied_sources = []

        class LocalTransport:
            def check(self):
                return "USER=newperson\nHOME=%s\nFILESYSTEM=apfs\n" % owner.fixture.target

            def run_remote(self, script, timeout=60):
                result = subprocess.run(
                    ["/bin/zsh", "-s"], input="ps() { return 0; }\n" + owner.prefix + script,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout,
                )
                if result.returncode:
                    raise RuntimeError("Fixture command failed (%d): %s" % (result.returncode, result.stderr))
                return result

            def rsync_process(self, source, destination, excludes=(), copy_links=False):
                owner.copied_sources.append(source)
                args = ["/usr/bin/rsync", "-aE", "--partial", "--delete-after"]
                if owner.rate_limit:
                    args.append("--bwlimit=%d" % owner.rate_limit)
                if copy_links:
                    args.append("--copy-links")
                for pattern in excludes:
                    args.extend(["--exclude", pattern])
                return TransferProcess(args + [source + "/", destination + "/"])

            def remote_bytes(self, path):
                if not Path(path).exists():
                    return 0
                result = subprocess.run(["/usr/bin/du", "-sk", path], capture_output=True, text=True, check=True)
                return int(result.stdout.split()[0]) * 1024

            def remote_free_bytes(self, path):
                return 1024**4

            def route(self):
                return "Disposable local fixture — SSH disabled"

            def cancel_all(self):
                pass

        self.transport = LocalTransport()
        self.engine.transport = self.transport

    def finalize(self):
        with patch("codex_migrate.migration.codex_running", return_value=False):
            self.engine._run_finalize()

    def test_stage_finalize_only_skills_preserves_codex_and_full_staging(self):
        full_stage = self.fixture.target / "Codex-Migrate-Staging"
        full_stage.mkdir()
        (full_stage / "keep.txt").write_text("existing full migration")
        self.engine._run_preseed()
        state = self.engine.state.read()
        self.assertEqual(state["status"], "ready_to_finalize")
        self.assertEqual(len(state["inventory"]["skill_exports"]), 1)
        self.assertEqual(self.copied_sources, [str(self.fixture.skill)])
        self.assertFalse((Path(self.engine.config.target_staging) / ".codex").exists())
        self.fixture.assert_destination_original()
        self.finalize()
        state = self.engine.state.read()
        self.assertEqual(state["status"], "complete")
        self.assertEqual(state["receipt"]["skills_verified"], 1)
        self.assertIsNone(state["warning"])
        self.assertIsNone(self.engine.compatibility_command())
        self.assertEqual((self.fixture.target / ".codex/old.txt").read_text(), "old Codex state")
        self.assertEqual((self.fixture.target / ".codex/auth.json").read_text(), "destination fixture login")
        self.assertEqual((full_stage / "keep.txt").read_text(), "existing full migration")
        self.assertEqual((self.fixture.destination_skill / "SKILL.md").read_text(), "current skill")

    def test_restart_reuses_owned_staging_and_does_not_resume_install_automatically(self):
        self.engine._run_preseed()
        before = self.engine.state.read()
        staged = self.engine.config.target_staging
        self.engine.state.update(status="running", phase="staging")
        restarted = ComponentMigrationEngine(self.engine.config, self.engine.state, ["personal-skills"])
        restarted.transport = self.transport
        restarted.reconcile_startup()
        self.assertEqual(restarted.state.read()["status"], "interrupted")
        restarted._run_preseed()
        self.assertEqual(restarted.config.target_staging, staged)
        self.assertEqual(restarted.state.read()["migration_id"], before["migration_id"])
        self.assertEqual(restarted.state.read()["status"], "ready_to_finalize")
        self.fixture.assert_destination_original()

    def test_post_install_corruption_rolls_back_only_selected_skills(self):
        self.engine._run_preseed()
        self.prefix = "mv() { command mv \"$@\"; if test \"$2\" = %s; then printf corrupt > %s; fi; }\n" % (
            shlex.quote(str(self.fixture.destination_skill)),
            shlex.quote(str(self.fixture.destination_skill / "SKILL.md")),
        )
        self.engine._guarded(self.finalize)
        self.assertEqual(self.engine.state.read()["status"], "failed")
        self.assertTrue(Path(self.engine.state.read()["pending_backup"]).is_dir())
        self.fixture.assert_destination_original()

    def test_scope_change_requires_restaging_even_after_restart(self):
        self.engine._run_preseed()
        new_skill = self.fixture.skill.parent / "new-skill"
        new_skill.mkdir()
        (new_skill / "SKILL.md").write_text("new")
        restarted = ComponentMigrationEngine(self.engine.config, self.engine.state, ["personal-skills"])
        restarted.transport = self.transport
        with self.assertRaisesRegex(MigrationError, "selection changed since staging"):
            restarted._run_finalize()
        self.fixture.assert_destination_original()

    def test_foreign_staging_marker_is_not_adopted(self):
        stage = Path(self.engine.config.target_staging)
        stage.mkdir()
        (stage / ".codex-migrate-owner").write_text("someone else's staging")
        (stage / "keep.txt").write_text("keep")
        with self.assertRaises(RuntimeError):
            self.engine._run_preseed()
        self.assertEqual((stage / "keep.txt").read_text(), "keep")
        self.fixture.assert_destination_original()

    def test_workspace_skill_export_does_not_copy_repository(self):
        project = self.fixture.source / "Git/project"
        skill = project / ".agents/skills/project-tool"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("project skill")
        (project / "not-a-skill.txt").write_text("private project")
        (self.fixture.target / "Git/project").mkdir(parents=True)
        from dataclasses import replace
        config = replace(self.fixture.config, workspace_roots=[str(project)])
        state = StateStore(str(self.fixture.source / "project-test-state"))
        self.engine = ComponentMigrationEngine(config, state, ["workspace-skills"])
        self.engine.transport = self.transport
        self.engine._run_preseed()
        self.finalize()
        self.assertEqual(self.copied_sources, [str(skill), str(skill)])  # staging + final delta
        self.assertFalse((self.fixture.target / "Git/project/not-a-skill.txt").exists())
        self.assertEqual((self.fixture.target / "Git/project/.agents/skills/project-tool/SKILL.md").read_text(), "project skill")
        self.fixture.assert_destination_original()

    def check_inflight_stop_and_resume(self, action, expected_status):
        (self.fixture.skill / "early-fixture.bin").write_bytes(b"y" * (64 * 1024))
        (self.fixture.skill / "large-fixture.bin").write_bytes(b"x" * (2 * 1024**2))
        self.rate_limit = 128
        self.engine.start_preseed()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            transfer = self.engine._process
            if transfer and transfer.process and transfer.process.poll() is None:
                staged_files = Path(self.engine.config.target_staging) / "items"
                if any(path.is_file() and path.stat().st_size >= 32768
                       for path in staged_files.rglob("*")):
                    break
            time.sleep(0.02)
        else:
            self.engine.shutdown()
            self.fail("No live rsync transfer with staged file bytes became available")
        try:
            getattr(self.engine, action)()
            self.engine._thread.join(timeout=10)
            self.assertFalse(self.engine._thread.is_alive())
            self.assertIsNotNone(transfer.process.poll())
            self.assertEqual(self.engine.state.read()["status"], expected_status)
            marker = self.engine.state.read()["migration_id"]
            self.fixture.assert_destination_original()
            self.rate_limit = None
            self.engine.resume()
            self.engine._thread.join(timeout=10)
            self.assertFalse(self.engine._thread.is_alive())
            self.assertEqual(self.engine.state.read()["status"], "ready_to_finalize")
            self.assertEqual(self.engine.state.read()["migration_id"], marker)
            self.fixture.assert_destination_original()
        finally:
            if self.engine._thread and self.engine._thread.is_alive():
                self.engine.shutdown()

    def test_actual_inflight_rsync_pause_and_resume(self):
        self.check_inflight_stop_and_resume("pause", "paused")

    def test_actual_inflight_rsync_safe_stop_and_resume(self):
        self.check_inflight_stop_and_resume("cancel", "cancelled")


if __name__ == "__main__":
    unittest.main()
