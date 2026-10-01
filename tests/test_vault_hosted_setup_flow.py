import json
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


if __name__ == "__main__":
    unittest.main()
