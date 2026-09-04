"""Read-only recovery against disposable destination files; no actual SSH."""

import contextlib
import io
import json
from pathlib import Path
import shlex
import shutil
import subprocess
from dataclasses import replace
import unittest
import threading
from types import SimpleNamespace
from unittest.mock import patch

import test_backup as fixtures
import test_destination_lock as lock_fixtures
from codex_migrate.cli import main
from codex_migrate.destination_lock import LOCK_NAME
from codex_migrate.errors import MigrationError
from codex_migrate.recovery import inspect_recovery
from codex_migrate.transaction import TRANSACTION_NAME, TRANSACTION_RUNNER


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.BackupTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.engine = self.fixture.engine
        self.engine.transport = self.fixture.transport()
        self.engine.transport.run_remote_cancellable = lambda script, timeout, cancelled: self.engine.transport.run_remote(script, timeout)
        self.home = self.fixture.target
        self.journal = self.home / TRANSACTION_NAME

    def inspect(self):
        return inspect_recovery(self.fixture.config, self.engine.transport)

    def interrupt(self):
        original = self.engine.transport.run_remote
        codex = shlex.quote(str(self.home / ".codex"))
        def fault(script, timeout=60):
            return original(script.replace("rm -rf " + codex + "\nmv ",
                "rm -rf " + codex + "\nkill -KILL $$\nmv "), timeout)
        self.engine.transport.run_remote = fault
        with self.assertRaises(RuntimeError):
            self.engine._install_and_verify()
        self.engine.transport.run_remote = original
        return json.loads(self.journal.read_text())

    def test_clean_home_is_read_only_and_does_not_claim_migration_complete(self):
        before = sorted(p.relative_to(self.home) for p in self.home.rglob("*"))
        report = self.inspect()
        self.assertEqual(report["status"], "no_pending_record")
        self.assertIn("does not verify", report["message"])
        self.assertEqual(before, sorted(p.relative_to(self.home) for p in self.home.rglob("*")))
        self.assertFalse((self.home / LOCK_NAME).exists())

    def test_interrupted_install_reports_verified_backup_without_restoring(self):
        record = self.interrupt()
        journal_bytes = self.journal.read_bytes()
        journal_stat = self.journal.stat()
        lock_stat = (self.home / LOCK_NAME).stat()
        report = self.inspect()
        self.assertEqual(report["status"], "backup_verified")
        self.assertEqual(report["inspected_items"], len(record["scope"]))
        self.assertIsNone(report["terminal_phase"])
        codex = next(i for i in report["items"] if i["original"].endswith("/.codex"))
        self.assertFalse(codex["current_present"])
        self.assertTrue(codex["existed"])
        self.assertFalse((self.home / ".codex").exists())
        self.assertEqual(self.journal.read_bytes(), journal_bytes)
        self.assertEqual(self.journal.stat().st_mtime_ns, journal_stat.st_mtime_ns)
        self.assertEqual((self.home / LOCK_NAME).stat().st_ino, lock_stat.st_ino)
        self.assertNotIn("backup_digest", json.dumps(report))
        self.assertNotIn("fixture-auth", json.dumps(report))

    def test_active_writer_reports_busy_without_inspecting_record(self):
        holder = lock_fixtures.DestinationLockTests()
        holder.setUp()
        self.addCleanup(holder.doCleanups)
        holder.hold(home=self.home)
        self.journal.write_text("PRIVATE broken record")
        report = self.inspect()
        self.assertEqual(report["status"], "busy")
        self.assertNotIn("PRIVATE", json.dumps(report))

    def test_damaged_backup_fails_without_private_output_or_changes(self):
        record = self.interrupt()
        copy = Path(record["backup"]) / ".codex/old.txt"
        copy.write_text("PRIVATE corrupted fixture")
        with self.assertRaisesRegex(MigrationError, "Recovery could not be verified") as error:
            self.inspect()
        self.assertNotIn("PRIVATE", str(error.exception))
        self.assertTrue(self.journal.exists())
        self.assertEqual(copy.read_text(), "PRIVATE corrupted fixture")
        self.assertFalse((self.home / ".codex").exists())

    def test_legacy_record_stays_pending_and_is_not_upgraded(self):
        self.interrupt()
        record = json.loads(self.journal.read_text())
        record["format"] = 1
        for item in record["scope"]:
            del item["backup_digest"]
        self.journal.write_text(json.dumps(record))
        before = self.journal.read_bytes()
        report = self.inspect()
        self.assertEqual(report["status"], "legacy_record")
        self.assertEqual(self.journal.read_bytes(), before)

    def test_terminal_receipt_is_historical_not_current_completion(self):
        original = self.engine.transport.run_remote
        self.engine.transport.run_remote = lambda script, timeout=60: original(
            script.replace("unlink($journal) or fail();", "fail();"), timeout)
        with self.assertRaises(RuntimeError):
            self.engine._install_and_verify()
        self.engine.transport.run_remote = original
        report = self.inspect()
        self.assertEqual(report["terminal_phase"], "installed")
        self.assertEqual(report["status"], "backup_verified")
        self.assertTrue(self.journal.exists())
        # Reading a receipt is not a claim the current installed tree is intact.
        (self.home / "Git/new.txt").write_text("later work")
        self.assertEqual(self.inspect()["status"], "backup_verified")
        self.assertEqual((self.home / "Git/new.txt").read_text(), "later work")

    def test_unsafe_journal_scope_cannot_read_arbitrary_paths(self):
        self.interrupt()
        before = json.loads(self.journal.read_text())
        for name in (".ssh", ".codex/auth.json", "../outside", "Git/../other", "Git//other"):
            with self.subTest(name=name):
                record = json.loads(json.dumps(before))
                record["scope"][0]["original"] = str(self.home) + "/" + name
                self.journal.write_text(json.dumps(record))
                with self.assertRaises(MigrationError):
                    self.inspect()
                self.assertTrue(self.journal.exists())

    def test_unsafe_lock_or_missing_lock_does_not_create_or_repair_it(self):
        self.interrupt()
        lock = self.home / LOCK_NAME
        lock.unlink()
        with self.assertRaises(MigrationError):
            self.inspect()
        self.assertFalse(lock.exists())
        lock.symlink_to(self.journal)
        with self.assertRaises(MigrationError):
            self.inspect()
        self.assertTrue(lock.is_symlink())

    def test_malformed_remote_reports_cannot_leak_extra_fields(self):
        for payload in ({"status": "no_pending_record", "inspected_items": 0, "secret": "PRIVATE"},
                        {"status": "backup_verified", "inspected_items": 1}, [], "PRIVATE"):
            with self.subTest(payload=payload):
                transport = SimpleNamespace(run_remote=lambda *a, **k: SimpleNamespace(stdout=json.dumps(payload)))
                with self.assertRaises(MigrationError) as error:
                    inspect_recovery(self.fixture.config, transport)
                self.assertNotIn("PRIVATE", str(error.exception))

    def test_unicode_home_and_backup_paths_roundtrip_without_digest_output(self):
        home = self.home / "café-测试"
        original = home / "données"
        original.mkdir(parents=True)
        (original / "naïve\n文件").write_text("fixture contents")
        backup = home / "sauvegarde-测试"
        backup.mkdir(mode=0o700)
        copy = backup / "données"
        shutil.copytree(original, copy)
        (home / LOCK_NAME).touch(mode=0o600)
        plan = {"format": 2, "id": "e" * 32, "home": str(home), "backup": str(backup),
                "scope": [{"original": str(original), "backup": str(copy)}]}
        result = subprocess.run(["/usr/bin/perl", "-e", TRANSACTION_RUNNER, "--", "begin", json.dumps(plan)],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = inspect_recovery(replace(self.fixture.config, target_home=str(home)), self.engine.transport)
        self.assertEqual(report["status"], "backup_verified")
        self.assertEqual(report["backup"], str(backup))
        self.assertEqual(report["items"][0]["original"], str(original))
        self.assertNotIn("backup_digest", json.dumps(report))

    def test_cli_inspection_needs_no_source_state_or_mutation_authority(self):
        args = ["recovery", "--target", "person@fixture.local", "--target-home", str(self.home),
                "--source-home", str(self.fixture.source), "--state-dir", str(self.fixture.source / "not-created"), "--json"]
        with patch("codex_migrate.transport.SSHTransport", return_value=self.engine.transport):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(args), 0)
            self.assertEqual(json.loads(output.getvalue())["status"], "no_pending_record")
            with contextlib.redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(main(args + ["--apply"]), 2)
            self.assertIn("read-only", errors.getvalue())
        self.assertFalse((self.fixture.source / "not-created").exists())
        self.assertFalse((self.home / LOCK_NAME).exists())

    def test_dashboard_check_keeps_migration_state_and_has_safe_stop(self):
        entered, release = threading.Event(), threading.Event()
        def slow_inspection(*args):
            entered.set()
            self.assertTrue(release.wait(5))
            return {"status": "no_pending_record", "message": "Finished"}
        self.fixture.state.update(status="failed", phase="installing", staging_complete=False, error="previous failure")
        with patch("codex_migrate.recovery.inspect_recovery", slow_inspection), \
             patch.object(self.engine.transport, "cancel_all", create=True) as cancel:
            self.engine.start_recovery_check()
            self.assertTrue(entered.wait(5))
            self.assertEqual(self.fixture.state.read()["recovery"]["status"], "checking")
            with self.assertRaises(MigrationError):
                self.engine.start_recovery_check()
            with self.assertRaises(MigrationError):
                self.engine.start_inspection()
            self.engine.stop_recovery_check()
            cancel.assert_called_once()
            release.set()
            self.engine._thread.join(5)
        current = self.fixture.state.read()
        self.assertEqual(current["status"], "failed")
        self.assertEqual(current["phase"], "installing")
        self.assertEqual(current["error"], "previous failure")
        self.assertEqual(current["recovery"]["status"], "stopped")

    def test_dashboard_recovery_result_and_restart_do_not_authorize_migration(self):
        self.fixture.state.update(status="failed", phase="installing", staging_complete=False)
        self.engine.start_recovery_check()
        self.engine._thread.join(5)
        current = self.fixture.state.read()
        self.assertEqual(current["recovery"]["status"], "no_pending_record")
        self.assertIn("checked_at", current["recovery"])
        self.assertEqual(current["status"], "failed")
        self.assertFalse(current["staging_complete"])
        self.fixture.state.update(recovery={"status": "checking"})
        self.engine.reconcile_startup()
        self.assertEqual(self.fixture.state.read()["recovery"]["status"], "stopped")

    def test_shutdown_stops_read_only_check_without_overwriting_migration_status(self):
        entered, release = threading.Event(), threading.Event()
        def slow(*args):
            entered.set()
            release.wait(5)
            return {"status": "no_pending_record", "message": "Finished"}
        self.fixture.state.update(status="complete", phase="verified")
        with patch("codex_migrate.recovery.inspect_recovery", slow), \
             patch.object(self.engine.transport, "cancel_all", side_effect=release.set, create=True):
            self.engine.start_recovery_check()
            self.assertTrue(entered.wait(5))
            self.engine.shutdown()
        self.assertFalse(self.engine._thread.is_alive())
        self.assertEqual(self.fixture.state.read()["status"], "complete")
        self.assertEqual(self.fixture.state.read()["recovery"]["status"], "stopped")


if __name__ == "__main__":
    unittest.main()
