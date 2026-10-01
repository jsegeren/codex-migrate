import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from codex_migrate.errors import MigrationError
from codex_migrate.vault_hosted_recovery_flow import HostedRecoveryFlow, purchase_token


DEVICE = "11111111-1111-4111-8111-111111111111"
VAULT = "22222222-2222-4222-8222-222222222222"
SNAPSHOT = "33333333-3333-4333-8333-333333333333"
PURCHASE = "cs_test_fixture." + "a" * 64
CODE = "hve1_" + "B" * 43
KEY = "CV1-" + "C" * 43
VERSION = {"snapshotId": SNAPSHOT, "totalObjects": 3,
           "totalBytes": 12345, "sourceCoverage": "complete"}


class HostedRecoveryFlowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.home = str(Path(self.temporary.name).resolve())
        self.output = str(Path(self.home) / "recovered")
        self.saved = {}
        self.registry = SimpleNamespace(read=lambda: dict(self.saved), update=self.saved.update,
                                        sync_recovery_checkpoint=Mock())
        self.flow = HostedRecoveryFlow(self.home, self.registry)
        self.client = Mock()
        self.client.create_device.return_value = DEVICE
        self.client.list_recovery_vaults.return_value = [{"vaultId": VAULT,
                                                       "lastGoodAt": None}]
        self.client.claim_recovery.return_value = {"vaultId": VAULT}
        self.client.resolve.return_value = {"vaultId": VAULT}
        self.client_patch = patch("codex_migrate.vault_hosted_recovery_flow.HostedEnrollmentClient",
                                  return_value=self.client)
        self.client_patch.start()
        self.addCleanup(self.client_patch.stop)
        self.addCleanup(self.temporary.cleanup)

    def step(self, action, **values):
        run = self.flow.stage(action, {**values, "apply": True})
        self.assertEqual(self.flow.snapshot()["status"], "running")
        run()
        return self.flow.snapshot()

    def pair(self):
        self.step("send_code", purchase_link="https://codexbackup.segeren.com/purchase#" + PURCHASE)
        self.step("list_vaults", code=CODE)
        return self.step("pair", vault_id=VAULT)

    def prepare(self):
        self.pair()
        with patch("codex_migrate.vault_hosted_recovery_flow.hosted_recovery_options",
                   return_value={"latest": VERSION, "latest_source_complete": VERSION}):
            self.step("versions")
        with patch("codex_migrate.vault_hosted_recovery_flow.prepare_hosted_recovery",
                   return_value={"vault": self.output, "snapshot_id": SNAPSHOT,
                                 "status": "awaiting_recovery_key"}) as prepare:
            state = self.step("prepare", snapshot_id=SNAPSHOT, output=self.output)
        self.assertEqual(prepare.call_args.kwargs["max_bytes"], VERSION["totalBytes"])
        return state

    def test_full_flow_keeps_key_confirmation_distinct_from_full_verification(self):
        self.assertEqual(self.prepare()["phase"], "prepared")
        with patch("codex_migrate.vault_hosted_recovery_flow.import_hosted_recovery_key",
                   return_value={"snapshot_id": SNAPSHOT, "status": "ready_to_download"}) as imported:
            state = self.step("import_key", recovery_key=KEY)
        self.assertEqual(state["phase"], "key_verified")
        self.assertNotIn("source_coverage", state)
        self.assertEqual(imported.call_args.kwargs["recovery_key"], KEY)
        result = {"snapshot_id": SNAPSHOT, "vault": self.output,
                  "needs_attention": False, "source_coverage": "complete", "at_risk_sources": 0}
        with patch("codex_migrate.vault_hosted_recovery_flow.recover_hosted_snapshot",
                   return_value=result) as download:
            state = self.step("download")
        self.assertEqual(state["phase"], "verified")
        self.assertEqual(download.call_args.kwargs, {
            "device_id": DEVICE, "output": self.output, "snapshot_id": SNAPSHOT,
            "max_bytes": VERSION["totalBytes"], "apply": True})
        self.assertEqual(self.saved, {"hosted_recovery_device": {
            "deviceId": DEVICE, "vaultId": VAULT}})
        for secret in (PURCHASE, CODE, KEY):
            self.assertNotIn(secret, json.dumps(state))
            self.assertNotIn(secret, json.dumps(self.saved))
        self.assertEqual(self.flow._proof, {})

    def test_lost_pairing_reply_resolves_exact_saved_device_even_after_restart(self):
        self.client.claim_recovery.side_effect = MigrationError("private " + CODE)
        state = self.pair()
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["phase"], "pairing_uncertain")
        self.assertNotIn(CODE, json.dumps(state))
        self.assertEqual(self.saved["hosted_recovery_device"]["deviceId"], DEVICE)
        self.flow = HostedRecoveryFlow(self.home, self.registry)
        with self.assertRaises(MigrationError):
            self.flow.stage("send_code", {"purchase_link": PURCHASE, "apply": True})
        self.assertEqual(self.step("resolve")["phase"], "paired")
        self.client.create_device.assert_called_once()
        self.client.claim_recovery.assert_called_once()
        self.client.resolve.assert_called_once_with(DEVICE)

    def test_resume_refuses_a_different_vault(self):
        self.saved["hosted_recovery_device"] = {"deviceId": DEVICE, "vaultId": VAULT}
        self.flow = HostedRecoveryFlow(self.home, self.registry)
        self.client.resolve.return_value = {"vaultId": SNAPSHOT}
        state = self.step("resolve")
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["phase"], "pairing_uncertain")
        self.client.create_device.assert_not_called()

    def test_failed_checkpoint_write_retries_same_device_before_claim(self):
        self.registry.update = Mock(side_effect=OSError("disk unavailable"))
        state = self.pair()
        self.assertEqual(state["phase"], "pairing_checkpoint")
        self.client.claim_recovery.assert_not_called()
        self.registry.sync_recovery_checkpoint.assert_not_called()
        self.registry.update = self.saved.update
        self.assertEqual(self.step("pair", vault_id=VAULT)["phase"], "paired")
        self.client.create_device.assert_called_once()
        self.registry.sync_recovery_checkpoint.assert_called_once()
        self.client.claim_recovery.assert_called_once()

    def test_failed_full_sync_cannot_claim_and_retry_keeps_identity(self):
        self.registry.sync_recovery_checkpoint.side_effect = OSError("sync failed")
        self.assertEqual(self.pair()["phase"], "pairing_checkpoint")
        self.client.claim_recovery.assert_not_called()
        with self.assertRaises(MigrationError):
            self.flow.stage("pair", {"vault_id": SNAPSHOT, "apply": True})
        self.registry.sync_recovery_checkpoint.side_effect = None
        self.assertEqual(self.step("pair", vault_id=VAULT)["phase"], "paired")
        self.client.create_device.assert_called_once()
        self.assertEqual(self.registry.sync_recovery_checkpoint.call_count, 2)

    def test_checkpoint_is_synced_before_claim_and_restart_only_resolves(self):
        order = []
        self.registry.sync_recovery_checkpoint.side_effect = lambda: order.append("synced")
        def crash_before_claim(*args, **kwargs):
            self.assertEqual(order, ["synced"])
            self.assertEqual(self.saved["hosted_recovery_device"]["deviceId"], DEVICE)
            raise KeyboardInterrupt()
        self.client.claim_recovery.side_effect = crash_before_claim
        with self.assertRaises(KeyboardInterrupt):
            self.pair()
        self.flow = HostedRecoveryFlow(self.home, self.registry)
        self.assertEqual(self.step("resolve")["phase"], "paired")
        self.client.create_device.assert_called_once()
        self.client.claim_recovery.assert_called_once()

    def test_restart_before_claim_reauthorizes_same_device_without_replacement(self):
        self.saved["hosted_recovery_device"] = {"deviceId": DEVICE, "vaultId": VAULT}
        self.flow = HostedRecoveryFlow(self.home, self.registry)
        self.client.resolve.side_effect = MigrationError("Not confirmed")
        self.assertEqual(self.step("resolve")["status"], "failed")
        self.assertEqual(self.step("reauthorize")["phase"], "start")
        self.assertEqual(self.pair()["phase"], "paired")
        self.client.create_device.assert_not_called()
        self.client.claim_recovery.assert_called_once_with(PURCHASE, CODE, VAULT, DEVICE, apply=True)

    def test_fresh_proof_after_lost_reply_resolves_without_repeating_claim(self):
        self.client.claim_recovery.side_effect = MigrationError("Reply lost")
        self.assertEqual(self.pair()["phase"], "pairing_uncertain")
        self.flow = HostedRecoveryFlow(self.home, self.registry)
        self.step("reauthorize")
        self.assertEqual(self.pair()["phase"], "paired")
        self.client.create_device.assert_called_once()
        self.client.claim_recovery.assert_called_once()

    def test_reauthorization_cannot_substitute_vault_or_bypass_email_proof(self):
        self.saved["hosted_recovery_device"] = {"deviceId": DEVICE, "vaultId": VAULT}
        self.flow = HostedRecoveryFlow(self.home, self.registry)
        self.step("reauthorize")
        with self.assertRaises(MigrationError):
            self.flow.stage("pair", {"vault_id": VAULT, "apply": True})
        self.step("send_code", purchase_link=PURCHASE)
        self.client.list_recovery_vaults.return_value = [{"vaultId": SNAPSHOT, "lastGoodAt": None}]
        self.assertEqual(self.step("list_vaults", code=CODE)["phase"], "email")
        self.client.create_device.assert_not_called()
        self.client.claim_recovery.assert_not_called()
        self.assertEqual(self.saved["hosted_recovery_device"]["vaultId"], VAULT)

    def test_wrong_key_can_retry_without_claiming_recovery_or_changing_plan(self):
        self.prepare()
        with patch("codex_migrate.vault_hosted_recovery_flow.import_hosted_recovery_key",
                   side_effect=MigrationError("private " + KEY)):
            state = self.step("import_key", recovery_key=KEY)
        self.assertEqual(state["phase"], "prepared")
        self.assertEqual(state["status"], "failed")
        self.assertNotIn(KEY, json.dumps(state))
        with self.assertRaises(MigrationError):
            self.flow.stage("download", {"apply": True})
        with patch("codex_migrate.vault_hosted_recovery_flow.import_hosted_recovery_key",
                   return_value={"snapshot_id": SNAPSHOT, "status": "ready_to_download"}):
            self.assertEqual(self.step("import_key", recovery_key=KEY)["phase"], "key_verified")

    def test_interrupted_download_retries_same_version_and_keeps_coverage_warning(self):
        self.prepare()
        with patch("codex_migrate.vault_hosted_recovery_flow.import_hosted_recovery_key",
                   return_value={"snapshot_id": SNAPSHOT, "status": "ready_to_download"}):
            self.step("import_key", recovery_key=KEY)
        with patch("codex_migrate.vault_hosted_recovery_flow.recover_hosted_snapshot",
                   side_effect=OSError("provider-private-failure")):
            state = self.step("download")
        self.assertEqual(state["phase"], "key_verified")
        with patch("codex_migrate.vault_hosted_recovery_flow.recover_hosted_snapshot",
                   return_value={"snapshot_id": SNAPSHOT, "vault": self.output,
                                 "needs_attention": True, "source_coverage": "incomplete",
                                 "at_risk_sources": 1}):
            self.assertTrue(self.step("download")["needs_attention"])

    def test_step_validation_precedes_provider_access(self):
        for action, payload in (
                ("send_code", {"purchase_link": PURCHASE, "apply": 1}),
                ("send_code", {"purchase_link": "https://attacker.test/purchase#" + PURCHASE,
                               "apply": True}),
                ("send_code", {"purchase_link": PURCHASE, "apply": True, "extra": "bad"}),
                ("download", {"apply": True}),
                ("unknown", {"apply": True})):
            with self.subTest(action=action), self.assertRaises(MigrationError):
                self.flow.stage(action, payload)
        self.client.begin_recovery.assert_not_called()
        self.client.create_device.assert_not_called()
        self.assertEqual(self.saved, {})

    def test_busy_step_refuses_another_request_and_snapshot_cannot_mutate_state(self):
        run = self.flow.stage("send_code", {"purchase_link": PURCHASE, "apply": True})
        with self.assertRaises(MigrationError):
            self.flow.stage("send_code", {"purchase_link": PURCHASE, "apply": True})
        state = self.flow.snapshot()
        state["phase"] = "verified"
        self.assertEqual(self.flow.snapshot()["phase"], "start")
        run()

    def test_invalid_saved_identity_is_not_silently_discarded(self):
        self.saved["hosted_recovery_device"] = {"deviceId": "bad", "vaultId": VAULT}
        with self.assertRaises(MigrationError):
            HostedRecoveryFlow(self.home, self.registry)
        self.assertEqual(self.saved["hosted_recovery_device"]["deviceId"], "bad")

    def test_purchase_link_only_accepts_known_origins_and_fragment_credentials(self):
        self.assertEqual(purchase_token(PURCHASE), PURCHASE)
        self.assertEqual(purchase_token("https://migrate.segeren.com/purchase#" + PURCHASE), PURCHASE)
        for value in (None, "https://codexbackup.segeren.com:443/purchase#" + PURCHASE,
                      "https://codexbackup.segeren.com/purchase?token=" + PURCHASE,
                      "https://codexbackup.segeren.com@attacker.test/purchase#" + PURCHASE,
                      "https://codexbackup.segeren.com/other#" + PURCHASE):
            with self.subTest(value_type=type(value).__name__), self.assertRaises(MigrationError):
                purchase_token(value)


if __name__ == "__main__":
    unittest.main()
