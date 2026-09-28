"""Synthetic sandbox proof: interrupted ciphertext staging never publishes."""

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch

from codex_migrate.errors import MigrationError
from codex_migrate.vault_hosted_backup_run import HostedBackupRun
from codex_migrate.vault_hosted_snapshot_stage import HostedSnapshotStage
from codex_migrate.vault_hosted_upload_client import (
    HostedPublicationStale, HostedUploadClient,
)
from codex_migrate.vault_remote_inventory import RemoteInventory, VaultTransferFile
from codex_migrate.vault_remote_transfer import (
    StageResult, StagedObject, stage_encrypted_snapshot,
)


ACCOUNT = "11111111-1111-4111-8111-111111111111"
VAULT = "22222222-2222-4222-8222-222222222222"
SNAPSHOT = "33333333-3333-4333-8333-333333333333"
RESERVATION = "44444444-4444-4444-8444-444444444444"
TOKEN = "hv1_" + "a" * 43
GRANT = "synthetic.valid"
EXPIRY = "2026-09-27T09:00:00.000Z"
FIRST_KEY = f"metadata/{SNAPSHOT}.json"
SECOND_KEY = f"refs/{SNAPSHOT}.json"
FIRST = b"opaque-encrypted-metadata"
SECOND = b"opaque-encrypted-reference"


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _json(self, status, value):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path not in ("/api/hosted-upload", "/api/hosted-receipt-page",
                             "/api/hosted-publish", "/api/hosted-verify-step",
                             "/api/hosted-publish-checkpointed",
                             "/api/hosted-published-chunks") or self.headers.get(
                "Authorization") != "Bearer " + TOKEN:
            return self._json(403, {"error": "access_denied"})
        size = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(size))
        self.server.actions.append(request.get("action", "lookup"))
        if request["vaultId"] != VAULT:
            return self._json(403, {"error": "access_denied"})
        if self.path == "/api/hosted-published-chunks":
            if sorted(request) != ["ids", "vaultId"]:
                return self._json(403, {"error": "access_denied"})
            return self._json(200, {"objects": [
                {"id": item, "bytes": facts[0], "sha256": facts[1]}
                for item, facts in sorted(self.server.published.items())
                if item in request["ids"]]})
        action = request["action"]
        if self.path == "/api/hosted-verify-step":
            if (action != "verify_next" or request["reservationId"] != RESERVATION or
                    request["snapshotId"] != SNAPSHOT):
                return self._json(403, {"error": "access_denied"})
            if self.server.fail_next_verify:
                self.server.fail_next_verify = False
                return self._json(503, {"error": "temporarily_unavailable"})
            if self.server.verify_calls == 0:
                self.server.verify_calls += 1
                return self._json(200, {"verifiedObjects": 3, "ready": False})
            self.server.verified_ready = True
            return self._json(200, {"verifiedObjects": 0, "ready": True})
        if self.path == "/api/hosted-publish-checkpointed":
            if (action != "publish_checkpointed" or
                    request["reservationId"] != RESERVATION or
                    request["snapshotId"] != SNAPSHOT or
                    not self.server.verified_ready):
                return self._json(503, {"error": "temporarily_unavailable"})
            if self.server.stale_next_checkpoint_publish:
                self.server.stale_next_checkpoint_publish = False
                return self._json(409, self.server.stale_body)
            if self.server.fail_next_checkpoint_publish:
                self.server.fail_next_checkpoint_publish = False
                return self._json(503, {"error": "temporarily_unavailable"})
            return self._json(200, {"snapshotId": SNAPSHOT,
                                    "verifiedObjectCount": 3})
        if self.path == "/api/hosted-publish":
            if (action != "publish" or request["reservationId"] != RESERVATION or
                    request["snapshotId"] != SNAPSHOT):
                return self._json(403, {"error": "access_denied"})
            if self.server.stale_next_publish:
                self.server.stale_next_publish = False
                return self._json(409, self.server.stale_body)
            if self.server.fail_next_publish:
                self.server.fail_next_publish = False
                return self._json(503, {"error": "temporarily_unavailable"})
            return self._json(200, {"snapshotId": SNAPSHOT,
                                    "verifiedObjectCount": 3})
        if self.path == "/api/hosted-receipt-page":
            if (action != "page" or request["reservationId"] != RESERVATION or
                    request["snapshotId"] != SNAPSHOT or
                    request["expectedCount"] != 3 or
                    request["expectedBytes"] != len(FIRST) + len(SECOND) + 5):
                return self._json(403, {"error": "access_denied"})
            if self.server.fail_next_page:
                self.server.fail_next_page = False
                return self._json(503, {"error": "temporarily_unavailable"})
            self.server.pages.append(request["objects"])
            return self._json(200, {"acceptedObjects": len(request["objects"])})
        if action == "reserve":
            if request["bytes"] != 1:
                return self._json(403, {"error": "access_denied"})
            return self._json(200, {"reservationId": RESERVATION,
                                    "expiresAt": EXPIRY,
                                    "baseSnapshotId": self.server.base_snapshot_id})
        if request.get("reservationId") != RESERVATION:
            return self._json(403, {"error": "access_denied"})
        if action == "renew":
            if self.server.fail_renew:
                return self._json(403, {"error": "access_denied"})
            return self._json(200, {"reservationId": RESERVATION,
                                    "expiresAt": EXPIRY})
        item = request["item"]
        key = item["key"]
        if (key not in self.server.expected or
                self.server.expected[key] != (item["bytes"], item["sha256"])):
            return self._json(403, {"error": "access_denied"})
        if action == "decide":
            if key in self.server.granted:
                return self._json(200, {"action": "head",
                                        "workerOrigin": self.server.origin,
                                        "grant": GRANT})
            return self._json(200, {"action": "put_required"})
        if action == "put":
            if self.server.fail_next_put:
                self.server.fail_next_put = False
                return self._json(503, {"error": "temporarily_unavailable"})
            self.server.granted.add(key)
            return self._json(200, {"workerOrigin": self.server.origin,
                                    "grant": GRANT})
        return self._json(400, {"error": "invalid_request"})

    def _worker_key(self):
        prefix = f"/v1/object/accounts/{ACCOUNT}/vaults/{VAULT}/"
        if (not self.path.startswith(prefix) or
                self.headers.get("Authorization") != "Bearer " + GRANT):
            return None
        key = self.path[len(prefix):]
        return key if key in self.server.granted else None

    def do_HEAD(self):
        key = self._worker_key()
        if key is None:
            status = 403
        elif key in self.server.conflicts:
            status = 409
        elif key not in self.server.objects:
            status = 404
        else:
            status = 200
        self.send_response(status)
        self.end_headers()

    def do_PUT(self):
        key = self._worker_key()
        if key is None:
            status = 403
        else:
            size, digest = self.server.expected[key]
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            if len(body) != size or hashlib.sha256(body).hexdigest() != digest:
                status = 409
            elif key in self.server.objects and self.server.objects[key] != body:
                status = 409
            else:
                status = 200 if key in self.server.objects else 201
                self.server.objects[key] = body
                if self.server.drop_next_put_response:
                    self.server.drop_next_put_response = False
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
        self.send_response(status)
        self.end_headers()


class HostedUploadClientTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.server.origin = f"http://127.0.0.1:{self.server.server_port}"
        self.server.objects = {}
        self.server.granted = set()
        self.server.conflicts = set()
        self.server.actions = []
        self.server.fail_next_put = False
        self.server.fail_renew = False
        self.server.fail_next_page = False
        self.server.fail_next_publish = False
        self.server.stale_next_publish = False
        self.server.stale_body = {"error": "stale_snapshot"}
        self.server.base_snapshot_id = None
        self.server.fail_next_verify = False
        self.server.fail_next_checkpoint_publish = False
        self.server.stale_next_checkpoint_publish = False
        self.server.verify_calls = 0
        self.server.verified_ready = False
        self.server.drop_next_put_response = False
        self.server.pages = []
        self.server.published = {}
        self.server.expected = {
            FIRST_KEY: (len(FIRST), hashlib.sha256(FIRST).hexdigest()),
            SECOND_KEY: (len(SECOND), hashlib.sha256(SECOND).hexdigest()),
        }
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = HostedUploadClient(
            self.server.origin, self.server.origin, TOKEN, ACCOUNT, VAULT,
            allow_loopback_http=True)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_abandon_requires_confirmation_and_exact_service_acknowledgement(self):
        with patch.object(self.client, "_post", return_value={"cleanupPending": True}) as post:
            with self.assertRaisesRegex(MigrationError, "explicit confirmation"):
                self.client.abandon(RESERVATION)
            post.assert_not_called()
            self.client.abandon(RESERVATION, apply=True)
            post.assert_called_once_with({"action": "abandon", "vaultId": VAULT,
                                          "reservationId": RESERVATION})
        with patch.object(self.client, "_post", return_value={"cleanupPending": False}):
            with self.assertRaisesRegex(MigrationError, "response is invalid"):
                self.client.abandon(RESERVATION, apply=True)

    def test_reservation_returns_captured_base_and_rejects_malformed_receipts(self):
        with self.assertRaises(MigrationError):
            self.client.reserve_with_base()
        self.assertEqual(self.client.reserve_with_base(apply=True),
                         (RESERVATION, None))
        self.server.base_snapshot_id = SNAPSHOT
        self.assertEqual(self.client.reserve_with_base(apply=True),
                         (RESERVATION, SNAPSHOT))
        with patch.object(self.client, "_post", return_value={
                "reservationId": RESERVATION, "expiresAt": EXPIRY}):
            with self.assertRaisesRegex(MigrationError, "response is invalid"):
                self.client.reserve_with_base(apply=True)

    def test_pre_recorded_reservation_id_is_sent_and_must_be_echoed(self):
        with patch.object(self.client, "_post", return_value={
                "reservationId": RESERVATION, "expiresAt": EXPIRY,
                "baseSnapshotId": None}) as post:
            self.assertEqual(self.client.reserve_with_base(
                reservation_id=RESERVATION, apply=True), (RESERVATION, None))
            post.assert_called_once_with({"action": "reserve", "vaultId": VAULT,
                                          "bytes": 1, "reservationId": RESERVATION})
            with self.assertRaisesRegex(MigrationError, "reservation changed"):
                self.client.reserve_with_base(reservation_id=SNAPSHOT,
                                              apply=True)

    def test_reservation_status_accepts_only_a_known_server_state(self):
        with patch.object(self.client, "_post", return_value={"state": "released"}) as post:
            self.assertEqual(self.client.reservation_status(RESERVATION), "released")
            post.assert_called_once_with({"action": "status", "vaultId": VAULT,
                                          "reservationId": RESERVATION})
        for bad in ({"state": "unknown"}, {"state": "released", "quotaFree": True}):
            with patch.object(self.client, "_post", return_value=bad):
                with self.assertRaisesRegex(MigrationError, "status response is invalid"):
                    self.client.reservation_status(RESERVATION)

    def test_published_reservation_receipt_names_the_exact_snapshot(self):
        receipt = {"state": "published", "snapshotId": SNAPSHOT,
                   "verifiedObjectCount": 3}
        with patch.object(self.client, "_post", return_value=receipt):
            self.assertEqual(self.client.reservation_receipt(RESERVATION), receipt)
            self.assertEqual(self.client.reservation_status(RESERVATION), "published")
        for bad in ({"state": "published"},
                    {"state": "published", "snapshotId": SNAPSHOT,
                     "verifiedObjectCount": 2},
                    {"state": "active", "snapshotId": SNAPSHOT,
                     "verifiedObjectCount": 3}):
            with patch.object(self.client, "_post", return_value=bad):
                with self.assertRaisesRegex(MigrationError, "status response is invalid"):
                    self.client.reservation_receipt(RESERVATION)

    def test_published_chunk_lookup_is_bounded_and_validates_exact_response(self):
        first, second = "a" * 64, "b" * 64
        facts = (75, hashlib.sha256(b"encrypted sample").hexdigest())
        self.server.published[first] = facts
        self.assertEqual(self.client.published_chunks([first, second]),
                         {first: facts})
        self.assertEqual(self.server.actions[-1], "lookup")
        for ids in ([], [first, first], [first.upper()], ["bad"],
                    [first] * 257):
            with self.assertRaisesRegex(MigrationError, "lookup is invalid"):
                self.client.published_chunks(ids)
        with patch.object(self.client, "_post", return_value={"objects": [
                {"id": second, "bytes": 1, "sha256": facts[1]}]}):
            with self.assertRaisesRegex(MigrationError, "response is invalid"):
                self.client.published_chunks([first])
        with patch.object(self.client, "_post", return_value={"objects": [
                {"id": first, "bytes": True, "sha256": facts[1]}]}):
            with self.assertRaisesRegex(MigrationError, "response is invalid"):
                self.client.published_chunks([first])

    def _stage(self, directory, store):
        root = Path(directory).resolve()
        inventory = RemoteInventory(SNAPSHOT, (
            VaultTransferFile("vault.json", FIRST_KEY, len(FIRST),
                              self.server.expected[FIRST_KEY][1]),
            VaultTransferFile("refs/" + SNAPSHOT + ".json", SECOND_KEY,
                              len(SECOND), self.server.expected[SECOND_KEY][1]),
        ), len(FIRST) + len(SECOND), True)
        with patch("codex_migrate.vault_remote_transfer.encrypted_snapshot_inventory",
                   return_value=inventory), patch(
                   "codex_migrate.vault_remote_transfer._vault_root", return_value=root):
            return stage_encrypted_snapshot(str(root), store)

    def test_interrupted_upload_reuses_verified_object_without_publishing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "refs").mkdir()
            (root / "vault.json").write_bytes(FIRST)
            (root / "refs" / (SNAPSHOT + ".json")).write_bytes(SECOND)
            reservation = self.client.reserve(apply=True)
            store = self.client.object_store(reservation, self.server.expected,
                                             apply=True)
            self.server.fail_next_put = False
            # Interrupt after the first encrypted object is stored.
            original_post = self.client._post

            def interrupted(claim):
                if claim["action"] == "put" and claim["item"]["key"] == SECOND_KEY:
                    raise MigrationError("Synthetic interruption")
                return original_post(claim)

            with patch.object(self.client, "_post", side_effect=interrupted):
                with self.assertRaises(MigrationError):
                    self._stage(directory, store)
            self.assertEqual(set(self.server.objects), {FIRST_KEY})
            self.assertEqual(self.client.renew(reservation, apply=True), reservation)
            resumed = self._stage(directory, store)
            repeated = self._stage(directory, store)
        self.assertEqual((resumed.uploaded_files, resumed.reused_files), (1, 1))
        self.assertEqual((repeated.uploaded_files, repeated.reused_files), (0, 2))
        self.assertEqual(self.server.objects, {FIRST_KEY: FIRST, SECOND_KEY: SECOND})
        self.assertNotIn("publish", self.server.actions)

    def test_denied_decision_and_conflict_are_not_absence(self):
        store = self.client.object_store(RESERVATION, self.server.expected, apply=True)
        with patch.object(self.client, "_post", side_effect=MigrationError("denied")):
            with self.assertRaises(MigrationError):
                store.checked_metadata(FIRST_KEY)
        self.server.granted.add(FIRST_KEY)
        self.server.conflicts.add(FIRST_KEY)
        with self.assertRaises(MigrationError):
            store.checked_metadata(FIRST_KEY)

    def test_lost_put_response_reconciles_by_verified_head(self):
        store = self.client.object_store(RESERVATION, self.server.expected, apply=True)
        self.assertIsNone(store.checked_metadata(FIRST_KEY))
        self.server.drop_next_put_response = True
        with self.assertRaises(MigrationError):
            store.put_if_absent(FIRST_KEY, io.BytesIO(FIRST), len(FIRST))
        self.assertEqual(self.server.objects[FIRST_KEY], FIRST)
        self.assertEqual(store.checked_metadata(FIRST_KEY),
                         self.server.expected[FIRST_KEY])
        # A retry need not issue another PUT grant for the already verified
        # immutable object, and neither attempt publishes a latest pointer.
        self.assertEqual(self.server.actions.count("put"), 1)
        self.assertNotIn("publish", self.server.actions)

    def test_long_transfer_renews_before_next_object_and_fails_closed(self):
        store = self.client.object_store(RESERVATION, self.server.expected, apply=True)
        store._last_renewal -= 25 * 60 + 1
        self.assertIsNone(store.checked_metadata(FIRST_KEY))
        self.assertEqual(self.server.actions[:2], ["renew", "decide"])
        self.server.fail_renew = True
        store._last_renewal -= 25 * 60 + 1
        with self.assertRaises(MigrationError):
            store.checked_metadata(SECOND_KEY)
        self.assertEqual(self.server.actions[-1], "renew")
        self.assertNotIn("put", self.server.actions)

    def test_receipt_pages_are_retryable_claims_not_publication(self):
        manifest_key = f"manifests/{SNAPSHOT}.cvmanifest"
        staged = StageResult(SNAPSHOT, 3, 0, len(FIRST) + len(SECOND) + 5,
                             (StagedObject(FIRST_KEY, len(FIRST),
                                           self.server.expected[FIRST_KEY][1]),
                              StagedObject(manifest_key, 5,
                                           hashlib.sha256(b"third").hexdigest()),
                              StagedObject(SECOND_KEY, len(SECOND),
                                           self.server.expected[SECOND_KEY][1])))
        with self.assertRaises(MigrationError):
            self.client.submit_pages(RESERVATION, staged)
        self.server.fail_next_page = True
        with self.assertRaises(MigrationError):
            self.client.submit_pages(RESERVATION, staged, apply=True)
        self.assertEqual(self.client.submit_pages(RESERVATION, staged, apply=True), 3)
        self.assertEqual([len(page) for page in self.server.pages], [3])
        self.assertNotIn("publish", self.server.actions)

    def test_bounded_hosted_stage_requires_exact_server_publication(self):
        manifest_key = f"manifests/{SNAPSHOT}.cvmanifest"
        objects = (
            StagedObject(FIRST_KEY, len(FIRST), self.server.expected[FIRST_KEY][1]),
            StagedObject(manifest_key, 5, hashlib.sha256(b"third").hexdigest()),
            StagedObject(SECOND_KEY, len(SECOND), self.server.expected[SECOND_KEY][1]),
        )
        staged = HostedSnapshotStage(SNAPSHOT, RESERVATION, objects, 2, 123, 0)
        self.assertIsNone(staged.upload_claim().uploaded_files)
        with self.assertRaisesRegex(MigrationError, "explicit confirmation"):
            self.client.publish_hosted_stage(RESERVATION, staged)
        with self.assertRaisesRegex(MigrationError, "another reservation"):
            self.client.publish_hosted_stage(
                RESERVATION,
                HostedSnapshotStage(SNAPSHOT, ACCOUNT, objects, 2, 123, 0),
                apply=True)
        self.server.fail_next_page = True
        with self.assertRaises(MigrationError):
            self.client.publish_hosted_stage(RESERVATION, staged, apply=True)
        self.assertNotIn("publish_checkpointed", self.server.actions)
        self.server.fail_next_checkpoint_publish = True
        with self.assertRaises(MigrationError):
            self.client.publish_hosted_stage(RESERVATION, staged, apply=True)
        self.assertEqual(self.client.publish_hosted_stage(
            RESERVATION, staged, apply=True), {
            "snapshotId": SNAPSHOT, "verifiedObjectCount": 3,
            "encryptedBytes": len(FIRST) + len(SECOND) + 5,
            "transcriptFiles": 2, "transcriptBytes": 123,
            "atRiskThreads": 0,
        })

    def test_publication_requires_apply_and_exact_server_receipt(self):
        with self.assertRaises(MigrationError):
            self.client.publish(RESERVATION, SNAPSHOT)
        with self.assertRaises(MigrationError):
            self.client.publish(RESERVATION, "wrong", apply=True)
        self.assertNotIn("publish", self.server.actions)
        self.server.fail_next_publish = True
        with self.assertRaises(MigrationError):
            self.client.publish(RESERVATION, SNAPSHOT, apply=True)
        self.assertEqual(self.client.publish(RESERVATION, SNAPSHOT, apply=True), 3)
        self.assertEqual(self.server.actions.count("publish"), 2)

    def test_stale_publication_is_not_an_ambiguous_service_failure(self):
        self.server.stale_next_publish = True
        with self.assertRaises(HostedPublicationStale):
            self.client.publish(RESERVATION, SNAPSHOT, apply=True)
        self.server.verified_ready = True
        self.server.stale_next_checkpoint_publish = True
        with self.assertRaises(HostedPublicationStale):
            self.client.publish_checkpointed(RESERVATION, SNAPSHOT, apply=True)
        self.server.stale_body = {"error": "other_conflict"}
        self.server.stale_next_checkpoint_publish = True
        with self.assertRaises(MigrationError) as failure:
            self.client.publish_checkpointed(RESERVATION, SNAPSHOT, apply=True)
        self.assertNotIsInstance(failure.exception, HostedPublicationStale)

    def test_verification_pages_resume_before_checkpointed_publication(self):
        with self.assertRaises(MigrationError):
            self.client.verify_next(RESERVATION, SNAPSHOT)
        with self.assertRaises(MigrationError):
            self.client.publish_checkpointed(RESERVATION, SNAPSHOT)
        self.server.fail_next_verify = True
        with self.assertRaises(MigrationError):
            self.client.verify_next(RESERVATION, SNAPSHOT, apply=True)
        with self.assertRaises(MigrationError):
            self.client.publish_checkpointed(RESERVATION, SNAPSHOT, apply=True)
        self.assertEqual(self.client.verify_next(RESERVATION, SNAPSHOT,
                                                 apply=True), (3, False))
        self.assertEqual(self.client.verify_next(RESERVATION, SNAPSHOT,
                                                 apply=True), (0, True))
        self.assertEqual(self.client.publish_checkpointed(
            RESERVATION, SNAPSHOT, apply=True), 3)
        self.assertEqual(self.server.actions.count("publish_checkpointed"), 2)

    def test_verification_loop_retries_ambiguous_final_response_safely(self):
        with self.assertRaises(MigrationError):
            self.client.verify_and_publish(RESERVATION, SNAPSHOT)
        self.server.fail_next_checkpoint_publish = True
        with self.assertRaises(MigrationError):
            self.client.verify_and_publish(RESERVATION, SNAPSHOT, apply=True)
        self.assertTrue(self.server.verified_ready)
        self.assertEqual(self.client.verify_and_publish(
            RESERVATION, SNAPSHOT, apply=True), 3)
        self.assertEqual(self.server.actions.count("publish_checkpointed"), 2)

    def test_full_snapshot_requires_publication_and_retries_without_reupload(self):
        manifest_key = f"manifests/{SNAPSHOT}.cvmanifest"
        manifest = b"third"
        self.server.expected[manifest_key] = (len(manifest),
                                              hashlib.sha256(manifest).hexdigest())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "manifests").mkdir()
            (root / "refs").mkdir()
            (root / "vault.json").write_bytes(FIRST)
            (root / "manifests" / (SNAPSHOT + ".cvmanifest")).write_bytes(manifest)
            (root / "refs" / (SNAPSHOT + ".json")).write_bytes(SECOND)
            inventory = RemoteInventory(SNAPSHOT, (
                VaultTransferFile("vault.json", FIRST_KEY, len(FIRST),
                                  self.server.expected[FIRST_KEY][1]),
                VaultTransferFile("manifests/" + SNAPSHOT + ".cvmanifest",
                                  manifest_key, len(manifest),
                                  self.server.expected[manifest_key][1]),
                VaultTransferFile("refs/" + SNAPSHOT + ".json", SECOND_KEY,
                                  len(SECOND), self.server.expected[SECOND_KEY][1]),
            ), len(FIRST) + len(manifest) + len(SECOND), True)
            with patch("codex_migrate.vault_hosted_upload_client.encrypted_snapshot_inventory",
                       return_value=inventory), patch(
                       "codex_migrate.vault_remote_transfer.encrypted_snapshot_inventory",
                       return_value=inventory), patch(
                       "codex_migrate.vault_remote_transfer._vault_root", return_value=root):
                with self.assertRaisesRegex(MigrationError, "explicit confirmation"):
                    self.client.back_up_snapshot(str(root), reservation_id=RESERVATION)
                self.assertEqual(self.server.actions, [])
                self.assertEqual(self.client.reserve(apply=True), RESERVATION)
                self.server.fail_next_page = True
                with self.assertRaises(MigrationError):
                    self.client.back_up_snapshot(str(root), reservation_id=RESERVATION,
                                                 apply=True)
                self.assertNotIn("publish_checkpointed", self.server.actions)
                self.assertEqual(set(self.server.objects), set(self.server.expected))
                self.server.fail_next_checkpoint_publish = True
                with self.assertRaises(MigrationError):
                    self.client.back_up_snapshot(str(root),
                                                 reservation_id=RESERVATION,
                                                 apply=True)
                self.assertEqual(self.client.back_up_snapshot(
                    str(root), reservation_id=RESERVATION, apply=True), {
                    "snapshotId": SNAPSHOT, "verifiedObjectCount": 3,
                    "uploadedFiles": 0, "reusedFiles": 3,
                    "encryptedBytes": inventory.transfer_bytes,
                })
        self.assertEqual(self.server.actions.count("put"), 3)
        self.assertEqual(self.server.actions.count("reserve"), 1)
        self.assertEqual(self.server.actions.count("publish_checkpointed"), 2)

    def test_journaled_run_retries_after_page_failure_without_new_reservation(self):
        manifest_key = f"manifests/{SNAPSHOT}.cvmanifest"
        manifest = b"third"
        self.server.expected[manifest_key] = (len(manifest),
                                              hashlib.sha256(manifest).hexdigest())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            home = root / "home"
            vault = root / "vault"
            home.mkdir()
            (vault / "manifests").mkdir(parents=True)
            (vault / "refs").mkdir()
            (vault / "vault.json").write_bytes(FIRST)
            (vault / "manifests" / (SNAPSHOT + ".cvmanifest")).write_bytes(manifest)
            (vault / "refs" / (SNAPSHOT + ".json")).write_bytes(SECOND)
            inventory = RemoteInventory(SNAPSHOT, (
                VaultTransferFile("vault.json", FIRST_KEY, len(FIRST),
                                  self.server.expected[FIRST_KEY][1]),
                VaultTransferFile("manifests/" + SNAPSHOT + ".cvmanifest",
                                  manifest_key, len(manifest),
                                  self.server.expected[manifest_key][1]),
                VaultTransferFile("refs/" + SNAPSHOT + ".json", SECOND_KEY,
                                  len(SECOND), self.server.expected[SECOND_KEY][1]),
            ), len(FIRST) + len(manifest) + len(SECOND), True)
            with patch("codex_migrate.vault_hosted_backup_run.encrypted_snapshot_inventory",
                       return_value=inventory), patch(
                       "codex_migrate.vault_hosted_upload_client.encrypted_snapshot_inventory",
                       return_value=inventory), patch(
                       "codex_migrate.vault_remote_transfer.encrypted_snapshot_inventory",
                       return_value=inventory), patch(
                       "codex_migrate.vault_remote_transfer._vault_root", return_value=vault):
                self.server.fail_next_page = True
                run = HostedBackupRun(self.client, str(home))
                with self.assertRaises(MigrationError):
                    run.back_up_snapshot(str(vault), apply=True)
                self.assertEqual(run.pending(), {
                    "snapshotId": SNAPSHOT, "reservationId": RESERVATION})
                relaunched = HostedBackupRun(self.client, str(home))
                receipt = relaunched.back_up_snapshot(str(vault), apply=True)
                self.assertEqual(receipt["verifiedObjectCount"], 3)
                self.assertEqual(receipt["uploadedFiles"], 0)
                self.assertIsNone(relaunched.pending())
        self.assertEqual(self.server.actions.count("reserve"), 1)
        self.assertEqual(self.server.actions.count("put"), 3)

    def test_mutation_requires_apply_and_server_origin_is_pinned(self):
        with self.assertRaises(MigrationError):
            self.client.reserve()
        with self.assertRaises(MigrationError):
            self.client.renew(RESERVATION)
        with self.assertRaises(MigrationError):
            self.client.object_store(RESERVATION, self.server.expected)
        with self.assertRaises(MigrationError):
            HostedUploadClient("http://example.com", self.server.origin, TOKEN,
                               ACCOUNT, VAULT, allow_loopback_http=True)
        with self.assertRaises(MigrationError):
            HostedUploadClient(self.server.origin, "http://example.com", TOKEN,
                               ACCOUNT, VAULT, allow_loopback_http=True)
        store = self.client.object_store(RESERVATION, self.server.expected, apply=True)
        self.server.granted.add(FIRST_KEY)
        self.server.origin = "https://wrong.example"
        with self.assertRaises(MigrationError):
            store.checked_metadata(FIRST_KEY)


if __name__ == "__main__":
    unittest.main()
