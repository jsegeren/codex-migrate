"""A failed hosted run keeps only the opaque IDs needed for an exact retry."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import UUID

from codex_migrate.errors import MigrationError
from codex_migrate.vault_hosted_backup_run import HostedBackupRun
from codex_migrate.vault_hosted_upload_client import HostedUploadClient
from codex_migrate.vault_remote_inventory import RemoteInventory


ACCOUNT = "11111111-1111-4111-8111-111111111111"
VAULT = "22222222-2222-4222-8222-222222222222"
SNAPSHOT = "33333333-3333-4333-8333-333333333333"
OTHER_SNAPSHOT = "55555555-5555-4555-8555-555555555555"
RESERVATION = "44444444-4444-4444-8444-444444444444"
TOKEN = "hv1_" + "a" * 43


class HostedBackupRunTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.client = HostedUploadClient(
            "http://127.0.0.1:49111", "http://127.0.0.1:49112",
            TOKEN, ACCOUNT, VAULT, allow_loopback_http=True)
        self.run = HostedBackupRun(self.client, str(self.home))
        self.inventory = RemoteInventory(SNAPSHOT, (), 0, True)
        uuid_patch = patch("codex_migrate.vault_hosted_backup_run.uuid.uuid4",
                           return_value=UUID(RESERVATION))
        uuid_patch.start()
        self.addCleanup(uuid_patch.stop)

    def test_read_and_plan_do_not_create_state_or_reserve(self):
        with patch.object(self.client, "reserve_with_base") as reserve:
            self.assertIsNone(self.run.pending())
            with self.assertRaisesRegex(MigrationError, "explicit confirmation"):
                self.run.back_up_snapshot(str(self.root))
            reserve.assert_not_called()
        self.assertFalse((self.home / "Library").exists())

    def test_failed_run_survives_relaunch_and_reuses_retained_reservation(self):
        receipt = {"snapshotId": SNAPSHOT, "verifiedObjectCount": 3}
        with patch("codex_migrate.vault_hosted_backup_run.encrypted_snapshot_inventory",
                   return_value=self.inventory), patch.object(
                   self.client, "reserve_with_base", return_value=(RESERVATION, None)) as reserve, patch.object(
                   self.client, "back_up_snapshot",
                   side_effect=[MigrationError("network interrupted"), receipt]) as upload:
            with self.assertRaisesRegex(MigrationError, "network interrupted"):
                self.run.back_up_snapshot(str(self.root), apply=True)
            self.assertEqual(self.run.pending(), {
                "snapshotId": SNAPSHOT, "reservationId": RESERVATION})
            journal = self.run._journal
            self.assertEqual(journal.stat().st_mode & 0o077, 0)
            self.assertNotIn(TOKEN.encode(), journal.read_bytes())
            relaunched = HostedBackupRun(self.client, str(self.home))
            self.assertEqual(relaunched.back_up_snapshot(str(self.root), apply=True),
                             receipt)
            self.assertIsNone(relaunched.pending())
            reserve.assert_called_once_with(reservation_id=RESERVATION, apply=True)
            self.assertEqual(upload.call_count, 2)
            self.assertEqual([call.kwargs["reservation_id"] for call in
                              upload.call_args_list], [RESERVATION, RESERVATION])
            self.assertEqual([call.kwargs["snapshot"] for call in
                              upload.call_args_list], [SNAPSHOT, SNAPSHOT])

    def test_lost_reservation_ack_retries_the_previously_saved_id(self):
        receipt = {"snapshotId": SNAPSHOT, "verifiedObjectCount": 3}
        with patch("codex_migrate.vault_hosted_backup_run.encrypted_snapshot_inventory",
                   return_value=self.inventory), patch.object(
                   self.client, "reserve_with_base",
                   side_effect=[MigrationError("reserve response lost"),
                                (RESERVATION, None)]) as reserve, patch.object(
                   self.client, "back_up_snapshot", return_value=receipt) as upload:
            with self.assertRaisesRegex(MigrationError, "reserve response lost"):
                self.run.back_up_snapshot(str(self.root), apply=True)
            self.assertEqual(self.run.pending(), {
                "snapshotId": SNAPSHOT, "reservationId": RESERVATION,
                "state": "reserving"})
            upload.assert_not_called()
            relaunched = HostedBackupRun(self.client, str(self.home))
            self.assertEqual(relaunched.back_up_snapshot(str(self.root), apply=True),
                             receipt)
            self.assertEqual(reserve.call_count, 2)
            for call in reserve.call_args_list:
                self.assertEqual(call.kwargs,
                                 {"reservation_id": RESERVATION, "apply": True})
            upload.assert_called_once()
            self.assertIsNone(relaunched.pending())

    def test_different_snapshot_cannot_silently_displace_pending_run(self):
        with patch("codex_migrate.vault_hosted_backup_run.encrypted_snapshot_inventory",
                   side_effect=[self.inventory,
                                RemoteInventory(OTHER_SNAPSHOT, (), 0, True)]), patch.object(
                   self.client, "reserve_with_base", return_value=(RESERVATION, None)) as reserve, patch.object(
                   self.client, "back_up_snapshot",
                   side_effect=MigrationError("network interrupted")) as upload:
            with self.assertRaises(MigrationError):
                self.run.back_up_snapshot(str(self.root), apply=True)
            with self.assertRaisesRegex(MigrationError, "different hosted snapshot"):
                self.run.back_up_snapshot(str(self.root), apply=True)
            reserve.assert_called_once()
            upload.assert_called_once()
            self.assertEqual(self.run.pending()["snapshotId"], SNAPSHOT)

    def test_default_latest_retries_pinned_snapshot_after_local_latest_moves(self):
        receipt = {"snapshotId": SNAPSHOT, "verifiedObjectCount": 3}
        with patch("codex_migrate.vault_hosted_backup_run.encrypted_snapshot_inventory",
                   return_value=self.inventory) as inventory, patch.object(
                   self.client, "reserve_with_base", return_value=(RESERVATION, None)) as reserve, patch.object(
                   self.client, "back_up_snapshot",
                   side_effect=[MigrationError("network interrupted"), receipt]) as upload:
            with self.assertRaises(MigrationError):
                self.run.back_up_snapshot(str(self.root), apply=True)
            self.assertEqual(self.run.back_up_snapshot(str(self.root), apply=True), receipt)
            self.assertEqual([call.kwargs["snapshot"] for call in
                              inventory.call_args_list], ["latest", SNAPSHOT])
            self.assertEqual([call.kwargs["snapshot"] for call in
                              upload.call_args_list], [SNAPSHOT, SNAPSHOT])
            reserve.assert_called_once_with(reservation_id=RESERVATION, apply=True)
            self.assertIsNone(self.run.pending())

    def test_unsafe_journal_is_not_used_for_retry(self):
        with patch("codex_migrate.vault_hosted_backup_run.encrypted_snapshot_inventory",
                   return_value=self.inventory), patch.object(
                   self.client, "reserve_with_base", return_value=(RESERVATION, None)), patch.object(
                   self.client, "back_up_snapshot",
                   side_effect=MigrationError("network interrupted")) as upload:
            with self.assertRaises(MigrationError):
                self.run.back_up_snapshot(str(self.root), apply=True)
            os.chmod(self.run._journal, 0o644)
            with self.assertRaisesRegex(MigrationError, "journal is unsafe"):
                self.run.pending()
            with self.assertRaisesRegex(MigrationError, "journal is unsafe"):
                self.run.back_up_snapshot(str(self.root), apply=True)
            upload.assert_called_once()

    def test_pending_reservation_cannot_cross_account_identity(self):
        with patch("codex_migrate.vault_hosted_backup_run.encrypted_snapshot_inventory",
                   return_value=self.inventory), patch.object(
                   self.client, "reserve_with_base", return_value=(RESERVATION, None)), patch.object(
                   self.client, "back_up_snapshot",
                   side_effect=MigrationError("network interrupted")):
            with self.assertRaises(MigrationError):
                self.run.back_up_snapshot(str(self.root), apply=True)
        other_client = HostedUploadClient(
            "http://127.0.0.1:49111", "http://127.0.0.1:49112", TOKEN,
            "66666666-6666-4666-8666-666666666666", VAULT,
            allow_loopback_http=True)
        with self.assertRaisesRegex(MigrationError, "does not match this account"):
            HostedBackupRun(other_client, str(self.home)).pending()

    def test_explicit_abandon_keeps_journal_until_service_quarantines(self):
        with patch("codex_migrate.vault_hosted_backup_run.encrypted_snapshot_inventory",
                   return_value=self.inventory), patch.object(
                   self.client, "reserve_with_base", return_value=(RESERVATION, None)), patch.object(
                   self.client, "back_up_snapshot",
                   side_effect=MigrationError("network interrupted")):
            with self.assertRaises(MigrationError):
                self.run.back_up_snapshot(str(self.root), apply=True)
        with patch.object(self.client, "abandon",
                          side_effect=[MigrationError("response lost"), None]) as abandon, \
             patch.object(self.client, "reservation_status",
                          side_effect=["active", "cleanup_pending", "released", "released"]):
            with self.assertRaisesRegex(MigrationError, "explicit confirmation"):
                self.run.abandon_pending()
            abandon.assert_not_called()
            with self.assertRaisesRegex(MigrationError, "response lost"):
                self.run.abandon_pending(apply=True)
            self.assertEqual(self.run.pending(), {
                "snapshotId": SNAPSHOT, "reservationId": RESERVATION})
            self.assertTrue(self.run.abandon_pending(apply=True))
            self.assertEqual(self.run.pending(), {
                "snapshotId": SNAPSHOT, "reservationId": RESERVATION,
                "state": "cleanup_pending"})
            self.assertEqual(self.run.cleanup_status(), "cleanup_pending")
            self.assertEqual(HostedBackupRun(self.client, str(self.home)).cleanup_status(),
                             "released")
            self.assertTrue(self.run.abandon_pending(apply=True))
            self.assertEqual(abandon.call_count, 2)
            abandon.assert_any_call(RESERVATION, apply=True)

    def test_abandoned_upload_blocks_new_backup_until_release_is_verified(self):
        with patch("codex_migrate.vault_hosted_backup_run.encrypted_snapshot_inventory",
                   return_value=self.inventory), patch.object(
                   self.client, "reserve_with_base", return_value=(RESERVATION, None)) as reserve, patch.object(
                   self.client, "back_up_snapshot",
                   side_effect=MigrationError("interrupted")):
            with self.assertRaisesRegex(MigrationError, "interrupted"):
                self.run.back_up_snapshot(str(self.root), apply=True)
        with patch.object(self.client, "abandon"), patch.object(
                self.client, "reservation_status",
                side_effect=["cleanup_pending", "released"]) as status, patch(
                "codex_migrate.vault_hosted_backup_run.encrypted_snapshot_inventory",
                return_value=self.inventory), patch.object(
                self.client, "reserve_with_base", return_value=(RESERVATION, None)) as reserve, patch.object(
                self.client, "back_up_snapshot",
                return_value={"snapshotId": SNAPSHOT, "verifiedObjectCount": 3}):
            self.run.abandon_pending(apply=True)
            with self.assertRaisesRegex(MigrationError, "awaiting verified cleanup"):
                self.run.back_up_snapshot(str(self.root), apply=True)
            reserve.assert_not_called()
            self.assertIsNotNone(self.run.pending())
            self.run.back_up_snapshot(str(self.root), apply=True)
            reserve.assert_called_once_with(reservation_id=RESERVATION, apply=True)
            self.assertIsNone(self.run.pending())
            self.assertEqual(status.call_count, 2)

    def test_lost_abandon_ack_reconciles_already_released_reservation(self):
        with patch("codex_migrate.vault_hosted_backup_run.encrypted_snapshot_inventory",
                   return_value=self.inventory), patch.object(
                   self.client, "reserve_with_base", return_value=(RESERVATION, None)), patch.object(
                   self.client, "back_up_snapshot",
                   side_effect=MigrationError("interrupted")):
            with self.assertRaisesRegex(MigrationError, "interrupted"):
                self.run.back_up_snapshot(str(self.root), apply=True)
        with patch.object(self.client, "abandon",
                          side_effect=MigrationError("response lost")), patch.object(
                          self.client, "reservation_status", return_value="released"):
            self.assertTrue(self.run.abandon_pending(apply=True))
            self.assertEqual(self.run.pending()["state"], "cleanup_pending")


if __name__ == "__main__":
    unittest.main()
