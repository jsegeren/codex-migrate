import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from codex_migrate.errors import MigrationError
from codex_migrate.vault_hosted_business_enrollment_client import (
    BusinessHostedEnrollmentClient,
)
from codex_migrate.vault_hosted_recovery_client import HostedRecoveryClient
from codex_migrate.vault_hosted_upload_client import HostedUploadClient


ACCOUNT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SEAT = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
VAULT = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
DEVICE = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
TOKEN = "hvb1_" + "a" * 43
HASH = hashlib.sha256(b"codex-backup-business-device-v1\0" +
                      TOKEN.encode("ascii")).hexdigest()
CODE = "hvwe1_" + "b" * 43
ADMIN_TOKEN = "hva1_" + "c" * 43
RECOVERY_CODE = "hvcr1_" + "d" * 43
REQUEST = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
NEW_DEVICE = "ffffffff-ffff-4fff-8fff-ffffffffffff"
NEW_TOKEN = "hvb1_" + "e" * 43
NEW_HASH = hashlib.sha256(b"codex-backup-business-device-v1\0" +
                          NEW_TOKEN.encode("ascii")).hexdigest()


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_POST(self):
        if self.path not in ("/api/hosted-business-device",
                             "/api/hosted-business-recovery-device",
                             "/api/hosted-business-health",
                             "/api/hosted-recovery"):
            self.send_error(404)
            return
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        authorization = self.headers.get("Authorization")
        self.server.calls.append((body, authorization))
        if self.path == "/api/hosted-recovery":
            response = {"accountId": self.server.recovery_account,
                        "workerOrigin": self.server.worker_origin, "latest": None}
        elif self.path == "/api/hosted-business-health":
            valid_reports = (
                {"action": "report", "deviceId": DEVICE,
                 "reportedState": "unchanged", "snapshotId": VAULT},
                {"action": "report", "deviceId": DEVICE,
                 "reportedState": "failed", "snapshotId": None},
            )
            if (body not in valid_reports or
                    authorization != "Bearer " + TOKEN or
                    self.server.device_purpose != "worker"):
                self.send_error(503)
                return
            response = {"accountId": ACCOUNT, "seatId": SEAT,
                        "vaultId": VAULT,
                        "checkedAt": "2026-09-30T18:00:00Z"}
        elif (self.path == "/api/hosted-business-recovery-device" and
              body["action"] == "begin"):
            response = {"requestId": REQUEST, "status": "sent"}
        elif body["action"] == "claim":
            if self.server.lose_claim_reply:
                self.close_connection = True
                return
            response = {"accountId": ACCOUNT, "seatId": SEAT,
                        "vaultId": VAULT, "deviceId": DEVICE}
        elif body["action"] == "rotate":
            if (not self.server.rotation_active or self.server.rotated or
                    body["oldDeviceId"] != DEVICE or
                    body["newDeviceId"] != NEW_DEVICE or
                    body["newDeviceTokenHash"] != NEW_HASH or
                    authorization != "Bearer " + TOKEN):
                self.send_error(503)
                return
            self.server.rotated = True
            if self.server.lose_rotate_reply:
                self.close_connection = True
                return
            response = {"accountId": ACCOUNT, "seatId": SEAT,
                        "vaultId": VAULT, "deviceId": NEW_DEVICE}
        else:
            device_id = body["deviceId"]
            if self.server.rotation_active:
                expected_id = NEW_DEVICE if self.server.rotated else DEVICE
                expected_token = NEW_TOKEN if self.server.rotated else TOKEN
                if (device_id != expected_id or
                        authorization != "Bearer " + expected_token):
                    self.send_error(503)
                    return
            response = {"accountId": ACCOUNT, "seatId": SEAT,
                        "vaultId": VAULT, "deviceId": device_id,
                        "accessPurpose": self.server.device_purpose}
        raw = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class BusinessHostedEnrollmentClientTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.server.calls = []
        self.server.lose_claim_reply = False
        self.server.recovery_account = ACCOUNT
        self.server.worker_origin = "http://127.0.0.1:54321"
        self.server.rotation_active = False
        self.server.rotated = False
        self.server.lose_rotate_reply = False
        self.server.device_purpose = "worker"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.helper_calls = []

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def client(self):
        return BusinessHostedEnrollmentClient(
            "http://127.0.0.1:%d" % self.server.server_port,
            allow_loopback_http=True)

    def fake_helper(self, _path, arguments):
        self.helper_calls.append(arguments)
        if arguments == ["hosted-business-device-create"]:
            return {"device_id": DEVICE, "token_hash": HASH}
        if arguments == ["hosted-business-device-read", "--device-id", DEVICE]:
            return {"device_id": DEVICE, "token_hash": HASH, "token": TOKEN}
        if arguments == ["hosted-business-device-read", "--device-id", NEW_DEVICE]:
            return {"device_id": NEW_DEVICE, "token_hash": NEW_HASH,
                    "token": NEW_TOKEN}
        raise AssertionError("unexpected helper operation")

    def helper_patches(self):
        return (patch("codex_migrate.vault_hosted_business_enrollment_client._helper_path",
                      return_value=Path("/synthetic/helper")),
                patch("codex_migrate.vault_hosted_business_enrollment_client._run_helper",
                      side_effect=self.fake_helper))

    def test_claim_resolve_and_backup_use_separate_business_credential(self):
        path_patch, helper_patch = self.helper_patches()
        with path_patch, helper_patch:
            client = self.client()
            with self.assertRaisesRegex(MigrationError, "requires confirmation"):
                client.create_device()
            self.assertEqual(client.create_device(apply=True), DEVICE)
            self.assertEqual(client.claim(ACCOUNT, SEAT, VAULT, CODE, DEVICE,
                                          apply=True)["seatId"], SEAT)
            self.assertEqual(client.resolve(DEVICE)["vaultId"], VAULT)
            upload, recovery = client.backup_clients(DEVICE)
        self.assertIsInstance(upload, HostedUploadClient)
        self.assertIsInstance(recovery, HostedRecoveryClient)
        self.assertEqual((upload._account_id, upload._vault_id), (ACCOUNT, VAULT))
        self.assertEqual(upload._worker_origin, self.server.worker_origin)
        self.assertEqual([body["action"] for body, _ in self.server.calls],
                         ["claim", "resolve", "resolve", "latest"])
        self.assertIsNone(self.server.calls[0][1])
        self.assertEqual(self.server.calls[0][0]["deviceTokenHash"], HASH)
        self.assertNotIn(TOKEN, json.dumps(self.server.calls[0][0]))
        self.assertTrue(all(auth == "Bearer " + TOKEN
                            for _, auth in self.server.calls[1:]))
        self.assertEqual(self.helper_calls.count(
            ["hosted-business-device-read", "--device-id", DEVICE]), 3)
        self.assertNotIn(TOKEN, repr(upload) + repr(recovery))

    def test_lost_claim_reply_keeps_saved_device_for_resolution(self):
        self.server.lose_claim_reply = True
        path_patch, helper_patch = self.helper_patches()
        with path_patch, helper_patch:
            client = self.client()
            client.create_device(apply=True)
            with self.assertRaisesRegex(MigrationError, "could not be confirmed"):
                client.claim(ACCOUNT, SEAT, VAULT, CODE, DEVICE, apply=True)
            self.server.lose_claim_reply = False
            self.assertEqual(client.resolve(DEVICE)["accountId"], ACCOUNT)
        self.assertEqual(self.helper_calls.count(["hosted-business-device-create"]), 1)
        self.assertFalse(any("delete" in part for call in self.helper_calls
                             for part in call))

    def test_clean_mac_recovery_uses_admin_approval_and_read_only_client(self):
        path_patch, helper_patch = self.helper_patches()
        with path_patch, helper_patch:
            client = self.client()
            with self.assertRaisesRegex(MigrationError, "invalid"):
                client.begin_recovery(ACCOUNT, SEAT, VAULT,
                                      "Original employee Mac is lost",
                                      ADMIN_TOKEN)
            request_id = client.begin_recovery(ACCOUNT, SEAT, VAULT,
                "Original employee Mac is lost", ADMIN_TOKEN, apply=True)
            self.assertEqual(request_id, REQUEST)
            client.create_device(apply=True)
            identity = client.claim_recovery(ACCOUNT, SEAT, VAULT, REQUEST,
                RECOVERY_CODE, DEVICE, apply=True)
            self.assertEqual(identity["vaultId"], VAULT)
            self.server.device_purpose = "recovery"
            recovery = client.recovery_client(DEVICE)
        self.assertIsInstance(recovery, HostedRecoveryClient)
        self.assertEqual([body["action"] for body, _ in self.server.calls],
                         ["begin", "claim", "resolve", "latest"])
        self.assertEqual(self.server.calls[0][1], "Bearer " + ADMIN_TOKEN)
        self.assertIsNone(self.server.calls[1][1])
        self.assertEqual(self.server.calls[1][0]["deviceTokenHash"], HASH)
        self.assertNotIn(TOKEN, json.dumps(self.server.calls[1][0]))
        self.assertTrue(all(auth == "Bearer " + TOKEN
                            for _, auth in self.server.calls[2:]))
        self.assertNotIn(TOKEN, repr(recovery))

    def test_recovery_only_credential_cannot_start_worker_backup(self):
        self.server.device_purpose = "recovery"
        path_patch, helper_patch = self.helper_patches()
        with path_patch, helper_patch:
            with self.assertRaisesRegex(MigrationError, "recovery-only"):
                self.client().backup_clients(DEVICE)
        self.assertEqual([body["action"] for body, _ in self.server.calls],
                         ["resolve"])

    def test_worker_health_check_is_separate_from_recovery_authority(self):
        path_patch, helper_patch = self.helper_patches()
        with path_patch, helper_patch:
            client = self.client()
            self.assertEqual(client.report_backup_check(
                DEVICE, "unchanged", VAULT)["seatId"], SEAT)
            self.assertEqual(client.report_backup_check(
                DEVICE, "failed", None)["seatId"], SEAT)
            with self.assertRaisesRegex(MigrationError, "invalid"):
                client.report_backup_check(DEVICE, "failed", VAULT)
            self.server.device_purpose = "recovery"
            with self.assertRaisesRegex(MigrationError, "recovery-only"):
                client.report_backup_check(DEVICE, "unchanged", VAULT)
        self.assertEqual([body["action"] for body, _ in self.server.calls],
                         ["resolve", "report", "resolve", "report", "resolve"])

    def test_refuses_personal_token_and_account_substitution(self):
        def personal_helper(path, arguments):
            result = self.fake_helper(path, arguments)
            if arguments[0] == "hosted-business-device-read":
                return {**result, "token": "hv1_" + "a" * 43}
            return result
        path_patch, helper_patch = self.helper_patches()
        with path_patch, helper_patch:
            with self.assertRaisesRegex(MigrationError, "credential is invalid"):
                with patch("codex_migrate.vault_hosted_business_enrollment_client._run_helper",
                           side_effect=personal_helper):
                    self.client().resolve(DEVICE)
            self.server.recovery_account = DEVICE
            with self.assertRaisesRegex(MigrationError, "account changed"):
                self.client().backup_clients(DEVICE)
        self.assertEqual([body["action"] for body, _ in self.server.calls],
                         ["resolve", "latest"])

    def test_worker_rotation_reconciles_lost_ack_with_saved_new_key(self):
        self.server.rotation_active = True
        self.server.lose_rotate_reply = True
        path_patch, helper_patch = self.helper_patches()
        with path_patch, helper_patch:
            client = self.client()
            expected = {"accountId": ACCOUNT, "seatId": SEAT,
                        "vaultId": VAULT, "deviceId": NEW_DEVICE}
            self.assertEqual(client.rotate_device(DEVICE, NEW_DEVICE,
                ACCOUNT, SEAT, VAULT, apply=True), expected)
            self.assertEqual(client.rotate_device(DEVICE, NEW_DEVICE,
                ACCOUNT, SEAT, VAULT, apply=True), expected)
        actions = [body["action"] for body, _ in self.server.calls]
        self.assertEqual(actions, ["resolve", "resolve", "rotate",
                                   "resolve", "resolve"])
        self.assertEqual(actions.count("rotate"), 1)
        self.assertNotIn(NEW_TOKEN, json.dumps(self.server.calls[2][0]))
        self.assertFalse(any("delete" in part for call in self.helper_calls
                             for part in call))

    def test_rotation_refuses_wrong_expected_seat_without_mutation(self):
        self.server.rotation_active = True
        path_patch, helper_patch = self.helper_patches()
        with path_patch, helper_patch:
            with self.assertRaisesRegex(MigrationError, "identity changed"):
                self.client().rotate_device(DEVICE, NEW_DEVICE,
                    ACCOUNT, VAULT, VAULT, apply=True)
        self.assertFalse(self.server.rotated)


if __name__ == "__main__":
    unittest.main()
