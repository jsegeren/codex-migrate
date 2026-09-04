"""No real SSH or account data: reconnect verification uses disposable APFS."""

from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_restore as fixtures
import test_destination_lock as locks
from codex_migrate.errors import MigrationError
from codex_migrate.recovery import recovery_reference
from codex_migrate.reconciliation import reconcile_recovery, _validate_result
from codex_migrate.restore import RESTORE_RUNNER


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RestoreTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.reference = recovery_reference(str(self.fixture.home), self.fixture.inspection)

    def check(self, reference=None):
        return reconcile_recovery(replace(self.fixture.config, apply=False), self.fixture.transport,
                                  reference or self.reference)

    def filesystem_state(self):
        paths = [self.fixture.home, *self.fixture.home.rglob("*")]
        return {str(p): (p.lstat().st_ino, p.lstat().st_mode, p.lstat().st_size, p.lstat().st_mtime_ns)
                for p in paths}

    def test_lost_final_reply_is_verified_without_second_restore(self):
        self.fixture.newer_work()
        runner = RESTORE_RUNNER.replace("emit({status => 'restored',", "kill 9, $$; emit({status => 'restored',")
        with self.assertRaises(MigrationError):
            self.fixture.restore(runner)
        self.assertFalse(self.fixture.fixture.journal.exists())
        before = self.filesystem_state()
        report = self.check()
        self.assertEqual(report["status"], "restore_verified")
        self.assertFalse(report["pending_cleanup"])
        self.assertEqual(report["inspected_items"], 2)
        self.assertEqual(self.filesystem_state(), before)
        self.assertNotIn("backup_digest", json.dumps(report))
        self.assertNotIn("fixture-auth", json.dumps(report))
        self.assertIn("does not complete", report["message"])
        # Even a repeated explicit internal apply does not restore again after
        # the journal disappeared. The read-only result is the way to reconcile.
        with self.assertRaises(MigrationError):
            self.fixture.restore()
        self.assertEqual(self.filesystem_state(), before)

    def test_completed_but_pending_cleanup_is_not_fully_resolved(self):
        runner = RESTORE_RUNNER.replace("unlink(filesystem_path($journal)) or fail();", "kill 9, $$;")
        with self.assertRaises(MigrationError):
            self.fixture.restore(runner)
        before = self.filesystem_state()
        report = self.check()
        self.assertEqual(report["status"], "restore_pending_cleanup")
        self.assertTrue(report["pending_cleanup"])
        self.assertEqual(self.filesystem_state(), before)
        self.assertTrue(self.fixture.fixture.journal.exists())
        self.fixture.restore()
        self.assertEqual(self.check()["status"], "restore_verified")

    def test_incomplete_restore_with_or_without_plan_is_not_completed(self):
        self.assertEqual(self.check()["status"], "restore_incomplete")
        self.assertFalse(self.fixture.root.exists())
        runner = RESTORE_RUNNER.replace("# This check runs again", "kill 9, $$;\n# This check runs again")
        with self.assertRaises(MigrationError):
            self.fixture.restore(runner)
        before = self.filesystem_state()
        self.assertEqual(self.check()["status"], "restore_incomplete")
        self.assertEqual(self.filesystem_state(), before)
        self.fixture.restore()
        self.assertEqual(self.check()["status"], "restore_verified")

    def test_missing_pending_record_and_no_receipt_is_not_success(self):
        journal = self.fixture.fixture.journal
        journal.rename(self.fixture.home / "fixture-journal-kept")
        before = self.filesystem_state()
        self.assertEqual(self.check()["status"], "restore_unconfirmed")
        self.assertEqual(self.filesystem_state(), before)

    def test_actual_newer_work_after_completion_is_reported_not_reverted(self):
        self.fixture.newer_work()
        self.fixture.restore()
        active = self.fixture.home / "Git/after-restore.txt"
        active.write_text("latest fixture work")
        before = self.filesystem_state()
        report = self.check()
        self.assertEqual(report["status"], "restore_changed")
        self.assertFalse(report["items"][1]["restored_matches"])
        self.assertTrue(report["items"][1]["preserved_matches"])
        self.assertEqual(active.read_text(), "latest fixture work")
        self.assertEqual(self.filesystem_state(), before)

    def test_missing_preserved_work_is_not_a_verified_restoration(self):
        self.fixture.newer_work()
        self.fixture.restore()
        saved = self.fixture.root / "current/0"
        saved.rename(self.fixture.home / "preserved-fixture-kept")
        report = self.check()
        self.assertEqual(report["status"], "restore_changed")
        self.assertFalse(report["items"][0]["preserved_matches"])
        self.assertFalse(report["items"][0]["preserved_present"])
        self.assertTrue(report["items"][0]["preserved_expected"])
        self.assertTrue(report["items"][0]["restored_matches"])
        self.assertFalse(saved.exists())

    def test_changed_login_after_restore_is_not_replaced(self):
        self.fixture.restore()
        auth = self.fixture.home / ".codex/auth.json"
        auth.write_text("newest synthetic login")
        self.assertEqual(self.check()["status"], "restore_changed")
        self.assertEqual(auth.read_text(), "newest synthetic login")

    def test_other_pending_transaction_is_not_resolved_by_old_receipt(self):
        self.fixture.restore()
        record = json.loads(json.dumps(self.fixture.record))
        record["id"] = "f" * 32
        # Only synthetic owner-only evidence. Do not inspect this other scope.
        record["scope"][0]["original"] = "/PRIVATE-OUTSIDE-SCOPE"
        journal = self.fixture.fixture.journal
        journal.write_text(json.dumps(record))
        journal.chmod(0o600)
        before = self.filesystem_state()
        report = self.check()
        self.assertEqual(report, {"status": "different_transaction", "inspected_items": 0,
                                 "message": report["message"]})
        self.assertNotIn("PRIVATE", json.dumps(report))
        self.assertEqual(self.filesystem_state(), before)

    def test_held_writer_returns_busy_without_reading_private_records(self):
        holder = locks.DestinationLockTests()
        holder.setUp()
        self.addCleanup(holder.doCleanups)
        # The ordinary writer correctly refuses a pre-existing journal. Hold
        # its lock first, then inject synthetic pending evidence while it runs.
        self.fixture.fixture.journal.rename(self.fixture.home / "fixture-journal-kept")
        holder.hold(home=self.fixture.home)
        self.fixture.fixture.journal.write_text("PRIVATE broken journal")
        self.assertEqual(self.check()["status"], "busy")

    def test_missing_lock_never_gets_recreated(self):
        lock = self.fixture.home / ".codex-migrate-destination.lock"
        lock.unlink()
        with self.assertRaises(MigrationError):
            self.check()
        self.assertFalse(lock.exists())

    def test_damaged_backup_plan_ready_and_completion_fail_closed(self):
        self.fixture.restore()
        for path in (self.fixture.backup / ".codex/old.txt", self.fixture.root / "plan.json",
                     self.fixture.root / "ready.json", self.fixture.root / "complete.json"):
            with self.subTest(path=path.name):
                original = path.read_bytes()
                path.write_bytes(b"PRIVATE corrupt fixture")
                before = self.filesystem_state()
                with self.assertRaises(MigrationError) as error:
                    self.check()
                self.assertNotIn("PRIVATE", str(error.exception))
                self.assertEqual(self.filesystem_state(), before)
                path.write_bytes(original)
        self.assertEqual(self.check()["status"], "restore_verified")

    def test_missing_ready_is_not_repaired_from_completion(self):
        self.fixture.restore()
        ready = self.fixture.root / "ready.json"
        ready.rename(self.fixture.root / "ready-kept.json")
        with self.assertRaises(MigrationError):
            self.check()
        self.assertFalse(ready.exists())

    def test_linked_evidence_cannot_read_other_files(self):
        self.fixture.restore()
        path = self.fixture.root / "complete.json"
        saved = self.fixture.root / "complete-kept.json"
        path.rename(saved)
        path.symlink_to(saved)
        with self.assertRaises(MigrationError):
            self.check()
        self.assertTrue(path.is_symlink())

    def test_unexpected_prepared_and_preserved_entries_are_not_ignored(self):
        self.fixture.restore()
        for relative in ("prepared/999", "current/999", "current/00", "current/private-note"):
            with self.subTest(relative=relative):
                path = self.fixture.root / relative
                path.write_text("unrelated fixture must not be deleted")
                with self.assertRaises(MigrationError):
                    self.check()
                self.assertEqual(path.read_text(), "unrelated fixture must not be deleted")
                # Explicit fixture-only move retains every injected conflict.
                path.rename(self.fixture.home / relative.replace("/", "-"))
        self.assertEqual(self.check()["status"], "restore_verified")

    def test_reference_is_exact_and_malformed_reference_never_connects(self):
        reference = dict(self.reference, backup="/outside/home")
        with patch.object(self.fixture.transport, "run_remote") as remote:
            with self.assertRaises(MigrationError):
                self.check(reference)
            remote.assert_not_called()
        self.fixture.restore()
        reference = dict(self.reference, originals=list(reversed(self.reference["originals"])))
        with self.assertRaises(MigrationError):
            self.check(reference)

    def test_remote_claims_are_bounded_consistent_and_do_not_leak_fields(self):
        self.fixture.restore()
        good = self.check()
        good.pop("message")
        bad = []
        bad.append(dict(good, secret="PRIVATE"))
        bad.append(dict(good, inspected_items=True))
        bad.append(dict(good, status="restore_changed"))
        bad.append(dict(good, pending_cleanup=True))
        swapped = json.loads(json.dumps(good))
        swapped["items"][0]["preserved"] = "/PRIVATE"
        bad.append(swapped)
        for report in bad:
            with self.subTest(fields=list(report)):
                with self.assertRaises(ValueError):
                    _validate_result(report, self.reference)
                remote = SimpleNamespace(run_remote=lambda *a, **k: SimpleNamespace(stdout=json.dumps(report)))
                with self.assertRaises(MigrationError) as error:
                    reconcile_recovery(self.fixture.config, remote, self.reference)
                self.assertNotIn("PRIVATE", str(error.exception))

    def test_cancellation_uses_only_cancellable_transport(self):
        self.fixture.restore()
        called = []
        original = self.fixture.transport.run_remote
        def cancellable(script, timeout, callback):
            called.append(callback())
            return original(script, timeout)
        remote = SimpleNamespace(run_remote_cancellable=cancellable)
        report = reconcile_recovery(self.fixture.config, remote, self.reference, lambda: False)
        self.assertEqual(called, [False])
        self.assertEqual(report["status"], "restore_verified")


if __name__ == "__main__":
    unittest.main()
