import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from codex_migrate.errors import MigrationError
from codex_migrate.vault_hosted_setup_flow import HostedSetupFlow


DEVICE = "11111111-1111-4111-8111-111111111111"
ACCOUNT = "22222222-2222-4222-8222-222222222222"
VAULT = "33333333-3333-4333-8333-333333333333"
PURCHASE = "cs_test_fixture." + "a" * 64
CODE = "hve1_" + "B" * 43
IDENTITY = {"deviceId": DEVICE, "accountId": ACCOUNT, "vaultId": VAULT}


class HostedSetupFlowTests(unittest.TestCase):
    def setUp(self):
        self.saved = {}
        self.registry = SimpleNamespace(read=lambda: dict(self.saved),
            update=self.saved.update, sync_recovery_checkpoint=Mock())
        self.client = Mock()
        self.client.create_device.return_value = DEVICE
        self.client.claim.return_value = dict(IDENTITY)
        self.client.resolve.return_value = dict(IDENTITY)
        self.patch_client = patch(
            "codex_migrate.vault_hosted_setup_flow.HostedEnrollmentClient",
            return_value=self.client)
        self.factory = self.patch_client.start()
        self.addCleanup(self.patch_client.stop)
        self.flow = HostedSetupFlow(self.registry)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = str(Path(temporary.name).resolve())

    def step(self, action, **values):
        run = self.flow.stage(action, {**values, "apply": True})
        self.assertEqual(self.flow.snapshot()["status"], "running")
        run()
        return self.flow.snapshot()

    def email(self):
        return self.step("send_code", purchase_link=(
            "https://codexbackup.segeren.com/purchase#" + PURCHASE))

    def test_email_pairing_saves_before_claim_and_never_grants_protection(self):
        self.assertEqual(self.email()["phase"], "email")
        def claim(*args, **kwargs):
            self.assertEqual(self.saved, {"hosted_setup_device": {"deviceId": DEVICE}})
            self.registry.sync_recovery_checkpoint.assert_called_once()
            return dict(IDENTITY)
        self.client.claim.side_effect = claim
        result = self.step("pair", code=CODE)
        self.assertEqual(result["phase"], "paired")
        self.assertEqual(self.saved, {"hosted_setup_device": IDENTITY})
        self.assertEqual(self.registry.sync_recovery_checkpoint.call_count, 2)
        self.client.begin.assert_called_once_with(PURCHASE, apply=True)
        self.client.claim.assert_called_once_with(PURCHASE, CODE, DEVICE, apply=True)
        self.client.resolve.assert_not_called()
        self.assertFalse(result["upload_authorized"])
        self.assertFalse(result["automatic_protection_verified"])
        self.assertEqual(self.flow._proof, {})
        for secret in (PURCHASE, CODE):
            self.assertNotIn(secret, json.dumps(result))
            self.assertNotIn(secret, json.dumps(self.saved))
        self.client.backup_clients.assert_not_called()

    def test_lost_claim_response_resolves_exact_device_after_restart(self):
        self.email()
        self.client.claim.side_effect = MigrationError("private " + CODE)
        self.assertEqual(self.step("pair", code=CODE)["phase"], "pairing_uncertain")
        self.assertNotIn("Retry the current step", self.flow.snapshot()["error"])
        self.flow = HostedSetupFlow(self.registry)
        with self.assertRaises(MigrationError):
            self.flow.stage("pair", {"code": CODE, "apply": True})
        self.assertEqual(self.step("resolve")["phase"], "paired")
        self.client.create_device.assert_called_once()
        self.client.claim.assert_called_once()
        self.client.resolve.assert_called_once_with(DEVICE)

    def test_failed_checkpoint_write_does_not_claim_or_create_a_second_device(self):
        self.email()
        self.registry.update = Mock(side_effect=OSError("private"))
        result = self.step("pair", code=CODE)
        self.assertEqual(result["phase"], "pairing_checkpoint")
        self.client.claim.assert_not_called()
        self.registry.sync_recovery_checkpoint.assert_not_called()
        self.registry.update = self.saved.update
        self.assertEqual(self.step("retry_save")["phase"], "paired")
        self.client.create_device.assert_called_once()
        self.client.claim.assert_called_once()

    def test_failed_full_sync_does_not_claim_and_retry_keeps_device(self):
        self.email()
        self.registry.sync_recovery_checkpoint.side_effect = OSError("disk")
        self.assertEqual(self.step("pair", code=CODE)["phase"], "pairing_checkpoint")
        self.client.claim.assert_not_called()
        self.registry.sync_recovery_checkpoint.side_effect = None
        self.assertEqual(self.step("retry_save")["phase"], "paired")
        self.client.create_device.assert_called_once()

    def test_crash_before_checkpoint_cannot_send_a_remote_claim(self):
        self.email()
        self.registry.update = Mock(side_effect=KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            self.step("pair", code=CODE)
        self.assertEqual(self.saved, {})
        self.client.claim.assert_not_called()
        self.client.resolve.assert_not_called()
        self.client.backup_clients.assert_not_called()
        # The native credential can remain unclaimed; never delete arbitrary
        # Keychain state or mistake it for an enrolled remote account.
        self.registry.update = self.saved.update
        self.flow = HostedSetupFlow(self.registry)
        self.assertEqual(self.flow.snapshot()["phase"], "start")

    def test_restart_before_claim_requires_fresh_proof_for_same_device(self):
        self.saved["hosted_setup_device"] = {"deviceId": DEVICE}
        self.flow = HostedSetupFlow(self.registry)
        self.client.resolve.side_effect = MigrationError("not paired yet")
        self.assertEqual(self.step("resolve")["status"], "failed")
        self.assertEqual(self.step("reauthorize")["phase"], "start")
        self.email()
        self.assertEqual(self.step("pair", code=CODE)["phase"], "paired")
        self.client.create_device.assert_not_called()
        self.assertEqual(self.client.resolve.call_count, 2)
        self.client.claim.assert_called_once()

    def test_reauthorization_resolves_committed_claim_without_replaying(self):
        self.saved["hosted_setup_device"] = {"deviceId": DEVICE}
        self.flow = HostedSetupFlow(self.registry)
        self.step("reauthorize")
        self.email()
        self.assertEqual(self.step("pair", code=CODE)["phase"], "paired")
        self.client.create_device.assert_not_called()
        self.client.claim.assert_not_called()
        self.client.resolve.assert_called_once_with(DEVICE)

    def test_final_save_failure_reconciles_without_reclaiming(self):
        self.email()
        count = 0
        def save(**values):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError("disk full")
            self.saved.update(values)
        self.registry.update = save
        self.assertEqual(self.step("pair", code=CODE)["status"], "failed")
        self.assertEqual(self.step("resolve")["phase"], "paired")
        self.client.claim.assert_called_once()
        self.client.create_device.assert_called_once()

    def test_resolve_refuses_identity_change_and_keeps_saved_binding(self):
        self.saved["hosted_setup_device"] = dict(IDENTITY)
        self.flow = HostedSetupFlow(self.registry)
        self.client.resolve.return_value = {**IDENTITY, "vaultId": ACCOUNT}
        self.assertEqual(self.step("resolve")["status"], "failed")
        self.assertEqual(self.saved["hosted_setup_device"], IDENTITY)
        self.client.claim.assert_not_called()

    def test_bad_identity_response_cannot_be_saved_as_paired(self):
        for bad in (None, {**IDENTITY, "deviceId": VAULT},
                    {**IDENTITY, "token": "private"},
                    {**IDENTITY, "accountId": "bad"}):
            with self.subTest(bad=bad):
                self.saved.clear()
                self.flow = HostedSetupFlow(self.registry)
                self.email()
                self.client.claim.return_value = bad
                result = self.step("pair", code=CODE)
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["phase"], "pairing_uncertain")
                self.assertEqual(self.saved["hosted_setup_device"], {"deviceId": DEVICE})

    def test_bad_checkpoint_is_refused_without_provider_work(self):
        for bad in ([], {}, {"deviceId": "bad"},
                    {"deviceId": DEVICE, "token": "private"},
                    {"deviceId": DEVICE, "accountId": ACCOUNT}):
            self.saved["hosted_setup_device"] = bad
            with self.assertRaises(MigrationError):
                HostedSetupFlow(self.registry)
        self.factory.assert_not_called()

    def test_input_validation_is_read_only_and_requires_exact_confirmation(self):
        for action, payload in (
                ("send_code", {"purchase_link": PURCHASE}),
                ("send_code", {"purchase_link": PURCHASE, "apply": 1}),
                ("send_code", {"purchase_link": PURCHASE, "apply": True, "token": CODE}),
                ("send_code", {"purchase_link": "https://other.example/purchase#" + PURCHASE,
                               "apply": True}),
                ("pair", {"code": CODE, "apply": True}),
                ("resolve", {"apply": True})):
            with self.assertRaises(MigrationError):
                self.flow.stage(action, payload)
        self.assertEqual(self.saved, {})
        self.factory.assert_not_called()

    def test_pending_step_cannot_be_reentered_or_disclose_input(self):
        run = self.flow.stage("send_code", {"purchase_link": PURCHASE, "apply": True})
        with self.assertRaises(MigrationError):
            self.flow.stage("send_code", {"purchase_link": PURCHASE, "apply": True})
        self.assertNotIn(PURCHASE, json.dumps(self.flow.snapshot()))
        run()

    def test_provider_failure_is_generic_and_retry_keeps_email_phase(self):
        self.client.begin.side_effect = RuntimeError("private " + PURCHASE)
        result = self.email()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["phase"], "start")
        self.assertNotIn(PURCHASE, json.dumps(result))
        self.assertFalse(result["upload_authorized"])
        self.assertFalse(result["automatic_protection_verified"])
        self.assertEqual(self.saved, {})

    def test_explicit_key_setup_requires_pairing_and_never_starts_backup(self):
        with self.assertRaises(MigrationError):
            self.flow.stage("prepare_key", {"apply": True})
        self.email()
        self.step("pair", code=CODE)
        secret = "CV1-" + "A" * 43
        self.flow._keys = Mock()
        self.flow._keys.prepare.return_value = secret
        result = self.step("prepare_key")
        self.assertEqual(result["phase"], "key_save")
        self.assertEqual(result["recovery_key"], secret)
        self.flow._keys.prepare.assert_called_once_with(IDENTITY)
        run = self.flow.stage("confirm_key", {"recovery_key": secret, "apply": True})
        self.assertNotIn("recovery_key", self.flow.snapshot())
        run()
        result = self.flow.snapshot()
        self.assertEqual(result["phase"], "key_ready")
        self.assertNotIn("recovery_key", result)
        self.assertIsNone(self.flow._recovery_key)
        self.assertFalse(result["upload_authorized"])
        self.assertFalse(result["automatic_protection_verified"])
        self.assertNotIn(secret, json.dumps(self.saved))
        self.client.backup_clients.assert_not_called()

    def test_failed_saved_copy_confirmation_stays_in_key_step(self):
        self.email()
        self.step("pair", code=CODE)
        secret = "CV1-" + "A" * 43
        self.flow._keys = Mock()
        self.flow._keys.prepare.return_value = secret
        self.flow._keys.confirm.side_effect = MigrationError("private " + secret)
        self.step("prepare_key")
        result = self.step("confirm_key", recovery_key=secret)
        self.assertEqual(result["phase"], "key_save")
        self.assertEqual(result["status"], "failed")
        self.assertNotIn(secret, result["error"])
        self.client.backup_clients.assert_not_called()

    def test_resolve_retains_confirmed_key_state_without_revealing_it(self):
        self.saved["hosted_setup_device"] = dict(IDENTITY)
        self.flow = HostedSetupFlow(self.registry)
        self.flow._keys = Mock()
        self.flow._keys.confirmed.return_value = True
        result = self.step("resolve")
        self.assertEqual(result["phase"], "key_ready")
        self.assertNotIn("recovery_key", result)
        self.flow._keys.prepare.assert_not_called()
        self.client.claim.assert_not_called()

    def test_saved_key_requires_same_full_device_binding_before_any_provider_work(self):
        self.saved["hosted_setup_key"] = {
            "binding": dict(IDENTITY), "saved_copy_confirmed": False,
            "metadata": {"format": "codex-vault", "version": 1,
                         "key_id": "44444444-4444-4444-8444-444444444444",
                         "created_at": "2026-10-01T00:00:00+00:00"},
        }
        for binding in (None, {"deviceId": DEVICE}, {"deviceId": ACCOUNT},
                        {**IDENTITY, "vaultId": ACCOUNT}):
            with self.subTest(binding=binding):
                self.saved.pop("hosted_setup_device", None)
                if binding is not None:
                    self.saved["hosted_setup_device"] = binding
                with self.assertRaises(MigrationError):
                    HostedSetupFlow(self.registry)
        self.factory.assert_not_called()
        self.client.claim.assert_not_called()
        self.saved["hosted_setup_device"] = dict(IDENTITY)
        self.assertEqual(HostedSetupFlow(self.registry).snapshot()["phase"], "pairing_uncertain")

    def ready_for_backup(self):
        key_id = "44444444-4444-4444-8444-444444444444"
        self.saved.update(hosted_setup_device=dict(IDENTITY), hosted_setup_key={
            "binding": dict(IDENTITY), "saved_copy_confirmed": True,
            "metadata": {"format": "codex-vault", "version": 1, "key_id": key_id,
                         "created_at": "2026-10-01T00:00:00+00:00"}})
        self.flow = HostedSetupFlow(self.registry, self.home)
        self.step("resolve")
        self.flow._keys = Mock()
        self.flow._keys.backup_metadata.return_value = (
            Path("/synthetic/state/hosted-key.json"), key_id)
        self.flow._keys.confirmed_binding.return_value = {**IDENTITY, "keyId": key_id}
        self.receipt = {"applied": True, "snapshot_id": VAULT, "status": "published",
                        "source_coverage": "complete", "at_risk_threads": 0,
                        "automatic_protection_verified": False}
        patcher = patch("codex_migrate.vault_hosted_setup_flow.back_up_hosted_history",
                        return_value=dict(self.receipt))
        self.backup = patcher.start()
        self.addCleanup(patcher.stop)
        return key_id

    def test_restart_resolves_rotated_device_without_rebinding_the_key_or_receipt(self):
        from codex_migrate.vault_hosted_connection import save_connection
        key_id = self.ready_for_backup()
        self.step("first_backup")
        before = json.dumps(self.saved, sort_keys=True)
        anchor = {**IDENTITY, "keyId": key_id}
        new_device = "55555555-5555-4555-8555-555555555555"
        save_connection(self.home, anchor)
        save_connection(self.home, {**anchor, "deviceId": new_device}, previous_device=DEVICE)
        self.flow = HostedSetupFlow(self.registry, self.home)
        self.client.resolve.return_value = {**IDENTITY, "deviceId": new_device}
        result = self.step("resolve")
        self.assertEqual(result["phase"], "backup_ready")
        self.client.resolve.assert_called_with(new_device)
        self.assertEqual(json.dumps(self.saved, sort_keys=True), before)

    def test_schedule_steps_require_good_receipt_and_keep_explicit_key_binding(self):
        key_id = self.ready_for_backup()
        with self.assertRaises(MigrationError):
            self.flow.stage("enable_schedule", {"apply": True})
        self.step("first_backup")
        with patch("codex_migrate.vault_hosted_setup_flow._safe_json", return_value={"key_id": key_id}), patch(
                "codex_migrate.vault_hosted_setup_flow.install_hosted_schedule") as install:
            self.assertEqual(self.step("enable_schedule")["status"], "ready")
            install.assert_called_once_with(self.home, DEVICE, {"key_id": key_id},
                expected_binding={**IDENTITY, "keyId": key_id}, apply=True)
        self.backup.return_value = {**self.receipt, "status": "needs_attention",
                                   "at_risk_threads": 1}
        self.step("first_backup")
        with self.assertRaises(MigrationError):
            self.flow.stage("enable_schedule", {"apply": True})

    def test_stop_is_local_and_available_before_rechecking_network_after_restart(self):
        key_id = self.ready_for_backup()
        self.step("first_backup")
        self.flow = HostedSetupFlow(self.registry, self.home)
        self.client.reset_mock()
        with patch("codex_migrate.vault_hosted_setup_flow.remove_hosted_schedule") as stop:
            self.assertEqual(self.step("disable_schedule")["status"], "ready")
            stop.assert_called_once_with(self.home,
                expected_binding={**IDENTITY, "keyId": key_id}, apply=True)
        self.client.resolve.assert_not_called()
        self.assertEqual(self.flow.snapshot()["phase"], "pairing_uncertain")

    def test_lost_schedule_reply_preserves_backup_receipt_and_reports_uncertainty(self):
        self.ready_for_backup()
        self.step("first_backup")
        before = json.dumps(self.saved, sort_keys=True)
        with patch("codex_migrate.vault_hosted_setup_flow.remove_hosted_schedule",
                   side_effect=MigrationError("synthetic private bearer")):
            result = self.step("disable_schedule")
        self.assertEqual(result["status"], "failed")
        self.assertIn("schedule change could not be confirmed", result["error"])
        self.assertNotIn("private bearer", result["error"])
        self.assertEqual(json.dumps(self.saved, sort_keys=True), before)

    def test_first_backup_requires_saved_key_and_explicit_separate_action(self):
        with self.assertRaises(MigrationError):
            self.flow.stage("first_backup", {"apply": True})
        key_id = self.ready_for_backup()
        self.backup.assert_not_called()
        result = self.step("first_backup")
        self.backup.assert_called_once_with(self.home, DEVICE,
            "/synthetic/state/hosted-key.json",
            expected_binding={**IDENTITY, "keyId": key_id}, apply=True)
        self.assertEqual(result["phase"], "backup_ready")
        self.assertEqual(result["last_backup"], self.receipt)
        self.assertFalse(result["automatic_protection_verified"])
        self.assertFalse(result["upload_authorized"])
        self.assertEqual(self.saved["hosted_setup_backup"]["receipt"], self.receipt)
        self.assertNotIn("keyId", result["last_backup"])
        self.client.backup_clients.assert_not_called()

    def test_first_backup_failure_keeps_previous_receipt_and_same_retry_binding(self):
        self.ready_for_backup()
        self.step("first_backup")
        previous = json.dumps(self.saved["hosted_setup_backup"], sort_keys=True)
        self.backup.side_effect = MigrationError("private bearer and transcript")
        result = self.step("first_backup")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["phase"], "backup_ready")
        self.assertEqual(result["last_backup"], self.receipt)
        self.assertEqual(json.dumps(self.saved["hosted_setup_backup"], sort_keys=True), previous)
        self.assertNotIn("private bearer", result["error"])
        self.assertIn("same connection and key", result["error"])
        self.backup.side_effect = None
        self.assertEqual(self.step("first_backup")["status"], "ready")
        self.assertEqual(self.backup.call_args_list[0], self.backup.call_args_list[-1])

    def test_setup_restart_preserves_receipt_but_still_requires_connection_check(self):
        self.ready_for_backup()
        self.step("first_backup")
        self.flow = HostedSetupFlow(self.registry, self.home)
        self.assertEqual(self.flow.snapshot()["phase"], "pairing_uncertain")
        with self.assertRaises(MigrationError):
            self.flow.stage("first_backup", {"apply": True})
        result = self.step("resolve")
        self.assertEqual(result["phase"], "backup_ready")
        self.assertEqual(result["last_backup"], self.receipt)
        self.assertFalse(result["automatic_protection_verified"])

    def test_bad_backup_receipts_cannot_be_saved_or_claim_success(self):
        self.ready_for_backup()
        for field, value in (("applied", 1), ("snapshot_id", "bad"),
                ("automatic_protection_verified", True), ("status", "protected"),
                ("at_risk_threads", False), ("source_coverage", "unknown")):
            with self.subTest(field=field):
                self.backup.return_value = {**self.receipt, field: value}
                result = self.step("first_backup")
                self.assertEqual(result["status"], "failed")
                self.assertNotIn("hosted_setup_backup", self.saved)
        self.backup.return_value = {**self.receipt, "private": "secret"}
        self.assertEqual(self.step("first_backup")["status"], "failed")

    def test_at_risk_capture_keeps_explicit_attention_and_no_protection(self):
        self.ready_for_backup()
        self.backup.return_value = {**self.receipt, "status": "needs_attention",
                                   "source_coverage": "needs_attention", "at_risk_threads": 2}
        result = self.step("first_backup")
        self.assertEqual(result["phase"], "backup_ready")
        self.assertEqual(result["last_backup"]["status"], "needs_attention")
        self.assertFalse(result["automatic_protection_verified"])

    def test_unsaved_key_or_checkpoint_failure_cannot_finish_backup_step(self):
        self.ready_for_backup()
        self.flow._keys.backup_metadata.side_effect = MigrationError("unconfirmed")
        self.assertEqual(self.step("first_backup")["status"], "failed")
        self.backup.assert_not_called()
        self.flow._keys.backup_metadata.side_effect = None
        self.registry.sync_recovery_checkpoint.side_effect = OSError("disk")
        result = self.step("first_backup")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["phase"], "key_ready")
        self.assertNotIn("last_backup", result)

    def test_mismatched_saved_backup_refuses_startup_before_provider_work(self):
        self.ready_for_backup()
        self.step("first_backup")
        self.factory.reset_mock()
        saved = dict(self.saved["hosted_setup_backup"])
        for bad in ({**saved, "binding": {**IDENTITY, "accountId": VAULT}},
                    {**saved, "key_id": DEVICE},
                    {**saved, "checked_at": "bad"},
                    {**saved, "receipt": {**self.receipt, "at_risk_threads": -1}}):
            with self.subTest(bad=bad):
                self.saved["hosted_setup_backup"] = bad
                with self.assertRaises(MigrationError):
                    HostedSetupFlow(self.registry, "/synthetic/home")
        self.factory.assert_not_called()

    def pending_upload(self, *, state="active"):
        return {"pending": True, "reservation_id": DEVICE, "snapshot_id": VAULT,
                "local_phase": "active", "remote_status": state,
                "can_abandon": state != "published", "automatic_protection_verified": False}

    def check_upload(self, value=None):
        with patch("codex_migrate.vault_hosted_setup_flow.pending_hosted_upload",
                   return_value=value if value is not None else self.pending_upload()) as inspect:
            result = self.step("check_upload")
            return result, inspect

    def test_upload_review_requires_key_and_does_not_change_backup_receipt(self):
        with self.assertRaises(MigrationError):
            self.flow.stage("check_upload", {"apply": True})
        key_id = self.ready_for_backup()
        self.step("first_backup")
        before = json.dumps(self.saved, sort_keys=True)
        result, inspect = self.check_upload()
        inspect.assert_called_once_with(self.home, DEVICE, "/synthetic/state/hosted-key.json",
            expected_binding={**IDENTITY, "keyId": key_id})
        self.assertEqual(result["phase"], "pending_upload")
        self.assertEqual(result["last_backup"], self.receipt)
        self.assertFalse(result["automatic_protection_verified"])
        self.assertEqual(json.dumps(self.saved, sort_keys=True), before)
        self.backup.assert_called_once()

    def test_upload_abandon_requires_separate_exact_boolean_confirmation(self):
        self.ready_for_backup()
        self.check_upload()
        with patch("codex_migrate.vault_hosted_setup_flow.abandon_hosted_upload") as abandon:
            for values in ({"reservation_id": DEVICE, "confirm_abandon": False},
                           {"reservation_id": DEVICE, "confirm_abandon": 1},
                           {"reservation_id": VAULT, "confirm_abandon": True},
                           {"reservation_id": "bad", "confirm_abandon": True}):
                with self.subTest(values=values), self.assertRaises(MigrationError):
                    self.flow.stage("abandon_upload", {**values, "apply": True})
            abandon.assert_not_called()

    def test_published_upload_cannot_be_abandoned_in_setup(self):
        self.ready_for_backup()
        self.check_upload(self.pending_upload(state="published"))
        with self.assertRaises(MigrationError):
            self.flow.stage("abandon_upload", {"reservation_id": DEVICE,
                "confirm_abandon": True, "apply": True})
        self.step("leave_upload_review")
        self.assertEqual(self.flow.snapshot()["phase"], "key_ready")
        self.assertEqual(self.flow.snapshot()["pending_upload"]["remote_status"], "published")

    def test_cleanup_pending_then_release_keeps_same_target_and_prior_backup(self):
        key_id = self.ready_for_backup()
        self.step("first_backup")
        before = json.dumps(self.saved, sort_keys=True)
        self.check_upload()
        receipt = {"applied": True, "reservation_id": DEVICE,
                   "status": "cleanup_pending", "automatic_protection_verified": False}
        with patch("codex_migrate.vault_hosted_setup_flow.abandon_hosted_upload",
                   return_value=receipt) as abandon:
            result = self.step("abandon_upload", reservation_id=DEVICE, confirm_abandon=True)
            self.assertEqual(result["phase"], "pending_upload")
            self.assertEqual(result["pending_upload"]["remote_status"], "cleanup_pending")
            abandon.assert_called_once_with(self.home, DEVICE, "/synthetic/state/hosted-key.json",
                expected_binding={**IDENTITY, "keyId": key_id}, reservation_id=DEVICE, apply=True)
            receipt["status"] = "released"
            result = self.step("abandon_upload", reservation_id=DEVICE, confirm_abandon=True)
            self.assertEqual(result["phase"], "backup_ready")
            self.assertNotIn("pending_upload", result)
        self.assertEqual(json.dumps(self.saved, sort_keys=True), before)
        self.assertEqual(result["last_backup"], self.receipt)

    def test_retry_clears_review_only_after_verified_backup_and_checkpoint(self):
        self.ready_for_backup()
        self.check_upload(self.pending_upload(state="published"))
        self.step("leave_upload_review")
        self.backup.side_effect = MigrationError("reply not verified")
        self.assertEqual(self.step("first_backup")["status"], "failed")
        self.assertEqual(self.flow.snapshot()["pending_upload"]["reservation_id"], DEVICE)
        self.backup.side_effect = None
        self.registry.sync_recovery_checkpoint.side_effect = OSError("disk full")
        self.assertEqual(self.step("first_backup")["status"], "failed")
        self.assertIn("pending_upload", self.flow.snapshot())
        self.registry.sync_recovery_checkpoint.side_effect = None
        result = self.step("first_backup")
        self.assertEqual(result["phase"], "backup_ready")
        self.assertNotIn("pending_upload", result)
        self.assertEqual(result["last_backup"], self.receipt)

    def test_lost_cleanup_reply_keeps_exact_review_and_redacts_private_error(self):
        self.ready_for_backup()
        self.check_upload()
        with patch("codex_migrate.vault_hosted_setup_flow.abandon_hosted_upload",
                   side_effect=MigrationError("private token and signed URL")) as abandon:
            result = self.step("abandon_upload", reservation_id=DEVICE, confirm_abandon=True)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["pending_upload"]["reservation_id"], DEVICE)
            self.assertNotIn("private token", result["error"])
            self.assertIn("Check upload status", result["error"])
            abandon.assert_called_once()
        self.assertEqual(self.check_upload({"pending": False,
            "automatic_protection_verified": False})[0]["phase"], "key_ready")

    def test_replacement_review_invalidates_old_confirmation_and_return_does_not_release(self):
        self.ready_for_backup()
        self.step("first_backup")
        self.check_upload()
        self.check_upload({**self.pending_upload(), "reservation_id": VAULT})
        with self.assertRaises(MigrationError):
            self.flow.stage("abandon_upload", {"reservation_id": DEVICE,
                "confirm_abandon": True, "apply": True})
        with patch("codex_migrate.vault_hosted_setup_flow.abandon_hosted_upload") as abandon:
            self.step("leave_upload_review")
            abandon.assert_not_called()
        with self.assertRaises(MigrationError):
            self.flow.stage("enable_schedule", {"apply": True})

    def test_restart_never_automatically_repeats_upload_cleanup(self):
        self.ready_for_backup()
        self.check_upload()
        with patch("codex_migrate.vault_hosted_setup_flow.abandon_hosted_upload") as abandon:
            self.flow = HostedSetupFlow(self.registry, self.home)
            self.assertEqual(self.flow.snapshot()["phase"], "pairing_uncertain")
            self.assertNotIn("pending_upload", self.flow.snapshot())
            with self.assertRaises(MigrationError):
                self.flow.stage("abandon_upload", {"reservation_id": DEVICE,
                    "confirm_abandon": True, "apply": True})
            abandon.assert_not_called()

    def test_invalid_status_or_cleanup_receipt_cannot_repaint_success(self):
        self.ready_for_backup()
        pending = self.pending_upload()
        for value in (None, [], {**pending, "private": "secret"},
                      {**pending, "can_abandon": 1}, {**pending, "reservation_id": "bad"},
                      {**pending, "remote_status": "published"},
                      {"pending": False, "automatic_protection_verified": True}):
            with self.subTest(value=value), patch(
                    "codex_migrate.vault_hosted_setup_flow.pending_hosted_upload", return_value=value):
                self.assertEqual(self.step("check_upload")["status"], "failed")
                self.assertNotIn("pending_upload", self.flow.snapshot())
        self.check_upload()
        for status in ("published", "active", "unknown"):
            with self.subTest(status=status), patch(
                    "codex_migrate.vault_hosted_setup_flow.abandon_hosted_upload",
                    return_value={"applied": True, "reservation_id": DEVICE, "status": status,
                                  "automatic_protection_verified": False}):
                self.assertEqual(self.step("abandon_upload", reservation_id=DEVICE,
                    confirm_abandon=True)["status"], "failed")
                self.assertEqual(self.flow.snapshot()["phase"], "pending_upload")


if __name__ == "__main__":
    unittest.main()
