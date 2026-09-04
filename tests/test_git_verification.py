"""Disposable installation + read-only Git retry acceptance, never remote Macs."""

from copy import deepcopy
from dataclasses import replace
import fcntl
import json
import os
from pathlib import Path
import subprocess
import threading
import unittest
from unittest.mock import Mock, patch

import test_full_skills as fixtures
from codex_migrate.errors import MigrationError
from codex_migrate.git_verification import check_installed, fingerprint, validate_baseline
from codex_migrate.migration import MigrationEngine
from codex_migrate.support import diagnostic_report
from codex_migrate.workspaces import freeze_tree


class GitVerificationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.FullSkillTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.repo = self.fixture.source / "Git/main repo"
        self.repo.mkdir(parents=True)
        env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(self.fixture.source),
               "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}
        self.git_env = env
        self.git("init", "-q", str(self.repo))
        (self.repo / "work.txt").write_text("committed fixture\n")
        self.git("-C", str(self.repo), "add", "work.txt")
        self.git("-C", str(self.repo), "commit", "-qm", "fixture")
        self.fixture.config = replace(self.fixture.config, workspace_roots=[str(self.repo)]).validate()
        self.engine = self.fixture.engine = MigrationEngine(self.fixture.config, self.fixture.state)
        self.state = self.fixture.state
        self.installed = self.fixture.target / "Git/main repo"

    def git(self, *args):
        return subprocess.run(["/usr/bin/git", "-c", "user.name=Fixture", "-c",
                               "user.email=fixture@example.invalid", *args], env=self.git_env,
                              check=True, capture_output=True, timeout=15)

    def install(self):
        self.fixture.prepare()
        prepared = self.engine._prepare_install()
        baseline = self.state.read()["git_baseline"]
        self.assertEqual(prepared["git_baseline_id"], fingerprint(baseline))
        self.assertEqual(os.stat(self.state.path).st_mode & 0o777, 0o600)
        receipt = self.engine._install_and_verify(prepared)
        self.state.update(receipt=receipt, phase="path_compatibility", status="needs_attention")
        return receipt

    def finish(self, receipt):
        with patch("codex_migrate.migration.check_compatibility", return_value={"status": "mapped", "message": "Disposable fixture paths ready"}):
            self.engine._complete_installation(receipt)

    def test_actual_install_checks_destination_with_source_offline_and_never_writes(self):
        receipt = self.install()
        offline = self.fixture.root / "offline-source-git"
        (self.fixture.source / "Git").rename(offline)
        self.addCleanup(lambda: offline.rename(self.fixture.source / "Git"))
        before = freeze_tree(str(self.installed))
        self.finish(receipt)
        self.assertEqual(self.state.read()["status"], "complete", self.state.read()["git_verification"])
        self.assertEqual(self.state.read()["git_verification"]["matched"], 1)
        self.assertEqual(freeze_tree(str(self.installed)), before)
        self.assertEqual(self.state.read()["receipt"], receipt)

    def test_bound_linked_worktree_check_requires_restored_historical_paths(self):
        linked = self.fixture.source / ".codex/worktrees/task"
        self.git("-C", str(self.repo), "branch", "local-task")
        self.git("-C", str(self.repo), "worktree", "add", "-q", str(linked), "local-task")
        (linked / "work.txt").write_text("unfinished linked work\n")
        self.install()
        saved = self.state.read()
        offline = self.fixture.root / "offline-source"
        self.fixture.source.rename(offline)
        def restore_fixture():
            if self.fixture.source.is_symlink():
                self.fixture.source.unlink()
            offline.rename(self.fixture.source)
        self.addCleanup(restore_fixture)
        missing = check_installed(self.engine.config, saved, self.engine.transport, lambda: False)
        self.assertEqual(missing["status"], "needs_review")
        self.fixture.source.symlink_to(self.fixture.target)
        before = freeze_tree(str(self.installed))
        result = check_installed(self.engine.config, saved, self.engine.transport, lambda: False)
        self.assertEqual(result["status"], "verified", result)
        self.assertEqual(result["matched"], 2)
        self.assertEqual(freeze_tree(str(self.installed)), before)

    def test_changed_work_is_reported_without_reinstall_and_readonly_retry_works(self):
        receipt = self.install()
        self.finish(receipt)
        (self.installed / "work.txt").write_text("new destination work\n")
        before = freeze_tree(str(self.installed))
        self.engine.config = replace(self.engine.config, apply=False)
        with patch.object(self.engine, "_copy_all", side_effect=AssertionError("must not copy")), \
             patch.object(self.engine, "_install_and_verify", side_effect=AssertionError("must not install")), \
             patch("codex_migrate.migration.check_compatibility", return_value={"status": "mapped", "message": "Fixture"}):
            self.engine.start_git_check()
            self.engine._thread.join(20)
            self.assertFalse(self.engine._thread.is_alive())
        result = self.state.read()
        self.assertEqual(result["git_verification"]["status"], "needs_review")
        self.assertEqual(result["git_verification"]["changed"], 1)
        self.assertEqual(result["phase"], "git_verification")
        self.assertEqual(result["receipt"], receipt)
        self.assertEqual(freeze_tree(str(self.installed)), before)
        for action in (self.engine.start_preseed, self.engine.resume, self.engine.start_finalize, self.engine.start_inspection):
            with self.assertRaises(MigrationError):
                action()

    def test_receipt_is_saved_before_fallible_check(self):
        receipt = self.install()
        def interrupted(*args):
            self.assertEqual(self.state.read()["receipt"], receipt)
            raise RuntimeError("PRIVATE_REMOTE_FAILURE")
        with patch("codex_migrate.migration.check_installed", side_effect=interrupted):
            self.finish(receipt)
        self.assertEqual(self.state.read()["receipt"], receipt)
        self.assertEqual(self.state.read()["git_verification"]["status"], "unavailable")
        self.assertNotIn("PRIVATE_REMOTE_FAILURE", json.dumps(self.state.read()))

    def test_baseline_and_receipt_mismatch_never_contacts_destination(self):
        self.install()
        original = self.state.read()
        for field, replacement in (("git_baseline", None), ("migration_id", "f" * 32)):
            state = {**original, field: replacement}
            with self.subTest(field=field), self.assertRaises(MigrationError):
                check_installed(self.engine.config, state, Mock(), lambda: False)
        for field in ("target_home", "content", "attempt", "plan", "report"):
            state = deepcopy(original)
            state["git_baseline"][field] = "PRIVATE_TAMPER"
            transport = Mock()
            with self.subTest(field=field), self.assertRaises(MigrationError):
                check_installed(self.engine.config, state, transport, lambda: False)
            transport.run_remote_cancellable.assert_not_called()

    def test_missing_destination_git_is_retryable_without_losing_receipt(self):
        receipt = self.install()
        with patch.object(self.engine.transport, "run_remote_cancellable", side_effect=RuntimeError("PRIVATE_ERROR")):
            self.finish(receipt)
        self.assertEqual(self.state.read()["git_verification"]["status"], "unavailable")
        self.assertEqual(self.state.read()["receipt"], receipt)
        self.engine._run_git_check()
        self.assertEqual(self.state.read()["status"], "complete")

    def test_source_unavailable_stops_before_replacement(self):
        with patch("codex_migrate.git_verification.probe_local", side_effect=MigrationError("Unavailable")):
            with self.assertRaisesRegex(MigrationError, "stopped before replacement"):
                self.install()
        self.fixture.assert_destination_original()
        self.assertIsNone(self.state.read().get("receipt"))
        self.assertTrue(Path(self.engine.config.target_staging).exists())

    def test_source_baseline_failure_offers_the_actual_guarded_retry_path(self):
        self.fixture.prepare()
        with patch("codex_migrate.git_verification.probe_local", side_effect=MigrationError("Unavailable")):
            self.engine._guarded(self.engine._prepare_install)
        current = self.state.read()
        self.assertEqual(current["status"], "failed")
        self.assertIn("Resume", current["message"])
        self.assertIn("then Finalize", current["message"])
        with self.assertRaises(MigrationError):
            self.engine.start_finalize()
        with patch.object(self.engine, "_run_preseed") as resume:
            self.engine.resume()
            self.engine._thread.join(5)
            resume.assert_called_once()
        self.fixture.assert_destination_original()

    def test_legacy_unavailable_baseline_is_not_recreated_from_new_work(self):
        receipt = self.install()
        baseline = self.state.read()["git_baseline"]
        baseline["report"] = None
        receipt["git_baseline_id"] = fingerprint(baseline)
        self.state.update(git_baseline=baseline, receipt=receipt)
        with patch.object(self.engine.transport, "run_remote_cancellable") as remote:
            self.finish(receipt)
            remote.assert_not_called()
        self.assertEqual(self.state.read()["git_verification"]["status"], "unavailable")
        self.assertIn("source before installation", self.state.read()["git_verification"]["message"])
        self.assertEqual(self.state.read()["receipt"], receipt)

    def test_existing_source_issue_is_not_reported_as_copy_damage(self):
        self.git("-C", str(self.repo), "config", "remote.origin.promisor", "true")
        receipt = self.install()
        self.finish(receipt)
        report = self.state.read()["git_verification"]
        self.assertEqual(report["source_needs_review"], 1)
        self.assertEqual(report["changed"], 0)
        self.assertEqual(report["status"], "needs_review")

    def test_postinstall_cancel_shutdown_restart_never_offer_copy(self):
        receipt = self.install()
        started, stopped = threading.Event(), threading.Event()
        def wait_check(script, timeout, cancelled):
            started.set()
            self.assertTrue(stopped.wait(10))
            raise MigrationError("Cancelled")
        with patch.object(self.engine.transport, "run_remote_cancellable", side_effect=wait_check), \
             patch.object(self.engine.transport, "cancel_all", side_effect=stopped.set), \
             patch("codex_migrate.migration.check_compatibility", return_value={"status": "mapped", "message": "Fixture"}):
            self.engine.start_git_check()
            self.assertTrue(started.wait(10))
            self.engine.shutdown()
        self.assertFalse(self.engine._thread.is_alive())
        self.assertEqual(self.state.read()["git_verification"]["status"], "cancelled")
        self.assertEqual(self.state.read()["receipt"], receipt)
        self.state.update(git_verification={"status": "checking"})
        MigrationEngine(self.engine.config, self.state).reconcile_startup()
        self.assertEqual(self.state.read()["phase"], "git_verification")
        self.assertNotIn("Resume", self.state.read()["message"])

    def test_shutdown_at_path_to_git_handoff_does_not_launch_probe(self):
        receipt = self.install()
        handoff, release = threading.Event(), threading.Event()
        original = self.engine._run_git_check
        def delayed():
            handoff.set()
            self.assertTrue(release.wait(10))
            original()
        with patch.object(self.engine, "_run_git_check", side_effect=delayed), \
             patch.object(self.engine.transport, "cancel_all", side_effect=release.set), \
             patch.object(self.engine.transport, "run_remote_cancellable") as remote, \
             patch("codex_migrate.migration.check_compatibility", return_value={"status": "mapped", "message": "Fixture"}):
            self.engine.start_git_check()
            self.assertTrue(handoff.wait(10))
            self.engine.shutdown()
            release.set()
            self.engine._thread.join(10)
            remote.assert_not_called()
        self.assertEqual(self.state.read()["git_verification"]["status"], "cancelled")
        self.assertEqual(self.state.read()["receipt"], receipt)

    def test_older_completion_without_git_proof_reopens_needing_review(self):
        receipt = self.install()
        self.state.update(phase="verified", status="complete", git_verification={})
        self.engine.reconcile_startup()
        self.assertEqual(self.state.read()["phase"], "git_verification")
        self.assertEqual(self.state.read()["status"], "needs_attention")
        self.assertEqual(self.state.read()["receipt"], receipt)

    def test_readonly_lock_never_creates_missing_lock_or_ignores_active_writer(self):
        self.install()
        lock = self.fixture.target / ".codex-migrate-destination.lock"
        with lock.open("rb") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = check_installed(self.engine.config, self.state.read(), self.engine.transport, lambda: False)
            self.assertEqual(result["status"], "unavailable")
        saved = lock.with_name("fixture-saved-lock")
        lock.rename(saved)
        result = check_installed(self.engine.config, self.state.read(), self.engine.transport, lambda: False)
        self.assertEqual(result["status"], "unavailable")
        self.assertFalse(lock.exists())

    def test_pending_transaction_blocks_git_checks(self):
        self.install()
        journal = self.fixture.target / ".codex-migrate-transaction.json"
        journal.write_text("PRIVATE_INVALID_RECORD")
        result = check_installed(self.engine.config, self.state.read(), self.engine.transport, lambda: False)
        self.assertEqual(result["status"], "unavailable")
        self.assertNotIn("PRIVATE_INVALID_RECORD", json.dumps(result))
        self.assertEqual(journal.read_text(), "PRIVATE_INVALID_RECORD")

    def test_changed_prepared_contents_cannot_reuse_baseline(self):
        self.fixture.prepare()
        prepared = self.engine._prepare_install()
        prepared["codex_state"] = "f" * 64
        with self.assertRaisesRegex(MigrationError, "baseline"):
            self.engine._install_and_verify(prepared)
        self.fixture.assert_destination_original()

    def test_source_cancellation_cannot_be_downgraded_to_unavailable(self):
        self.fixture.prepare()
        def cancel(*args):
            self.engine._cancel_requested = True
            raise MigrationError("Cancelled")
        with patch("codex_migrate.git_verification.probe_local", side_effect=cancel), self.assertRaises(MigrationError):
            self.engine._prepare_install()
        self.assertIsNone(self.state.read().get("git_baseline"))
        self.fixture.assert_destination_original()

    def test_stop_git_during_path_precheck_never_starts_git(self):
        self.install()
        self.state.update(path_compatibility={"status": "checking"})
        self.engine.stop_git_check()
        self.assertTrue(self.engine._path_cancelled)
        self.assertTrue(self.engine._git_cancelled)
        self.assertEqual(self.state.read()["path_compatibility"]["status"], "unverified")
        self.assertEqual(self.state.read()["git_verification"]["status"], "cancelled")

    def test_empty_git_scope_is_verified_without_requiring_git_or_network(self):
        # A real selected non-Git folder still has a bound content baseline.
        for child in self.repo.iterdir():
            if child.name == ".git":
                child.rename(self.fixture.source / "unused-fixture-git-metadata")
        receipt = self.install()
        with patch.object(self.engine.transport, "run_remote_cancellable") as remote:
            self.finish(receipt)
            remote.assert_not_called()
        self.assertEqual(self.state.read()["git_verification"]["total"], 0)
        self.assertEqual(self.state.read()["status"], "complete")

    def test_private_baselines_are_excluded_from_diagnostics(self):
        self.install()
        self.finish(self.state.read()["receipt"])
        text = json.dumps(diagnostic_report(self.state.read()))
        self.assertNotIn(str(self.repo), text)
        self.assertNotIn(self.state.read()["receipt"]["git_baseline_id"], text)
        self.assertNotIn("checks", text)
        self.assertEqual(diagnostic_report(self.state.read())["current"]["git_status"], "verified")
