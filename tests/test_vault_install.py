import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from codex_migrate.errors import MigrationError
from codex_migrate.vault_backup import backup
from codex_migrate.vault_install import (
    install_snapshot, install_status, install_thread, plan_thread_install,
    recover_interrupted_install,
)
from codex_migrate.vault_local_lock import local_history_lock
from codex_migrate.vault_recovery import RestorePlan, RestoreResult


class VaultInstallTests(unittest.TestCase):
    ARCHIVE_ID = "22222222-2222-4222-8222-222222222222"
    ACTIVE_ID = "33333333-3333-4333-8333-333333333333"

    def archived_content(self):
        return (json.dumps({"type": "session_meta", "payload": {"id": self.ARCHIVE_ID}}) + "\n"
                + json.dumps({"payload": {"text": "NEW ARCHIVE"}}) + "\n")

    def active_content(self):
        return (json.dumps({"type": "session_meta", "payload": {"id": self.ACTIVE_ID}}) + "\n"
                + json.dumps({"payload": {"text": "NEW PRIVATE HISTORY"}}) + "\n")

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
        active = self.active_content()
        archived = self.archived_content()
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

    def install_selected(self, collection="archived", transcript="new.jsonl",
                         process_states=(False, False, False)):
        with patch("codex_migrate.vault_install.verify_snapshot",
                   return_value=self.verified()), \
                patch("codex_migrate.vault_install.restore_snapshot",
                      side_effect=self.restored), \
                patch("codex_migrate.vault_install.codex_running",
                      side_effect=process_states):
            return install_thread(
                str(self.home), str(self.vault), collection, transcript,
                snapshot=self.snapshot,
            )

    def test_install_replaces_only_history_and_keeps_verified_rollback_backup(self):
        result = self.install()
        self.assertEqual(result.snapshot_id, self.snapshot)
        self.assertEqual(
            (self.codex / "sessions/new/thread.jsonl").read_text(),
            self.active_content(),
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

    def test_selected_install_adds_only_one_thread_and_preserves_everything_else(self):
        before_active = (self.codex / "sessions/old/thread.jsonl").read_bytes()
        before_archive = (self.codex / "archived_sessions/old.jsonl").read_bytes()

        result = self.install_selected()

        self.assertEqual(result.status, "installed")
        self.assertTrue(result.applied)
        self.assertEqual(
            (self.codex / "archived_sessions/new.jsonl").read_text(),
            self.archived_content(),
        )
        self.assertEqual(
            (self.codex / "sessions/old/thread.jsonl").read_bytes(), before_active)
        self.assertEqual(
            (self.codex / "archived_sessions/old.jsonl").read_bytes(), before_archive)
        self.assertFalse((self.codex / "sessions/new/thread.jsonl").exists())
        self.assertEqual((self.codex / "auth.json").read_text(), "AUTH MUST STAY")
        self.assertEqual(
            (self.codex / "installation_id").read_text(), "IDENTITY MUST STAY")
        receipt = json.loads(Path(result.receipt).read_text())
        self.assertEqual(receipt["format"], "codex-vault-thread-restore-receipt")
        self.assertEqual(receipt["transcript"], "new.jsonl")
        self.assertTrue(receipt["verified"])
        self.assertFalse(any(self.home.glob(".codex-vault-selected-*")))

    def test_selected_plan_is_read_only(self):
        with patch("codex_migrate.vault_install.verify_snapshot",
                   return_value=self.verified()), \
                patch("codex_migrate.vault_install.restore_snapshot",
                      side_effect=self.restored):
            plan = plan_thread_install(
                str(self.home), str(self.vault), "archived", "new.jsonl",
                snapshot=self.snapshot,
            )
        self.assertEqual(plan.action, "add")
        self.assertEqual(plan.target, "archived_sessions/new.jsonl")
        self.assertFalse(plan.applied)
        self.assertFalse((self.codex / "archived_sessions/new.jsonl").exists())

    def test_selected_install_reports_identical_thread_already_present(self):
        content = self.archived_content()
        (self.codex / "sessions/already").mkdir()
        (self.codex / "sessions/already/new.jsonl").write_text(content)

        result = self.install_selected(process_states=(False,))

        self.assertEqual(result.status, "already_present")
        self.assertFalse(result.applied)
        self.assertIsNone(result.receipt)
        self.assertEqual(result.target, "sessions/already/new.jsonl")
        self.assertFalse((self.codex / "archived_sessions/new.jsonl").exists())

    def test_selected_install_refuses_same_identity_with_different_content(self):
        (self.codex / "archived_sessions/new.jsonl").write_text("different\n")

        with self.assertRaisesRegex(MigrationError, "never overwrites or merges"):
            self.install_selected(process_states=(False,))

        self.assertEqual(
            (self.codex / "archived_sessions/new.jsonl").read_text(), "different\n")
        self.assertFalse(any(self.home.glob("Codex-Vault-Thread-Restore-Receipt-*")))

    def test_selected_install_refuses_embedded_id_collision_under_other_filename(self):
        renamed = self.codex / "sessions/old/renamed.jsonl"
        renamed.write_text(
            json.dumps({"type": "session_meta", "payload": {"id": self.ARCHIVE_ID}})
            + "\n" + json.dumps({"payload": {"text": "DIVERGED"}}) + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(MigrationError, "never overwrites or merges"):
            self.install_selected()
        self.assertFalse((self.codex / "archived_sessions/new.jsonl").exists())

    def test_selected_install_recognizes_identical_id_under_other_filename(self):
        renamed = self.codex / "sessions/old/renamed.jsonl"
        renamed.write_text(self.archived_content(), encoding="utf-8")
        result = self.install_selected(process_states=(False,))
        self.assertEqual(result.status, "already_present")
        self.assertEqual(result.target, "sessions/old/renamed.jsonl")

    def test_selected_install_refuses_unverified_source_identity(self):
        def missing_id(*args, **kwargs):
            result = self.restored(*args, **kwargs)
            replacement = json.dumps({"payload": {"text": "NO ID"}}) + "\n"
            (Path(result.output) / "archived_sessions/new.jsonl").write_text(
                replacement, encoding="utf-8")
            return RestoreResult(
                vault=result.vault, snapshot_id=result.snapshot_id,
                transcript_files=result.transcript_files,
                transcript_bytes=result.transcript_bytes - len(self.archived_content().encode())
                + len(replacement.encode()), output=result.output,
            )

        with patch("codex_migrate.vault_install.verify_snapshot",
                   return_value=self.verified()), \
                patch("codex_migrate.vault_install.restore_snapshot",
                      side_effect=missing_id), \
                patch("codex_migrate.vault_install.codex_running",
                      return_value=False):
            with self.assertRaisesRegex(MigrationError, "no verified thread ID"):
                install_thread(str(self.home), str(self.vault), "archived", "new.jsonl",
                               snapshot=self.snapshot)
        self.assertFalse((self.codex / "archived_sessions/new.jsonl").exists())

    def test_selected_install_refuses_duplicate_id_within_backup(self):
        def duplicated(*args, **kwargs):
            result = self.restored(*args, **kwargs)
            duplicate = Path(result.output) / "sessions/new/duplicate.jsonl"
            duplicate.write_text(self.archived_content(), encoding="utf-8")
            return RestoreResult(
                vault=result.vault, snapshot_id=result.snapshot_id,
                transcript_files=result.transcript_files + 1,
                transcript_bytes=result.transcript_bytes + len(self.archived_content().encode()),
                output=result.output,
            )

        with patch("codex_migrate.vault_install.verify_snapshot",
                   return_value=self.verified()), \
                patch("codex_migrate.vault_install.restore_snapshot",
                      side_effect=duplicated):
            with self.assertRaisesRegex(MigrationError, "more than one file"):
                plan_thread_install(str(self.home), str(self.vault), "archived", "new.jsonl",
                                    snapshot=self.snapshot)
        self.assertFalse((self.codex / "archived_sessions/new.jsonl").exists())

    def test_selected_install_rolls_back_if_receipt_write_fails(self):
        with patch("codex_migrate.vault_install.verify_snapshot",
                   return_value=self.verified()), \
                patch("codex_migrate.vault_install.restore_snapshot",
                      side_effect=self.restored), \
                patch("codex_migrate.vault_install.codex_running",
                      side_effect=(False, False, False)), \
                patch("codex_migrate.vault_install._atomic_json",
                      side_effect=MigrationError("simulated receipt failure")):
            with self.assertRaisesRegex(MigrationError, "stopped safely"):
                install_thread(
                    str(self.home), str(self.vault), "archived", "new.jsonl",
                    snapshot=self.snapshot,
                )

        self.assertFalse((self.codex / "archived_sessions/new.jsonl").exists())
        self.assertTrue((self.codex / "archived_sessions/old.jsonl").is_file())
        self.assertTrue((self.codex / "sessions/old/thread.jsonl").is_file())
        self.assertFalse(any(self.home.glob(".codex-vault-selected-*")))

    def test_selected_install_rejects_unsafe_or_missing_selection(self):
        with patch("codex_migrate.vault_install.verify_snapshot",
                   return_value=self.verified()), \
                patch("codex_migrate.vault_install.restore_snapshot",
                      side_effect=self.restored):
            with self.assertRaisesRegex(ValueError, "invalid conversation"):
                plan_thread_install(
                    str(self.home), str(self.vault), "archived", "../new.jsonl",
                    snapshot=self.snapshot,
                )
            with self.assertRaisesRegex(MigrationError, "not present"):
                plan_thread_install(
                    str(self.home), str(self.vault), "archived", "missing.jsonl",
                    snapshot=self.snapshot,
                )


if __name__ == "__main__":
    unittest.main()
