"""A hosted-only backup must never lose its reservation or claim early success."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from codex_migrate.errors import MigrationError
from codex_migrate.vault_hosted_live_run import HostedLiveBackupRun
from codex_migrate.vault_hosted_recovery_client import HostedRecoveryClient
from codex_migrate.vault_hosted_upload_client import HostedUploadClient


ACCOUNT = "11111111-1111-4111-8111-111111111111"
VAULT = "22222222-2222-4222-8222-222222222222"
BASE = "33333333-3333-4333-8333-333333333333"
OTHER = "44444444-4444-4444-8444-444444444444"
KEY = "55555555-5555-4555-8555-555555555555"
TOKEN = "hv1_" + "a" * 43
ORIGIN = "http://127.0.0.1:49111"


class HostedLiveRunTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "home"
        self.home.mkdir(mode=0o700)
        self.helper = self.root / "helper"
        self.helper.write_text("#!/bin/sh\nexit 0\n")
        self.helper.chmod(0o700)
        self.upload = HostedUploadClient(
            ORIGIN, "http://127.0.0.1:49112", TOKEN, ACCOUNT, VAULT,
            allow_loopback_http=True)
        self.recovery = HostedRecoveryClient(
            ORIGIN, TOKEN, VAULT, allow_loopback_http=True)
        self.run = HostedLiveBackupRun(self.upload, self.recovery, str(self.home))
        preflight = patch("codex_migrate.vault_hosted_live_run.unchanged_published_history",
                          return_value=None)
        self.preflight = preflight.start()
        self.addCleanup(preflight.stop)
        self.metadata = {"format": "codex-vault", "version": 1,
                         "key_id": KEY, "created_at": "2026-09-27T00:00:00+00:00"}

    def back_up(self, run=None, metadata=None):
        return (run or self.run).back_up_live_history(
            metadata or self.metadata, crypto_helper=str(self.helper),
            max_prior_bytes=5_000_000, apply=True)

    def interrupted_run(self, *, scratch_name=None):
        def stage(*args, **kwargs):
            if scratch_name is not None:
                scratch_root = args[2].directory / "scratch"
                scratch_root.mkdir(mode=0o700)
                prefix = scratch_root / "aa"
                prefix.mkdir(mode=0o700)
                chunk = prefix / scratch_name
                chunk.write_bytes(b"synthetic ciphertext")
                chunk.chmod(0o600)
            raise MigrationError("upload interrupted")

        with patch.object(self.upload, "reserve_with_base",
                          side_effect=lambda *, reservation_id, apply:
                          (reservation_id, BASE)), patch(
                "codex_migrate.vault_hosted_live_run.stage_reserved_hosted_snapshot",
                side_effect=stage):
            with self.assertRaisesRegex(MigrationError, "upload interrupted"):
                self.back_up()
        return self.run.pending()

    def test_plan_and_invalid_setup_do_not_reserve(self):
        with patch.object(self.upload, "reserve_with_base") as reserve:
            with self.assertRaisesRegex(MigrationError, "explicit confirmation"):
                self.run.back_up_live_history(
                    self.metadata, crypto_helper=str(self.helper),
                    max_prior_bytes=5_000_000)
            with self.assertRaisesRegex(MigrationError, "size limit"):
                self.run.back_up_live_history(
                    self.metadata, crypto_helper=str(self.helper),
                    max_prior_bytes=0, apply=True)
            reserve.assert_not_called()
        self.assertIsNone(self.run.pending())

    def test_unchanged_check_creates_no_reservation_or_new_version(self):
        self.preflight.return_value = {"unchanged": True,
                                       "lastGoodSnapshotId": BASE,
                                       "lastGoodObjectCount": 4}
        with patch.object(self.upload, "reserve_with_base") as reserve:
            self.assertEqual(self.back_up(), self.preflight.return_value)
            reserve.assert_not_called()
        self.assertIsNone(self.run.pending())

    def test_lost_reservation_reply_retries_exact_pre_recorded_id(self):
        ids = []

        def reserve(*, reservation_id, apply):
            self.assertTrue(apply)
            ids.append(reservation_id)
            if len(ids) == 1:
                raise MigrationError("network reply lost")
            return reservation_id, None

        with patch.object(self.upload, "reserve_with_base", side_effect=reserve), \
                patch("codex_migrate.vault_hosted_live_run.stage_reserved_hosted_snapshot",
                      return_value="staged") as stage, patch.object(
                self.upload, "publish_hosted_stage") as publish:
            with self.assertRaisesRegex(MigrationError, "reply lost"):
                self.back_up()
            pending = self.run.pending()
            self.assertEqual(pending["phase"], "reserving")
            self.assertEqual(pending["reservationId"], ids[0])
            self.assertNotIn(TOKEN.encode(), self.run._state.read_bytes())
            self.assertEqual(json.loads(self.run._state.read_text())["phase"],
                             "reserving")
            stage.assert_not_called()
            publish.assert_not_called()
            publish.return_value = {"snapshotId": pending["snapshotId"],
                                    "verifiedObjectCount": 3}
            self.assertEqual(self.back_up()["snapshotId"], pending["snapshotId"])
            self.assertEqual(ids, [pending["reservationId"]] * 2)
            self.assertIsNone(self.run.pending())
            self.assertFalse((self.run._directory /
                ("snapshot-" + pending["snapshotId"])).exists())

    def test_interrupted_stage_keeps_exact_base_snapshot_and_key(self):
        ids = []

        def reserve(*, reservation_id, apply):
            ids.append(reservation_id)
            return reservation_id, BASE

        with patch.object(self.upload, "reserve_with_base", side_effect=reserve), \
                patch.object(self.upload, "reservation_receipt",
                             return_value={"state": "active"}), patch(
                "codex_migrate.vault_hosted_live_run.stage_reserved_hosted_snapshot",
                side_effect=[MigrationError("upload interrupted"), "staged"]), \
                patch.object(self.upload, "publish_hosted_stage") as publish:
            with self.assertRaisesRegex(MigrationError, "upload interrupted"):
                self.back_up()
            pending = self.run.pending()
            self.assertEqual(pending["phase"], "active")
            self.assertEqual(json.loads(self.run._state.read_text())["baseSnapshotId"],
                             BASE)
            publish.return_value = {"snapshotId": pending["snapshotId"],
                                    "verifiedObjectCount": 3}
            resumed = HostedLiveBackupRun(self.upload, self.recovery, str(self.home))
            self.assertEqual(self.back_up(resumed)["snapshotId"],
                             pending["snapshotId"])
            self.assertEqual(ids, [pending["reservationId"]] * 2)
            self.assertIsNone(resumed.pending())

    def test_lost_publication_ack_reconciles_exact_server_snapshot(self):
        with patch.object(self.upload, "reserve_with_base",
                          side_effect=lambda *, reservation_id, apply:
                          (reservation_id, BASE)), patch(
                "codex_migrate.vault_hosted_live_run.stage_reserved_hosted_snapshot",
                return_value="staged") as stage, patch.object(
                self.upload, "publish_hosted_stage",
                side_effect=MigrationError("publication reply lost")) as publish:
            with self.assertRaisesRegex(MigrationError, "reply lost"):
                self.back_up()
            pending = self.run.pending()
            self.assertEqual(pending["phase"], "active")
            with patch.object(self.upload, "reservation_receipt", return_value={
                    "state": "published", "snapshotId": pending["snapshotId"],
                    "verifiedObjectCount": 3}):
                self.assertEqual(self.back_up(), {
                    "snapshotId": pending["snapshotId"],
                    "verifiedObjectCount": 3})
            stage.assert_called_once()
            publish.assert_called_once()
            self.assertIsNone(self.run.pending())

    def test_foreign_publication_or_key_change_keeps_pending_state(self):
        with patch.object(self.upload, "reserve_with_base",
                          side_effect=lambda *, reservation_id, apply:
                          (reservation_id, BASE)), patch(
                "codex_migrate.vault_hosted_live_run.stage_reserved_hosted_snapshot",
                side_effect=MigrationError("interrupted")):
            with self.assertRaisesRegex(MigrationError, "interrupted"):
                self.back_up()
        pending = self.run.pending()
        with patch.object(self.upload, "reservation_receipt", return_value={
                "state": "published", "snapshotId": OTHER,
                "verifiedObjectCount": 3}):
            with self.assertRaisesRegex(MigrationError, "does not match"):
                self.back_up()
        with self.assertRaisesRegex(MigrationError, "different hosted key"):
            self.back_up(metadata={**self.metadata, "key_id": OTHER})
        self.assertEqual(self.run.pending(), pending)

    def test_retry_refuses_a_changed_reservation_base(self):
        bases = iter((BASE, OTHER))
        with patch.object(self.upload, "reserve_with_base",
                          side_effect=lambda *, reservation_id, apply:
                          (reservation_id, next(bases))), patch.object(
                self.upload, "reservation_receipt", return_value={"state": "active"}), \
                patch("codex_migrate.vault_hosted_live_run.stage_reserved_hosted_snapshot",
                      side_effect=MigrationError("interrupted")) as stage:
            with self.assertRaisesRegex(MigrationError, "interrupted"):
                self.back_up()
            pending = self.run.pending()
            with self.assertRaisesRegex(MigrationError, "base changed on retry"):
                self.back_up()
            stage.assert_called_once()
            self.assertEqual(self.run.pending(), pending)

    def test_unsafe_pending_file_is_not_replaced_or_retried(self):
        with patch.object(self.upload, "reserve_with_base",
                          side_effect=MigrationError("reply lost")) as reserve:
            with self.assertRaisesRegex(MigrationError, "reply lost"):
                self.back_up()
            self.run._state.chmod(0o644)
            with self.assertRaisesRegex(MigrationError, "state is unsafe"):
                self.run.pending()
            with self.assertRaisesRegex(MigrationError, "state is unsafe"):
                self.back_up()
            reserve.assert_called_once()

    def test_dangling_state_folder_link_is_not_reported_as_empty(self):
        self.run._directory.parent.mkdir(parents=True, mode=0o700)
        self.run._directory.symlink_to(self.root / "missing")
        with self.assertRaisesRegex(MigrationError, "linked path"):
            self.run.pending()

    def test_published_run_keeps_unverified_scratch_until_review(self):
        def stage(*args, **kwargs):
            journal = args[2]
            scratch_root = journal.directory / "scratch"
            scratch_root.mkdir(mode=0o700)
            scratch = scratch_root / "aa"
            scratch.mkdir(mode=0o700)
            (scratch / "orphan.cvchunk").write_bytes(b"unverified ciphertext")
            return "staged"

        with patch.object(self.upload, "reserve_with_base",
                          side_effect=lambda *, reservation_id, apply:
                          (reservation_id, None)), patch(
                "codex_migrate.vault_hosted_live_run.stage_reserved_hosted_snapshot",
                side_effect=stage) as staged, patch.object(
                self.upload, "publish_hosted_stage") as publish:
            publish.side_effect = lambda reservation_id, value, *, apply: {
                "snapshotId": self.run.pending()["snapshotId"],
                "verifiedObjectCount": 3}
            with self.assertRaisesRegex(MigrationError, "scratch is not empty"):
                self.back_up()
            pending = self.run.pending()
            journal = self.run._directory / ("snapshot-" + pending["snapshotId"])
            orphan = journal / "scratch/aa/orphan.cvchunk"
            self.assertTrue(orphan.is_file())
            orphan.unlink()  # Disposable test fixture, not customer data.
            with patch.object(self.upload, "reservation_receipt", return_value={
                    "state": "published", "snapshotId": pending["snapshotId"],
                    "verifiedObjectCount": 3}):
                self.assertEqual(self.back_up()["snapshotId"], pending["snapshotId"])
            staged.assert_called_once()
            publish.assert_called_once()
            self.assertIsNone(self.run.pending())
            self.assertFalse(journal.exists())

    def test_published_run_refuses_a_foreign_journal_identity(self):
        with patch.object(self.upload, "reserve_with_base",
                          side_effect=lambda *, reservation_id, apply:
                          (reservation_id, BASE)), patch(
                "codex_migrate.vault_hosted_live_run.stage_reserved_hosted_snapshot",
                side_effect=MigrationError("interrupted")):
            with self.assertRaisesRegex(MigrationError, "interrupted"):
                self.back_up()
        pending = self.run.pending()
        journal = self.run._directory / ("snapshot-" + pending["snapshotId"])
        header = journal / "journal.json"
        changed = json.loads(header.read_text())
        changed["reservationId"] = OTHER
        header.write_text(json.dumps(changed))
        header.chmod(0o600)
        with patch.object(self.upload, "reservation_receipt", return_value={
                "state": "published", "snapshotId": pending["snapshotId"],
                "verifiedObjectCount": 3}):
            with self.assertRaisesRegex(MigrationError, "belongs to another run"):
                self.back_up()
        self.assertEqual(self.run.pending(), pending)
        self.assertTrue(header.exists())

    def test_cleanup_interruption_reconciles_published_run_without_restaging(self):
        with patch.object(self.upload, "reserve_with_base",
                          side_effect=lambda *, reservation_id, apply:
                          (reservation_id, None)), patch(
                "codex_migrate.vault_hosted_live_run.stage_reserved_hosted_snapshot",
                return_value="staged") as stage, patch.object(
                self.upload, "publish_hosted_stage") as publish:
            publish.side_effect = lambda reservation_id, value, *, apply: {
                "snapshotId": self.run.pending()["snapshotId"],
                "verifiedObjectCount": 3}
            with patch("codex_migrate.vault_hosted_live_run._fsync_directory",
                       side_effect=OSError("interrupted cleanup")):
                with self.assertRaisesRegex(MigrationError, "needs local cleanup"):
                    self.back_up()
            pending = self.run.pending()
            self.assertFalse((self.run._directory /
                              ("snapshot-" + pending["snapshotId"])).exists())
            with patch.object(self.upload, "reservation_receipt", return_value={
                    "state": "published", "snapshotId": pending["snapshotId"],
                    "verifiedObjectCount": 3}):
                self.assertEqual(self.back_up()["snapshotId"], pending["snapshotId"])
            stage.assert_called_once()
            publish.assert_called_once()
            self.assertIsNone(self.run.pending())

    def test_cleanup_preflight_os_error_keeps_published_run_retryable(self):
        with patch.object(self.upload, "reserve_with_base",
                          side_effect=lambda *, reservation_id, apply:
                          (reservation_id, None)), patch(
                "codex_migrate.vault_hosted_live_run.stage_reserved_hosted_snapshot",
                return_value="staged") as stage, patch.object(
                self.upload, "publish_hosted_stage") as publish:
            publish.side_effect = lambda reservation_id, value, *, apply: {
                "snapshotId": self.run.pending()["snapshotId"],
                "verifiedObjectCount": 3}
            with patch.object(self.run, "_private_file",
                              side_effect=PermissionError("synthetic preflight failure")):
                with self.assertRaisesRegex(MigrationError, "needs local cleanup"):
                    self.back_up()
            pending = self.run.pending()
            self.assertIsNotNone(pending)
            with patch.object(self.upload, "reservation_receipt", return_value={
                    "state": "published", "snapshotId": pending["snapshotId"],
                    "verifiedObjectCount": 3}):
                self.assertEqual(self.back_up()["snapshotId"], pending["snapshotId"])
            stage.assert_called_once()
            publish.assert_called_once()
            self.assertIsNone(self.run.pending())

    def test_abandon_requires_confirmation_and_server_release_before_new_run(self):
        pending = self.interrupted_run(scratch_name="b" * 62 + ".cvchunk")
        journal = self.run._directory / ("snapshot-" + pending["snapshotId"])
        with patch.object(self.upload, "reservation_receipt") as receipt, \
                patch.object(self.upload, "abandon") as abandon:
            with self.assertRaisesRegex(MigrationError, "explicit confirmation"):
                self.run.abandon_pending()
            receipt.assert_not_called()
            abandon.assert_not_called()
            receipt.return_value = {"state": "active"}
            self.assertEqual(self.run.abandon_pending(apply=True), "cleanup_pending")
            abandon.assert_called_once_with(pending["reservationId"], apply=True)
            self.assertEqual(self.run.pending()["phase"], "cleanup_pending")
            self.assertTrue(journal.exists())
            with self.assertRaisesRegex(MigrationError, "verified cleanup"):
                self.back_up()
            receipt.return_value = {"state": "released"}
            self.assertEqual(self.run.abandon_pending(apply=True), "released")
            self.assertIsNone(self.run.pending())
            self.assertFalse(journal.exists())

    def test_lost_abandon_ack_reconciles_without_repeat_action(self):
        pending = self.interrupted_run()
        with patch.object(self.upload, "reservation_receipt",
                          side_effect=[{"state": "active"},
                                       {"state": "cleanup_pending"},
                                       {"state": "released"}]) as receipt, \
                patch.object(self.upload, "abandon",
                             side_effect=MigrationError("ACK lost")) as abandon:
            self.assertEqual(self.run.abandon_pending(apply=True), "cleanup_pending")
            self.assertEqual(self.run.pending()["phase"], "cleanup_pending")
            self.assertEqual(self.run.abandon_pending(apply=True), "released")
            abandon.assert_called_once_with(pending["reservationId"], apply=True)
            self.assertEqual(receipt.call_count, 3)
            self.assertIsNone(self.run.pending())

    def test_unconfirmed_abandon_keeps_active_run_retryable(self):
        pending = self.interrupted_run()
        with patch.object(self.upload, "reservation_receipt",
                          return_value={"state": "active"}), patch.object(
                self.upload, "abandon", side_effect=MigrationError("network down")):
            self.assertEqual(self.run.cleanup_status(), "active")
            with self.assertRaisesRegex(MigrationError, "could not be confirmed"):
                self.run.abandon_pending(apply=True)
        self.assertEqual(self.run.pending(), pending)

    def test_released_run_keeps_unknown_scratch_for_review(self):
        pending = self.interrupted_run(scratch_name="unknown.cvchunk")
        journal = self.run._directory / ("snapshot-" + pending["snapshotId"])
        with patch.object(self.upload, "reservation_receipt",
                          return_value={"state": "released"}):
            with self.assertRaisesRegex(MigrationError, "unknown files"):
                self.run.abandon_pending(apply=True)
        self.assertEqual(self.run.pending()["phase"], "cleanup_pending")
        self.assertTrue((journal / "scratch/aa/unknown.cvchunk").exists())

    def test_abandon_reconciles_published_run_without_quarantine(self):
        pending = self.interrupted_run()
        with patch.object(self.upload, "reservation_receipt", return_value={
                "state": "published", "snapshotId": pending["snapshotId"],
                "verifiedObjectCount": 1}), patch.object(
                self.upload, "abandon") as abandon:
            self.assertEqual(self.run.abandon_pending(apply=True), "published")
            abandon.assert_not_called()
            self.assertIsNone(self.run.pending())


if __name__ == "__main__":
    unittest.main()
