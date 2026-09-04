"""Browser engine lifecycle against disposable restoration fixtures."""

import threading
import copy
import unittest
from unittest.mock import patch

import test_restore as fixtures
from codex_migrate.errors import MigrationError
from codex_migrate.migration import MigrationEngine
from codex_migrate.restore import RESTORE_RUNNER
from codex_migrate.state import StateStore


class GuidedRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RestoreTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.engine = self.fixture.fixture.engine
        self.state = self.engine.state
        self.state.update(status="failed", phase="installing", recovery=self.fixture.inspection)
        self.id = self.fixture.record["id"]

    def wait(self):
        self.engine._thread.join(10)
        self.assertFalse(self.engine._thread.is_alive())

    def start(self):
        with patch("codex_migrate.restore.require_codex_closed_script", return_value=self.fixture.guard):
            self.engine.start_restore_recovery(self.id)
            self.wait()

    def test_actual_restore_resolves_recovery_not_source_migration(self):
        self.fixture.newer_work()
        self.start()
        current = self.state.read()
        self.assertEqual(current["recovery"]["status"], "restore_verified")
        self.assertTrue(current["recovery_attempt"]["resolved"])
        self.assertEqual(current["status"], "interrupted")
        self.assertEqual(current["phase"], "restored")
        self.assertFalse(current["staging_complete"])
        self.assertIsNone(current["receipt"])
        self.assertIsNone(current["pending_backup"])
        self.fixture.assert_restored(newer=True)
        with self.assertRaises(MigrationError):
            self.engine.start_restore_recovery(self.id)
        self.engine._require_recovery_resolved()

    def test_stale_confirmation_and_unverified_state_cannot_start(self):
        with patch.object(self.engine.transport, "run_remote") as remote:
            for wrong in (None, "f" * 32, [], self.id + "x"):
                with self.assertRaises(MigrationError):
                    self.engine.start_restore_recovery(wrong)
            self.state.update(recovery={"status": "no_pending_record"})
            with self.assertRaises(MigrationError):
                self.engine.start_restore_recovery(self.id)
            remote.assert_not_called()
        self.assertFalse(self.fixture.root.exists())

    def test_missing_or_malformed_saved_proof_cannot_bypass_reconciliation(self):
        for attempt in (None, {}, {"resolved": True}, "invalid"):
            self.state.update(phase="recovery_required", recovery_attempt=attempt,
                              recovery={"status": "restore_unconfirmed"})
            with patch.object(self.engine, "_start") as dispatch:
                with self.assertRaises(MigrationError):
                    self.engine.start_inspection()
                dispatch.assert_not_called()
            with patch.object(self.engine.transport, "run_remote") as remote:
                self.engine._run_recovery_check()
                remote.assert_not_called()
            self.assertEqual(self.state.read()["phase"], "recovery_required")
        self.state.update(recovery=self.fixture.inspection, recovery_attempt=None)
        self.start()
        original = self.state.read()["recovery_attempt"]
        for field in ("reference", "inspection", "proof", "outcome"):
            malformed = copy.deepcopy(original)
            malformed.pop(field)
            self.state.update(recovery_attempt=malformed)
            with self.assertRaises(MigrationError):
                self.engine._require_recovery_resolved()
        malformed = copy.deepcopy(original)
        malformed["proof"]["items"][0]["restored_matches"] = False
        self.state.update(recovery_attempt=malformed)
        with self.assertRaises(MigrationError):
            self.engine._require_recovery_resolved()
        self.state.update(recovery_attempt=original)
        self.engine._require_recovery_resolved()

    def test_checkpoint_failure_sends_no_restore_request(self):
        with patch.object(self.state, "sync_recovery_checkpoint", side_effect=OSError("fixture sync error")), \
             patch.object(self.engine.transport, "run_remote") as remote:
            with self.assertRaisesRegex(MigrationError, "checkpoint"):
                self.engine.start_restore_recovery(self.id)
            remote.assert_not_called()
        self.assertEqual(self.state.read()["recovery"]["status"], "restore_unconfirmed")
        self.assertFalse(self.fixture.root.exists())

    def test_interrupted_request_requires_check_before_retry(self):
        runner = RESTORE_RUNNER.replace("# This check runs again", "kill 9, $$;\n# This check runs again")
        with patch("codex_migrate.restore.RESTORE_RUNNER", runner):
            self.start()
        self.assertEqual(self.state.read()["recovery"]["status"], "restore_unconfirmed")
        for operation in (self.engine.start_inspection, self.engine.start_preseed,
                          self.engine.start_finalize, self.engine.resume):
            with self.assertRaises(MigrationError):
                operation()
        with self.assertRaises(MigrationError):
            self.engine.start_restore_recovery(self.id)
        self.engine.start_recovery_check()
        self.wait()
        self.assertEqual(self.state.read()["recovery"]["status"], "restore_incomplete")
        self.start()
        self.assertEqual(self.state.read()["recovery"]["status"], "restore_verified")

    def test_lost_final_reply_reconciles_without_second_mutation(self):
        runner = RESTORE_RUNNER.replace("emit({status => 'restored',", "kill 9, $$; emit({status => 'restored',")
        with patch("codex_migrate.restore.RESTORE_RUNNER", runner):
            self.start()
        self.assertFalse(self.fixture.fixture.journal.exists())
        self.assertEqual(self.state.read()["recovery"]["status"], "restore_unconfirmed")
        with patch("codex_migrate.restore.restore_recovery", side_effect=AssertionError("Must not retry mutation")):
            self.engine.start_recovery_check()
            self.wait()
        self.assertEqual(self.state.read()["recovery"]["status"], "restore_verified")

    def test_source_restart_preserves_reference_and_does_not_auto_restore(self):
        with patch.object(self.engine, "_start") as dispatch:
            self.engine.start_restore_recovery(self.id)
            dispatch.assert_called_once()
        # The destination finishes; the source app exits before publishing any
        # outcome. The durable source checkpoint still says restoring.
        self.fixture.restore()
        reopened = StateStore(str(self.state.root))
        self.engine = MigrationEngine(self.fixture.config, reopened)
        self.engine.transport = self.fixture.transport
        with patch.object(self.engine.transport, "run_remote") as remote:
            self.engine.reconcile_startup()
            remote.assert_not_called()
        self.assertEqual(reopened.read()["recovery"]["status"], "restore_unconfirmed")
        self.assertEqual(reopened.read()["recovery_attempt"]["reference"]["transaction_id"], self.id)
        self.engine.start_recovery_check()
        self.wait()
        self.assertEqual(reopened.read()["recovery"]["status"], "restore_verified")

    def test_restore_is_protected_from_duplicate_stop_and_shutdown(self):
        entered, release = threading.Event(), threading.Event()
        def held_restore(*args):
            entered.set()
            release.wait(5)
            raise MigrationError("Synthetic lost reply")
        with patch("codex_migrate.restore.restore_recovery", held_restore):
            self.engine.start_restore_recovery(self.id)
            self.assertTrue(entered.wait(5))
            try:
                for operation in (self.engine.start_recovery_check, self.engine.cancel,
                                  self.engine.pause, self.engine.shutdown,
                                  lambda: self.engine.start_restore_recovery(self.id)):
                    with self.assertRaises(MigrationError):
                        operation()
                self.assertEqual(self.state.read()["phase"], "restoring")
                self.assertEqual(self.state.read()["current_item"], "Destination backup restoration")
            finally:
                release.set()
                self.wait()

    def test_newer_work_after_restoration_check_is_not_silently_overwritten(self):
        self.start()
        path = self.fixture.home / "Git/newer.txt"
        path.write_text("latest work")
        self.engine.start_recovery_check()
        self.wait()
        self.assertEqual(self.state.read()["recovery"]["status"], "restore_changed")
        self.assertFalse(self.state.read()["recovery_attempt"]["resolved"])
        with self.assertRaises(MigrationError):
            self.engine.start_restore_recovery(self.id)
        self.assertEqual(path.read_text(), "latest work")


if __name__ == "__main__":
    unittest.main()
