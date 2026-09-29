import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from codex_migrate.errors import MigrationError
from codex_migrate.vault_hosted_enrollment_client import HostedEnrollmentClient
from codex_migrate.vault_hosted_recovery_client import HostedRecoveryClient
from codex_migrate.vault_hosted_upload_client import HostedUploadClient


ACCOUNT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
VAULT = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
DEVICE = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
TOKEN = "hv1_" + "a" * 43
TOKEN_HASH = hashlib.sha256(b"codex-vault-hosted-session-v1\0" +
                            TOKEN.encode("ascii")).hexdigest()
NEW_DEVICE = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
NEW_TOKEN = "hv1_" + "d" * 43
NEW_TOKEN_HASH = hashlib.sha256(b"codex-vault-hosted-session-v1\0" +
                                NEW_TOKEN.encode("ascii")).hexdigest()
PURCHASE = "cs_test_fixture." + "b" * 64
CODE = "hve1_" + "c" * 43


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_POST(self):
        if self.path not in ("/api/hosted-enrollment", "/api/hosted-recovery"):
            self.send_error(404)
            return
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.calls.append((body, self.headers.get("Authorization")))
        if self.path == "/api/hosted-recovery":
            result = {"accountId": self.server.recovery_account,
                      "workerOrigin": self.server.worker_origin, "latest": None}
            raw = json.dumps(result).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if body["action"] in ("claim", "claim_recovery") and self.server.lose_claim_reply:
            # The server has acted, but the client cannot know if it did.
            self.close_connection = True
            return
        if self.server.rotation_active and body["action"] == "resolve":
            expected = (NEW_DEVICE if self.server.rotated else DEVICE)
            bearer = (NEW_TOKEN if self.server.rotated else TOKEN)
            if (body["deviceId"] != expected or
                    self.headers.get("Authorization") != "Bearer " + bearer):
                self.send_error(503)
                return
        if body["action"] == "rotate" and self.server.rotation_active:
            if (self.server.rotated or body["oldDeviceId"] != DEVICE or
                    body["newDeviceId"] != NEW_DEVICE or
                    body["newDeviceTokenHash"] != NEW_TOKEN_HASH or
                    self.headers.get("Authorization") != "Bearer " + TOKEN):
                self.send_error(503)
                return
            self.server.rotated = True
            if self.server.lose_rotate_reply:
                self.close_connection = True
                return
        if body["action"] in ("begin", "begin_recovery"):
            result = {"status": "sent"}
        elif body["action"] == "list_recovery_vaults":
            result = {"vaults": [{"vaultId": VAULT,
                                  "lastGoodAt": "2026-09-27T12:00:00.000Z"}]}
        elif body["action"] in ("claim", "claim_recovery"):
            result = {"accountId": ACCOUNT, "vaultId": VAULT,
                      "deviceId": body["deviceId"]}
        elif body["action"] == "rotate":
            result = {"accountId": ACCOUNT, "vaultId": VAULT,
                      "deviceId": body["newDeviceId"]}
        else:
            result = {"accountId": ACCOUNT, "vaultId": VAULT,
                      "deviceId": body["deviceId"]}
        raw = json.dumps(result).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class HostedEnrollmentClientTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.server.calls = []
        self.server.lose_claim_reply = False
        self.server.rotation_active = False
        self.server.rotated = False
        self.server.lose_rotate_reply = False
        self.server.recovery_account = ACCOUNT
        self.server.worker_origin = "http://127.0.0.1:54321"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.helper_calls = []

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def client(self):
        return HostedEnrollmentClient(
            "http://127.0.0.1:%d" % self.server.server_port,
            allow_loopback_http=True)

    def fake_helper(self, _path, arguments):
        self.helper_calls.append(arguments)
        if arguments == ["hosted-device-create"]:
            return {"device_id": DEVICE, "token_hash": TOKEN_HASH}
        if arguments == ["hosted-device-list"]:
            return {"devices": [{"device_id": DEVICE, "token_hash": TOKEN_HASH},
                                {"device_id": NEW_DEVICE,
                                 "token_hash": NEW_TOKEN_HASH}]}
        if arguments == ["hosted-device-read", "--device-id", DEVICE]:
            return {"device_id": DEVICE, "token_hash": TOKEN_HASH, "token": TOKEN}
        if arguments == ["hosted-device-read", "--device-id", NEW_DEVICE]:
            return {"device_id": NEW_DEVICE, "token_hash": NEW_TOKEN_HASH,
                    "token": NEW_TOKEN}
        raise AssertionError("unexpected helper operation")

    def test_email_claim_and_resolve_keep_bearer_out_of_claim(self):
        with patch("codex_migrate.vault_hosted_enrollment_client._helper_path",
                   return_value=Path("/synthetic/helper")), \
                patch("codex_migrate.vault_hosted_enrollment_client._run_helper",
                      side_effect=self.fake_helper):
            client = self.client()
            self.assertIsNone(client.begin(PURCHASE, apply=True))
            device_id = client.create_device(apply=True)
            self.assertEqual(device_id, DEVICE)
            claimed = client.claim(PURCHASE, CODE, device_id, apply=True)
            self.assertEqual((claimed["accountId"], claimed["vaultId"]), (ACCOUNT, VAULT))
            self.assertEqual(client.resolve(device_id), claimed)
        self.assertEqual([call[0]["action"] for call in self.server.calls],
                         ["begin", "claim", "resolve"])
        self.assertTrue(all(auth is None for _, auth in self.server.calls[:2]))
        self.assertEqual(self.server.calls[2][1], "Bearer " + TOKEN)
        self.assertEqual(self.server.calls[1][0]["deviceTokenHash"], TOKEN_HASH)
        self.assertNotIn("token", self.server.calls[1][0])
        self.assertEqual(self.helper_calls, [
            ["hosted-device-create"], ["hosted-device-list"],
            ["hosted-device-read", "--device-id", DEVICE]])

    def test_lost_claim_reply_keeps_saved_key_for_resolution(self):
        self.server.lose_claim_reply = True
        with patch("codex_migrate.vault_hosted_enrollment_client._helper_path",
                   return_value=Path("/synthetic/helper")), \
                patch("codex_migrate.vault_hosted_enrollment_client._run_helper",
                      side_effect=self.fake_helper):
            client = self.client()
            device_id = client.create_device(apply=True)
            with self.assertRaisesRegex(MigrationError, "could not be confirmed"):
                client.claim(PURCHASE, CODE, device_id, apply=True)
            self.server.lose_claim_reply = False
            recovered = client.resolve(device_id)
            self.assertEqual(recovered["accountId"], ACCOUNT)
        self.assertEqual(self.helper_calls.count(["hosted-device-create"]), 1)
        self.assertFalse(any("delete" in part for call in self.helper_calls
                             for part in call))

    def test_rotation_resolves_new_bearer_after_lost_ack_without_replay(self):
        self.server.rotation_active = True
        self.server.lose_rotate_reply = True
        with patch("codex_migrate.vault_hosted_enrollment_client._helper_path",
                   return_value=Path("/synthetic/helper")), \
                patch("codex_migrate.vault_hosted_enrollment_client._run_helper",
                      side_effect=self.fake_helper):
            client = self.client()
            expected = {"accountId": ACCOUNT, "vaultId": VAULT,
                        "deviceId": NEW_DEVICE}
            self.assertEqual(client.rotate_device(DEVICE, NEW_DEVICE,
                             ACCOUNT, VAULT, apply=True), expected)
            self.assertEqual(client.rotate_device(DEVICE, NEW_DEVICE,
                             ACCOUNT, VAULT, apply=True), expected)
        actions = [body["action"] for body, _ in self.server.calls]
        self.assertEqual(actions, ["resolve", "resolve", "rotate", "resolve",
                                   "resolve"])
        self.assertEqual(actions.count("rotate"), 1)
        self.assertEqual(self.server.calls[2][1], "Bearer " + TOKEN)
        self.assertNotIn(TOKEN, json.dumps(self.server.calls[2][0]))
        self.assertFalse(any("delete" in part for call in self.helper_calls
                             for part in call))

    def test_rotation_refuses_mismatched_identity_or_missing_confirmation(self):
        self.server.rotation_active = True
        with patch("codex_migrate.vault_hosted_enrollment_client._helper_path",
                   return_value=Path("/synthetic/helper")), \
                patch("codex_migrate.vault_hosted_enrollment_client._run_helper",
                      side_effect=self.fake_helper):
            client = self.client()
            with self.assertRaisesRegex(MigrationError, "changed identity"):
                client.rotate_device(DEVICE, NEW_DEVICE, NEW_DEVICE, VAULT,
                                     apply=True)
            self.assertFalse(self.server.rotated)
            with self.assertRaisesRegex(MigrationError, "explicit confirmation"):
                client.rotate_device(DEVICE, NEW_DEVICE, ACCOUNT, VAULT)

    def test_rotation_refuses_corrupt_new_keychain_bearer_before_server_mutation(self):
        def corrupt_new(path, arguments):
            result = self.fake_helper(path, arguments)
            if arguments == ["hosted-device-read", "--device-id", NEW_DEVICE]:
                return {**result, "token_hash": "0" * 64}
            return result
        with patch("codex_migrate.vault_hosted_enrollment_client._helper_path",
                   return_value=Path("/synthetic/helper")), \
                patch("codex_migrate.vault_hosted_enrollment_client._run_helper",
                      side_effect=corrupt_new):
            with self.assertRaisesRegex(MigrationError, "credential is invalid"):
                self.client().rotate_device(DEVICE, NEW_DEVICE, ACCOUNT, VAULT,
                                            apply=True)
        self.assertEqual(self.server.calls, [])

    def test_keychain_credential_opens_native_upload_and_recovery_clients(self):
        with patch("codex_migrate.vault_hosted_enrollment_client._helper_path",
                   return_value=Path("/synthetic/helper")), \
                patch("codex_migrate.vault_hosted_enrollment_client._run_helper",
                      side_effect=self.fake_helper):
            client = self.client()
            upload = client.upload_client(DEVICE, "http://127.0.0.1:54321")
            recovery = client.recovery_client(DEVICE)
        self.assertIsInstance(upload, HostedUploadClient)
        self.assertIsInstance(recovery, HostedRecoveryClient)
        self.assertEqual((upload._account_id, upload._vault_id), (ACCOUNT, VAULT))
        self.assertEqual(recovery._vault_id, VAULT)
        self.assertNotIn(TOKEN, repr(upload) + repr(recovery))
        self.assertEqual([body["action"] for body, _ in self.server.calls],
                         ["resolve", "resolve"])
        self.assertTrue(all(auth == "Bearer " + TOKEN
                            for _, auth in self.server.calls))
        self.assertEqual(self.helper_calls, [
            ["hosted-device-read", "--device-id", DEVICE],
            ["hosted-device-read", "--device-id", DEVICE]])

    def test_backup_clients_use_authenticated_worker_origin_and_one_keychain_read(self):
        with patch("codex_migrate.vault_hosted_enrollment_client._helper_path",
                   return_value=Path("/synthetic/helper")), \
                patch("codex_migrate.vault_hosted_enrollment_client._run_helper",
                      side_effect=self.fake_helper):
            upload, recovery = self.client().backup_clients(DEVICE)
        self.assertEqual(upload._worker_origin, self.server.worker_origin)
        self.assertEqual(upload._account_id, ACCOUNT)
        self.assertEqual(recovery._vault_id, VAULT)
        self.assertEqual(self.helper_calls,
                         [["hosted-device-read", "--device-id", DEVICE]])
        self.assertEqual([body["action"] for body, _ in self.server.calls],
                         ["resolve", "latest"])
        self.assertTrue(all(auth == "Bearer " + TOKEN
                            for _, auth in self.server.calls))
        self.assertNotIn(TOKEN, repr(upload) + repr(recovery))

    def test_backup_clients_refuse_account_substitution(self):
        self.server.recovery_account = DEVICE
        with patch("codex_migrate.vault_hosted_enrollment_client._helper_path",
                   return_value=Path("/synthetic/helper")), \
                patch("codex_migrate.vault_hosted_enrollment_client._run_helper",
                      side_effect=self.fake_helper):
            with self.assertRaisesRegex(MigrationError, "account changed"):
                self.client().backup_clients(DEVICE)

    def test_lost_mac_pairs_new_device_to_existing_vault(self):
        with patch("codex_migrate.vault_hosted_enrollment_client._helper_path",
                   return_value=Path("/synthetic/helper")), \
                patch("codex_migrate.vault_hosted_enrollment_client._run_helper",
                      side_effect=self.fake_helper):
            client = self.client()
            self.assertIsNone(client.begin_recovery(PURCHASE, apply=True))
            vaults = client.list_recovery_vaults(PURCHASE, CODE)
            self.assertEqual(vaults, [{"vaultId": VAULT,
                                      "lastGoodAt": "2026-09-27T12:00:00.000Z"}])
            device_id = client.create_device(apply=True)
            self.assertEqual(client.claim_recovery(PURCHASE, CODE, VAULT,
                                                   device_id, apply=True),
                             {"accountId": ACCOUNT, "vaultId": VAULT,
                              "deviceId": DEVICE})
            self.assertEqual(client.resolve(device_id)["vaultId"], VAULT)
        self.assertEqual([call[0]["action"] for call in self.server.calls],
                         ["begin_recovery", "list_recovery_vaults",
                          "claim_recovery", "resolve"])
        self.assertEqual(self.server.calls[2][0]["deviceTokenHash"], TOKEN_HASH)
        self.assertNotIn(TOKEN, json.dumps(self.server.calls[2][0]))
        self.assertIsNone(self.server.calls[2][1])

    def test_recovery_claim_refuses_vault_substitution_and_lost_reply_is_resolvable(self):
        self.server.lose_claim_reply = True
        with patch("codex_migrate.vault_hosted_enrollment_client._helper_path",
                   return_value=Path("/synthetic/helper")), \
                patch("codex_migrate.vault_hosted_enrollment_client._run_helper",
                      side_effect=self.fake_helper):
            client = self.client()
            with self.assertRaisesRegex(MigrationError, "could not be confirmed"):
                client.claim_recovery(PURCHASE, CODE, VAULT, DEVICE, apply=True)
            self.server.lose_claim_reply = False
            self.assertEqual(client.resolve(DEVICE)["vaultId"], VAULT)
            with self.assertRaisesRegex(MigrationError, "changed the selected Vault"):
                client.claim_recovery(PURCHASE, CODE, ACCOUNT, DEVICE, apply=True)

    def test_bad_inputs_refuse_network_or_keychain_work(self):
        with self.assertRaises(MigrationError):
            HostedEnrollmentClient("http://example.com")
        with self.assertRaises(MigrationError):
            HostedEnrollmentClient("https://user:secret@example.com")
        client = self.client()
        for operation in [
            lambda: client.begin(PURCHASE),
            lambda: client.create_device(),
            lambda: client.claim(PURCHASE, CODE, DEVICE),
            lambda: client.begin_recovery(PURCHASE),
            lambda: client.claim_recovery(PURCHASE, CODE, VAULT, DEVICE),
        ]:
            with self.assertRaisesRegex(MigrationError, "explicit confirmation"):
                operation()
        with self.assertRaises(MigrationError):
            client.begin("not-a-purchase", apply=True)
        with self.assertRaises(MigrationError):
            client.claim(PURCHASE, "bad", DEVICE, apply=True)
        with self.assertRaises(MigrationError):
            client.resolve("bad")
        self.assertEqual(self.server.calls, [])
        self.assertEqual(self.helper_calls, [])

    def test_mismatched_keychain_digest_refuses_resolve_before_network(self):
        def forged(_path, _arguments):
            return {"device_id": DEVICE, "token_hash": "0" * 64,
                    "token": TOKEN}
        with patch("codex_migrate.vault_hosted_enrollment_client._helper_path",
                   return_value=Path("/synthetic/helper")), \
                patch("codex_migrate.vault_hosted_enrollment_client._run_helper",
                      side_effect=forged):
            with self.assertRaisesRegex(MigrationError, "credential is invalid"):
                self.client().resolve(DEVICE)
            with self.assertRaisesRegex(MigrationError, "credential is invalid"):
                self.client().upload_client(DEVICE, "http://127.0.0.1:54321")
            with self.assertRaisesRegex(MigrationError, "credential is invalid"):
                self.client().recovery_client(DEVICE)
        self.assertEqual(self.server.calls, [])


if __name__ == "__main__":
    unittest.main()
