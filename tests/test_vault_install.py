import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from codex_migrate.errors import MigrationError
from codex_migrate.vault_backup import backup
from codex_migrate.vault_install import (
    install_snapshot, install_status, recover_interrupted_install,
)
from codex_migrate.vault_local_lock import local_history_lock
from codex_migrate.vault_recovery import RestorePlan, RestoreResult


class VaultInstallTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name).resolve()
        self.codex = self.home / ".codex"
        (self.codex / "sessions/old").mkdir(parents=True)
        (self.codex / "archived_sessions").mkdir()
        (self.codex / "sessions/old/thread.jsonl").write_text(
            json.dumps({"payload": {"text": "OLD PRIVATE HISTORY"}}) + "\n",
            encoding="utf-8",
        )
        (self.codex / "archived_sessions/old.jsonl").write_text(
            json.dumps({"payload": {"text": "OLD ARCHIVE"}}) + "\n",
            encoding="utf-8",
        )
        (self.codex / "auth.json").write_text("AUTH MUST STAY", encoding="utf-8")
        (self.codex / "installation_id").write_text("IDENTITY MUST STAY", encoding="utf-8")
        self.vault = self.home / "vault"
        self.vault.mkdir()
        self.snapshot = "11111111-1111-4111-8111-111111111111"

    def restored(self, _home, _vault, output, *, snapshot, crypto_helper=None):
        self.assertEqual(snapshot, self.snapshot)
        root = Path(output)
        (root / "sessions/new").mkdir(parents=True)
        (root / "archived_sessions").mkdir()
        active = json.dumps({"payload": {"text": "NEW PRIVATE HISTORY"}}) + "\n"
        archived = json.dumps({"payload": {"text": "NEW ARCHIVE"}}) + "\n"
        (root / "sessions/new/thread.jsonl").write_text(active, encoding="utf-8")
        (root / "archived_sessions/new.jsonl").write_text(archived, encoding="utf-8")
        (root / "restore-receipt.json").write_text("{}", encoding="utf-8")
        return RestoreResult(
            vault=str(self.vault), snapshot_id=self.snapshot,
            transcript_files=2,
            transcript_bytes=len(active.encode()) + len(archived.encode()),
            output=str(root),
        )

    def verified(self):
        return RestorePlan(
            vault=str(self.vault), snapshot_id=self.snapshot,
            transcript_files=2, transcript_bytes=100, chunks=2, output=None,
        )

    def install(self, process_states=(False, False, False)):
        with patch("codex_migrate.vault_install.verify_snapshot",
                   return_value=self.verified()), \
                patch("codex_migrate.vault_install.restore_snapshot",
                      side_effect=self.restored), \
                patch("codex_migrate.vault_install.codex_running",
                      side_effect=process_states):
            return install_snapshot(
                str(self.home), str(self.vault), snapshot=self.snapshot)

    def test_install_replaces_only_history_and_keeps_verified_rollback_backup(self):
        result = self.install()
        self.assertEqual(result.snapshot_id, self.snapshot)
        self.assertEqual(
            (self.codex / "sessions/new/thread.jsonl").read_text(),
            json.dumps({"payload": {"text": "NEW PRIVATE HISTORY"}}) + "\n",
        )
        self.assertFalse((self.codex / "sessions/old/thread.jsonl").exists())
        self.assertEqual((self.codex / "auth.json").read_text(), "AUTH MUST STAY")
        self.assertEqual(
            (self.codex / "installation_id").read_text(), "IDENTITY MUST STAY")
        backup = Path(result.backup)
        self.assertTrue((backup / "sessions/old/thread.jsonl").is_file())
        receipt = json.loads((backup / "install-receipt.json").read_text())
        self.assertTrue(receipt["verified"])
        self.assertEqual(receipt["snapshot_id"], self.snapshot)
        self.assertEqual(install_status(str(self.home)), {"status": "idle"})
        self.assertFalse(any(self.home.glob(".codex-vault-stage-*")))

    def test_codex_reopening_rolls_back_and_preserves_failed_install_for_review(self):
        with self.assertRaisesRegex(MigrationError, "rollback was verified"):
            self.install((False, False, True))
        self.assertTrue((self.codex / "sessions/old/thread.jsonl").is_file())
        self.assertFalse((self.codex / "sessions/new/thread.jsonl").exists())
        backups = list(self.home.glob("Codex-Vault-Restore-Backup-*"))
        self.assertEqual(len(backups), 1)
        self.assertTrue(
            (backups[0] / "failed-install/sessions/new/thread.jsonl").is_file())
        self.assertTrue((backups[0] / "rollback-receipt.json").is_file())
        self.assertEqual(install_status(str(self.home)), {"status": "idle"})

    def test_interrupted_first_move_is_detected_and_recovered(self):
        real_replace = os.replace

        def interrupted(source, destination):
            source_path = Path(source)
            destination_path = Path(destination)
            real_replace(source, destination)
            if (source_path == self.codex / "sessions"
                    and destination_path.parent.name.startswith(
                        "Codex-Vault-Restore-Backup-")):
                raise SystemExit("simulated power loss")

        with patch("codex_migrate.vault_install.verify_snapshot",
                   return_value=self.verified()), \
                patch("codex_migrate.vault_install.restore_snapshot",
                      side_effect=self.restored), \
                patch("codex_migrate.vault_install.codex_running",
                      return_value=False), \
                patch("codex_migrate.vault_install.os.replace",
                      side_effect=interrupted):
            with self.assertRaises(SystemExit):
                install_snapshot(
                    str(self.home), str(self.vault), snapshot=self.snapshot)

        status = install_status(str(self.home))
        self.assertEqual(status["status"], "interrupted")
        self.assertFalse((self.codex / "sessions").exists())
        with patch("codex_migrate.vault_install.codex_running", return_value=False):
            recovered = recover_interrupted_install(str(self.home), apply=True)
        self.assertEqual(recovered["status"], "rolled_back")
        self.assertTrue((self.codex / "sessions/old/thread.jsonl").is_file())
        self.assertTrue((self.codex / "archived_sessions/old.jsonl").is_file())
        self.assertEqual(install_status(str(self.home)), {"status": "idle"})

    def test_install_refuses_running_codex_before_decryption_or_mutation(self):
        with patch("codex_migrate.vault_install.codex_running", return_value=True), \
                patch("codex_migrate.vault_install.verify_snapshot") as verify, \
                patch("codex_migrate.vault_install.restore_snapshot") as restore:
            with self.assertRaisesRegex(MigrationError, "Close Codex"):
                install_snapshot(
                    str(self.home), str(self.vault), snapshot=self.snapshot)
        verify.assert_not_called()
        restore.assert_not_called()
        self.assertTrue((self.codex / "sessions/old/thread.jsonl").is_file())

    def test_unexpected_recovered_file_blocks_before_live_history_moves(self):
        def unsafe_restore(*args, **kwargs):
            result = self.restored(*args, **kwargs)
            (Path(result.output) / "sessions/unexpected.txt").write_text("unsafe")
            return result

        with patch("codex_migrate.vault_install.verify_snapshot",
                   return_value=self.verified()), \
                patch("codex_migrate.vault_install.restore_snapshot",
                      side_effect=unsafe_restore), \
                patch("codex_migrate.vault_install.codex_running",
                      return_value=False):
            with self.assertRaisesRegex(MigrationError, "unexpected file"):
                install_snapshot(
                    str(self.home), str(self.vault), snapshot=self.snapshot)
        self.assertTrue((self.codex / "sessions/old/thread.jsonl").is_file())
        self.assertFalse(any(self.home.glob("Codex-Vault-Restore-Backup-*")))

    def test_backup_and_install_share_one_local_history_lock(self):
        with local_history_lock(str(self.home)):
            with self.assertRaisesRegex(
                    MigrationError, "Another local Vault history operation"):
                backup(str(self.home), str(self.vault))


if __name__ == "__main__":
    unittest.main()
