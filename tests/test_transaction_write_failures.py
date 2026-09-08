"""Receipt write failures in the real local installer and explicit restoration.

Only a selected Perl write/sync boundary and the closed-process snapshot are
injected. These tests do not exhaust a disk or claim physical power-loss proof.
All identities and workspace contents are disposable, synthetic fixtures.
"""

import json
from pathlib import Path
import platform
import unittest
from unittest.mock import patch

import test_transactions as fixtures
from process_fixtures import closed_codex_script
from codex_migrate.processes import require_codex_closed_script
from codex_migrate.recovery import inspect_recovery
from codex_migrate.restore import restore_recovery
from codex_migrate.transaction import TRANSACTION_RUNNER


@unittest.skipUnless(platform.system() == "Darwin", "local APFS installer fixture")
class TransactionWriteFailureTests(unittest.TestCase):
    def setUp(self):
        self.transaction = fixtures.TransactionTests()
        self.transaction.setUp()
        self.addCleanup(self.transaction.doCleanups)
        self.fixture = self.transaction.fixture
        self.engine = self.transaction.engine
        self.home = self.fixture.target
        self.journal = self.transaction.journal

    def runner_with_failure(self, phase, boundary="partial"):
        condition = "$value->{phase} eq '" + phase + "'"
        if boundary == "partial":
            marker = "my $n = syswrite($fh, $bytes, length($bytes) - $offset, $offset);"
            replacement = (
                "my $n;\nif (" + condition + ") {\n"
                "  if ($offset == 0) { $n = syswrite($fh, $bytes, 8); }\n"
                "  else { $! = Errno::ENOSPC(); $n = undef; }\n"
                "} else { $n = syswrite($fh, $bytes, length($bytes) - $offset, $offset); }")
        else:
            marker = ("    $fh->sync or fail();\n    exclusive_rename($temp, $path);"
                      if boundary == "sync" else
                      "    flush_parent($path);\n    defined fcntl($fh, 51, 0) or fail();")
            replacement = "    if (" + condition + ") { $! = Errno::EIO(); fail(); }\n" + marker
        self.assertEqual(TRANSACTION_RUNNER.count(marker), 1)
        return TRANSACTION_RUNNER.replace(marker, replacement)

    def install_with_failure(self, phase, boundary="partial"):
        with patch("codex_migrate.transaction.TRANSACTION_RUNNER",
                   self.runner_with_failure(phase, boundary)):
            with self.assertRaises(RuntimeError) as caught:
                self.engine._install_and_verify()
        self.assertNotIn("INSTALLED=1", str(caught.exception))
        self.assertNotIn("fixture-auth", str(caught.exception))
        return str(caught.exception)

    def assert_originals_and_backup(self, backup):
        self.assertEqual((self.home / ".codex/old.txt").read_text(), "original")
        self.assertEqual((self.home / "Git/old.txt").read_text(), "original-work")
        self.assertEqual((backup / ".codex/old.txt").read_text(), "original")
        self.assertEqual((backup / "home-relative/Git/old.txt").read_text(), "original-work")
        self.assertEqual((self.fixture.source / "Git/new.txt").read_text(), "new-work")

    def recover_and_preserve_later_work(self):
        self.transaction.assert_pending_blocks_writes()
        backup = Path(self.fixture.state.read()["pending_backup"])
        self.assert_originals_and_backup(backup)
        # Even when rollback restored bytes, an unconfirmed receipt is not
        # success. A later explicit restore must preserve any subsequent work.
        later = self.home / "Git/after-failure.txt"
        later.write_text("invented later work")
        transport = self.fixture.transport()
        transport.run_remote_cancellable = (
            lambda script, timeout, cancelled: transport.run_remote(script, timeout))
        inspection = inspect_recovery(self.fixture.config, transport)
        self.assertEqual(inspection["status"], "backup_verified")
        self.assertEqual(later.read_text(), "invented later work")
        guard = closed_codex_script(require_codex_closed_script(str(self.home)))
        with patch("codex_migrate.restore.require_codex_closed_script", return_value=guard):
            result = restore_recovery(self.fixture.config, transport, inspection)
        self.assertEqual(result["status"], "restored")
        self.assertFalse(self.journal.exists())
        self.assert_originals_and_backup(backup)
        self.assertFalse(later.exists())
        self.assertEqual((Path(result["preserved"]) / "1/after-failure.txt").read_text(),
                         "invented later work")
        self.assertEqual((self.home / ".codex/auth.json").read_text(), "fixture-auth")
        self.assertEqual((self.home / ".codex/installation_id").read_text(), "fixture-id")
        completed = Path(result["preserved"]).parent / "complete.json"
        self.assertTrue(completed.is_file())

    def test_partial_initial_journal_never_replaces_and_retry_retains_failed_attempt(self):
        self.install_with_failure("replacing")
        self.fixture.assert_originals_untouched()
        self.assertFalse(self.journal.exists())
        partials = list(self.home.glob(self.journal.name + ".pending-*"))
        self.assertEqual(len(partials), 1)
        self.assertEqual(partials[0].stat().st_size, 8)
        old_backup = Path(self.fixture.state.read()["pending_backup"])
        self.assert_originals_and_backup(old_backup)
        # Finalize/resume prepares staging again before installation. A failed
        # journal write may leave destination identity prepared in staging;
        # remove that transient copy through the real retry path, not by
        # bypassing the installer's identity-free staging precondition.
        self.engine._prepare_staging()
        self.assertFalse((self.fixture.stage / ".codex/auth.json").exists())
        self.assertFalse((self.fixture.stage / ".codex/installation_id").exists())
        receipt = self.engine._install_and_verify()
        self.assertTrue(receipt["backup_verified"])
        self.assertNotEqual(Path(receipt["backup"]), old_backup)
        self.assertTrue(partials[0].exists())
        self.assertTrue(old_backup.exists())
        self.assertEqual((self.home / "Git/new.txt").read_text(), "new-work")

    def test_partial_install_receipt_allows_explicit_verified_recovery(self):
        message = self.install_with_failure("installed")
        self.assertIn("rollback is unconfirmed", message)
        backup = Path(self.fixture.state.read()["pending_backup"])
        partials = list(backup.glob("transaction-receipt.json.pending-*"))
        self.assertEqual(len(partials), 1)
        self.assertEqual(partials[0].stat().st_size, 8)
        self.recover_and_preserve_later_work()
        self.assertTrue(partials[0].exists())

    def test_partial_rollback_receipt_allows_explicit_verified_recovery(self):
        self.transaction.inject(self.transaction.corrupt_installed)
        message = self.install_with_failure("restored")
        self.assertIn("rollback is unconfirmed", message)
        self.recover_and_preserve_later_work()

    def test_receipt_sync_failure_allows_explicit_verified_recovery(self):
        message = self.install_with_failure("installed", "sync")
        self.assertIn("rollback is unconfirmed", message)
        self.recover_and_preserve_later_work()

    def test_failure_after_receipt_rename_is_not_treated_as_current_success(self):
        message = self.install_with_failure("installed", "published")
        self.assertIn("rollback is unconfirmed", message)
        backup = Path(self.fixture.state.read()["pending_backup"])
        terminal = json.loads((backup / "transaction-receipt.json").read_text())
        self.assertEqual(terminal["phase"], "installed")
        # A visible installed receipt can precede a failed durability barrier
        # and automatic rollback. Current bytes and explicit restore must win.
        self.recover_and_preserve_later_work()


if __name__ == "__main__":
    unittest.main()
