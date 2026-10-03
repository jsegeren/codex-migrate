"""Explicit failed-upload cleanup never becomes deletion of a backup."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from codex_migrate.cli import main
from codex_migrate.errors import MigrationError
from codex_migrate.vault_hosted_connection import save_connection
from codex_migrate.vault_hosted_pending import pending_hosted_upload, abandon_hosted_upload
from codex_migrate.vault_hosted_schedule import SERVICE_ORIGIN
from codex_migrate.vault_schedule import _update_lock


DEVICE = "11111111-1111-4111-8111-111111111111"
ACCOUNT = "22222222-2222-4222-8222-222222222222"
VAULT = "33333333-3333-4333-8333-333333333333"
KEY = "44444444-4444-4444-8444-444444444444"
RESERVATION = "55555555-5555-4555-8555-555555555555"
SNAPSHOT = "66666666-6666-4666-8666-666666666666"
BINDING = {"deviceId": DEVICE, "accountId": ACCOUNT, "vaultId": VAULT, "keyId": KEY}


class PendingUploadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = str(Path(temporary.name).resolve())
        self.metadata = Path(self.home) / "vault.json"
        self.metadata.write_text(json.dumps({"format": "codex-vault", "version": 1,
            "key_id": KEY, "created_at": "2026-10-03T00:00:00+00:00"}))
        self.metadata.chmod(0o600)
        self.helper = Path(self.home) / "helper"
        self.helper.write_text("#!/bin/sh\nexit 1\n")
        self.helper.chmod(0o700)
        self.upload = Mock()
        self.upload._account_id = ACCOUNT
        self.upload._vault_id = VAULT
        self.upload.reservation_receipt.return_value = {"state": "active"}
        self.recovery = Mock()
        self.client = Mock()
        self.client.backup_clients.return_value = (self.upload, self.recovery)
        self.run = Mock()
        self.run.pending.return_value = {"reservationId": RESERVATION,
            "snapshotId": SNAPSHOT, "phase": "active"}
        self.run.abandon_pending.return_value = "cleanup_pending"
        self.factory = self.patch("HostedEnrollmentClient", return_value=self.client)
        self.live = self.patch("HostedLiveBackupRun", return_value=self.run)

    def patch(self, name, **kwargs):
        patcher = patch("codex_migrate.vault_hosted_pending." + name, **kwargs)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def inspect(self, **kwargs):
        return pending_hosted_upload(self.home, DEVICE, str(self.metadata),
            crypto_helper=str(self.helper), **kwargs)

    def abandon(self, **kwargs):
        return abandon_hosted_upload(self.home, DEVICE, str(self.metadata),
            crypto_helper=str(self.helper),
            **{"reservation_id": RESERVATION, "apply": True, **kwargs})

    def test_inspection_returns_opaque_ids_without_changing_the_service(self):
        result = self.inspect(expected_binding=BINDING)
        self.assertEqual(result, {"pending": True, "reservation_id": RESERVATION,
            "snapshot_id": SNAPSHOT, "local_phase": "active", "remote_status": "active",
            "can_abandon": True, "automatic_protection_verified": False})
        self.factory.assert_called_once_with(SERVICE_ORIGIN)
        self.run.pending.assert_called_once_with(expected_key_id=KEY)
        self.upload.reservation_receipt.assert_called_once_with(RESERVATION)
        self.run.abandon_pending.assert_not_called()
        self.upload.abandon.assert_not_called()

    def test_absent_pending_is_not_backup_protection(self):
        self.run.pending.return_value = None
        self.assertEqual(self.inspect(), {"pending": False, "automatic_protection_verified": False})
        self.upload.reservation_receipt.assert_not_called()

    def test_published_receipt_requires_exact_snapshot_and_cannot_offer_abandon(self):
        self.upload.reservation_receipt.return_value = {"state": "published", "snapshotId": SNAPSHOT,
                                                        "verifiedObjectCount": 3}
        self.assertFalse(self.inspect()["can_abandon"])
        self.upload.reservation_receipt.return_value["snapshotId"] = VAULT
        with self.assertRaises(MigrationError):
            self.inspect()

    def test_cleanup_pending_and_released_stay_explicit(self):
        for state in ("cleanup_pending", "released"):
            self.upload.reservation_receipt.return_value = {"state": state}
            self.assertEqual(self.inspect()["remote_status"], state)
            self.run.abandon_pending.return_value = state
            result = self.abandon()
            self.assertEqual(result["status"], state)
            self.assertFalse(result["automatic_protection_verified"])
        self.run.abandon_pending.assert_called_with(expected_key_id=KEY,
            expected_reservation_id=RESERVATION, apply=True)

    def test_plan_or_invalid_exact_confirmation_never_reaches_network(self):
        for kwargs in ({"apply": False}, {"apply": 1}, {"reservation_id": "bad"},
                       {"reservation_id": None}):
            with self.subTest(kwargs=kwargs), self.assertRaises(MigrationError):
                self.abandon(**kwargs)
        self.factory.assert_not_called()

    def test_wrong_connection_or_metadata_stops_before_provider_work(self):
        for binding in ({}, {**BINDING, "keyId": VAULT}, {**BINDING, "deviceId": VAULT},
                        {**BINDING, "accountId": True}, {**BINDING, "extra": "private"}):
            with self.subTest(binding=binding), self.assertRaises(MigrationError):
                self.inspect(expected_binding=binding)
        self.factory.assert_not_called()
        data = json.loads(self.metadata.read_text())
        for change in ({"recovery_mode": "business-v1"}, {"version": True}, {"key_id": "bad"}):
            self.metadata.write_text(json.dumps({**data, **change}))
            with self.assertRaises(MigrationError):
                self.inspect()
        self.factory.assert_not_called()

    def test_rotated_device_preserves_same_account_vault_and_key(self):
        save_connection(self.home, BINDING)
        save_connection(self.home, {**BINDING, "deviceId": SNAPSHOT}, previous_device=DEVICE)
        self.inspect(expected_binding=BINDING)
        self.client.backup_clients.assert_called_once_with(SNAPSHOT, crypto_helper=str(self.helper))

    def test_remote_identity_change_never_abandons_anything(self):
        self.upload._account_id = VAULT
        with self.assertRaises(MigrationError):
            self.abandon(expected_binding=BINDING)
        self.run.abandon_pending.assert_not_called()
        self.live.assert_not_called()

    def test_update_or_concurrent_scheduled_run_blocks_cleanup(self):
        with _update_lock(self.home, nonblocking=True):
            with self.assertRaises(MigrationError):
                self.abandon()
        self.factory.assert_not_called()

    def test_provider_errors_are_redacted_and_pending_state_kept(self):
        private = "hv1_private https://provider.invalid/?grant=private"
        self.run.abandon_pending.side_effect = RuntimeError(private)
        sentinel = Path(self.home) / "sentinel.json"
        sentinel.write_text("keep this state")
        with self.assertRaises(MigrationError) as caught:
            self.abandon()
        self.assertNotIn(private, str(caught.exception))
        self.assertEqual(sentinel.read_text(), "keep this state")

    def test_invalid_cleanup_result_never_claims_success(self):
        for status in ("none", "published", "active", "unexpected"):
            self.run.abandon_pending.return_value = status
            with self.subTest(status=status), self.assertRaises(MigrationError):
                self.abandon()

    def test_cli_abandon_plan_and_apply_name_exact_reservation(self):
        argv = ["vault", "--source-home", self.home, "hosted-abandon-upload",
                "--device-id", DEVICE, "--key-metadata", str(self.metadata),
                "--reservation-id", RESERVATION]
        with redirect_stdout(io.StringIO()), patch(
                "codex_migrate.vault_hosted_pending.abandon_hosted_upload") as abandon:
            self.assertEqual(main(argv), 0)
            abandon.assert_not_called()
            abandon.return_value = {"status": "cleanup_pending"}
            self.assertEqual(main(argv + ["--apply", "--json"]), 0)
            abandon.assert_called_once_with(self.home, DEVICE, str(self.metadata),
                crypto_helper=None, reservation_id=RESERVATION, apply=True)


if __name__ == "__main__":
    unittest.main()
