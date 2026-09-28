import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile
import threading
import unittest

from codex_migrate.errors import MigrationError
from codex_migrate.vault_hosted_recovery_client import HostedRecoveryClient
from codex_migrate.vault_backup import backup
from codex_migrate.vault_recovery import import_recovery_key, restore_snapshot
from codex_migrate.vault_remote_recovery import download_encrypted_snapshot
from codex_migrate.vault_remote_transfer import stage_encrypted_snapshot
from tests.portable_vault_roundtrip import delete_test_key


ACCOUNT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
VAULT = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
SNAPSHOT = "11111111-1111-4111-8111-111111111111"
TOKEN = "hv1_" + "a" * 43
PREFIX = f"accounts/{ACCOUNT}/vaults/{VAULT}/"


def inventory(chunk_count=0):
    values = {f"metadata/{SNAPSHOT}.json": b"metadata",
              f"manifests/{SNAPSHOT}.cvmanifest": b"manifest",
              f"refs/{SNAPSHOT}.json": b"reference"}
    for index in range(chunk_count):
        digest = format(index, "064x")
        values[f"objects/{digest[:2]}/{digest[2:]}.cvchunk"] = b"chunk" + str(index).encode()
    return values


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def _reply(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/api/hosted-recovery" or self.headers.get(
                "Authorization") != "Bearer " + TOKEN:
            return self._reply(403, {"error": "access_denied"})
        claim = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append(claim)
        rows = [{"key": key, "bytes": len(value),
                 "sha256": hashlib.sha256(value).hexdigest()}
                for key, value in sorted(self.server.objects.items())]
        total = sum(item["bytes"] for item in rows)
        if claim["action"] == "latest":
            snapshot_id = (self.server.latest_sequence.pop(0)
                           if self.server.latest_sequence else self.server.snapshot_id)
            return self._reply(200, {"accountId": ACCOUNT,
                "workerOrigin": self.server.origin,
                "latest": None if snapshot_id is None else
                {"snapshotId": snapshot_id,
                 "totalObjects": len(rows), "totalBytes": total}})
        if claim["action"] == "objects":
            after = claim.get("afterKey", "")
            page = [item for item in rows if PREFIX + item["key"] > after][:257]
            more = len(page) > 256
            page = page[:256]
            result = {"snapshotId": self.server.snapshot_id, "totalObjects": len(rows),
                      "totalBytes": total, "objects": page,
                      "nextCursor": PREFIX + page[-1]["key"] if more else None}
            if self.server.mutate_page:
                self.server.mutate_page(result)
            return self._reply(200, result)
        if claim["action"] == "manifest":
            snapshot_id = (self.server.latest_sequence.pop(0)
                           if self.server.latest_sequence else self.server.snapshot_id)
            if claim["snapshotId"] != snapshot_id:
                return self._reply(503, {"error": "unavailable"})
            key = f"manifests/{snapshot_id}.cvmanifest"
            value = self.server.objects.get(key)
            if value is None:
                return self._reply(503, {"error": "unavailable"})
            result = {"accountId": ACCOUNT, "workerOrigin": self.server.origin,
                      "snapshotId": snapshot_id, "bytes": len(value),
                      "sha256": hashlib.sha256(value).hexdigest(),
                      "grant": "synthetic.valid"}
            if self.server.mutate_manifest:
                self.server.mutate_manifest(result)
            return self._reply(200, result)
        if claim["action"] == "get":
            return self._reply(200, {"workerOrigin": self.server.origin,
                                     "grant": "synthetic.valid"})
        return self._reply(400, {"error": "invalid_request"})

    def do_GET(self):
        key = self.path.removeprefix("/v1/object/")
        self.server.get_requests.append(key)
        if (not self.path.startswith("/v1/object/") or
                self.headers.get("Authorization") != "Bearer synthetic.valid" or
                not key.startswith(PREFIX) or key[len(PREFIX):] not in self.server.objects):
            self.send_response(403)
            self.end_headers()
            return
        body = self.server.objects[key[len(PREFIX):]]
        if self.server.mutate_get:
            body = self.server.mutate_get(key[len(PREFIX):], body)
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class HostedRecoveryClientTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.server.origin = f"http://127.0.0.1:{self.server.server_port}"
        self.server.snapshot_id = SNAPSHOT
        self.server.objects = inventory()
        self.server.requests = []
        self.server.get_requests = []
        self.server.mutate_page = None
        self.server.mutate_manifest = None
        self.server.mutate_get = None
        self.server.latest_sequence = []
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def client(self):
        return HostedRecoveryClient(self.server.origin, TOKEN, VAULT,
                                    allow_loopback_http=True)

    def test_prepares_validated_receipt_and_exact_get_grant(self):
        receipt, store = self.client().prepare(max_bytes=1_000_000)
        self.assertEqual(receipt["snapshot_id"], SNAPSHOT)
        self.assertEqual([item["key"] for item in receipt["objects"]],
                         [f"metadata/{SNAPSHOT}.json",
                          f"manifests/{SNAPSHOT}.cvmanifest", f"refs/{SNAPSHOT}.json"])
        with store.open_read(f"metadata/{SNAPSHOT}.json") as stream:
            self.assertEqual(stream.read(), b"metadata")
        self.assertEqual([item["action"] for item in self.server.requests],
                         ["latest", "objects", "get"])

    def test_large_inventory_pages_and_reorders_only_after_complete_validation(self):
        self.server.objects = inventory(254)
        receipt, _store = self.client().prepare(max_bytes=1_000_000)
        self.assertEqual(len(receipt["objects"]), 257)
        self.assertTrue(receipt["objects"][1]["key"].startswith("objects/"))
        self.assertEqual([item["action"] for item in self.server.requests],
                         ["latest", "objects", "objects"])
        self.assertEqual(self.server.requests[-1]["afterKey"],
                         PREFIX + sorted(self.server.objects)[255])

    def test_incomplete_or_changed_pages_fail_before_any_get(self):
        for mutate in [
            lambda page: page["objects"].pop(),
            lambda page: page["objects"][0].update(sha256="bad"),
            lambda page: page.update(nextCursor=PREFIX + "objects/aa/" + "a" * 62 + ".cvchunk"),
            lambda page: page.update(totalBytes=page["totalBytes"] + 1),
        ]:
            with self.subTest(mutate=mutate):
                self.server.requests.clear()
                self.server.mutate_page = mutate
                with self.assertRaises(MigrationError):
                    self.client().prepare(max_bytes=1_000_000)
                self.assertNotIn("get", [item["action"] for item in self.server.requests])

    def test_refuses_insecure_service_and_bad_bearer(self):
        with self.assertRaises(MigrationError):
            HostedRecoveryClient(self.server.origin, TOKEN, VAULT)
        with self.assertRaises(MigrationError):
            HostedRecoveryClient("https://user:pass@example.com", TOKEN, VAULT)
        with self.assertRaises(MigrationError):
            HostedRecoveryClient(self.server.origin, "bad", VAULT,
                                 allow_loopback_http=True)

    def test_authenticated_empty_vault_is_not_a_catalog_error(self):
        self.server.snapshot_id = None
        snapshot_id, files = self.client().prior_catalog(
            key_id="unused", crypto_helper="/missing-helper", max_bytes=1_000_000,
            expected_snapshot_id=None)
        self.assertIsNone(snapshot_id)
        self.assertEqual(files, [])
        self.assertEqual([item["action"] for item in self.server.requests], ["latest"])

    def test_reserved_base_must_match_latest_before_any_manifest_download(self):
        other = "22222222-2222-4222-8222-222222222222"
        with self.assertRaisesRegex(MigrationError, "changed after reservation"):
            self.client().prior_catalog(key_id="unused",
                crypto_helper="/missing-helper", max_bytes=1_000_000,
                expected_snapshot_id=None)
        with self.assertRaisesRegex(MigrationError, "changed after reservation"):
            self.client().prior_catalog(key_id="unused",
                crypto_helper="/missing-helper", max_bytes=1_000_000,
                expected_snapshot_id=other)
        self.assertEqual([item["action"] for item in self.server.requests],
                         ["latest", "latest"])

    def test_reserved_account_must_match_before_any_manifest_download(self):
        other_account = "22222222-2222-4222-8222-222222222222"
        with self.assertRaisesRegex(MigrationError, "account changed"):
            self.client().prior_catalog(
                key_id="unused", crypto_helper="/missing-helper",
                max_bytes=1_000_000, expected_snapshot_id=SNAPSHOT,
                expected_account_id=other_account)
        self.assertEqual([item["action"] for item in self.server.requests],
                         ["latest"])

    def test_latest_change_refuses_prior_manifest_grant(self):
        self.server.latest_sequence = [SNAPSHOT, "22222222-2222-4222-8222-222222222222"]
        with tempfile.TemporaryDirectory() as temporary:
            helper = Path(temporary) / "helper"
            helper.write_text("#!/bin/sh\nexit 0\n")
            helper.chmod(0o700)
            with self.assertRaises(MigrationError):
                self.client().prior_catalog(key_id=SNAPSHOT,
                    crypto_helper=str(helper), max_bytes=1_000_000)
        self.assertEqual([item["action"] for item in self.server.requests],
                         ["latest", "manifest"])
        self.assertEqual(self.server.get_requests, [])

    def test_prior_manifest_grant_refuses_changed_authority_and_size(self):
        with tempfile.TemporaryDirectory() as temporary:
            helper = Path(temporary) / "helper"
            helper.write_text("#!/bin/sh\nexit 0\n")
            helper.chmod(0o700)
            for mutate in [
                lambda manifest: manifest.update(accountId="cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
                lambda manifest: manifest.update(workerOrigin="https://other.example"),
                lambda manifest: manifest.update(snapshotId="22222222-2222-4222-8222-222222222222"),
                lambda manifest: manifest.update(sha256="bad"),
                lambda manifest: manifest.update(bytes=100_000_001),
                lambda manifest: manifest.update(grant="bad"),
            ]:
                with self.subTest(mutate=mutate):
                    self.server.requests.clear()
                    self.server.get_requests.clear()
                    self.server.mutate_manifest = mutate
                    with self.assertRaises(MigrationError):
                        self.client().prior_catalog(key_id=SNAPSHOT,
                            crypto_helper=str(helper), max_bytes=200_000_000)
                    self.assertEqual([request["action"] for request in self.server.requests],
                                     ["latest", "manifest"])
                    self.assertEqual(self.server.get_requests, [])
            self.server.mutate_manifest = None

    @unittest.skipUnless(platform.system() == "Darwin", "CryptoKit helper requires macOS")
    def test_synthetic_encrypted_backup_recovers_through_service_pages(self):
        class MemoryStore:
            def __init__(self):
                self.objects = {}

            def open_read(self, key):
                import io
                value = self.objects.get(key)
                return io.BytesIO(value) if value is not None else None

            def put_if_absent(self, key, source, length):
                if key in self.objects:
                    raise AssertionError("synthetic object overwrite")
                self.objects[key] = source.read(length)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            helper = root / "CodexVaultCrypto"
            subprocess.run(["xcrun", "swiftc", "-parse-as-library", "-O", "-D",
                "CODEX_VAULT_TEST_LEGACY_KEYCHAIN", "-target",
                platform.machine() + "-apple-macos13.0",
                "desktop/CodexVaultCrypto.swift", "-o", str(helper)],
                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=120)
            source = root / "source"
            transcript = source / ".codex/sessions/2026/09/27/fixture.jsonl"
            transcript.parent.mkdir(parents=True)
            content = b'{"type":"response_item","payload":{"content":"recovery fixture"}}\n'
            transcript.write_bytes(content)
            vault = root / "vault"
            saved = backup(str(source), str(vault), crypto_helper=str(helper))
            key_id = saved.key_id
            try:
                staged_store = MemoryStore()
                staged = stage_encrypted_snapshot(str(vault), staged_store,
                                                  crypto_helper=str(helper))
                self.server.objects = staged_store.objects
                self.server.snapshot_id = staged.snapshot_id
                receipt, read_store = self.client().prepare(max_bytes=5_000_000)
                self.assertEqual(receipt["snapshot_id"], staged.snapshot_id)
                manifest_key = f"manifests/{staged.snapshot_id}.cvmanifest"
                manifest_bytes = len(staged_store.objects[manifest_key])
                self.assertGreater(sum(map(len, staged_store.objects.values())),
                                   manifest_bytes)
                # Full restore remains bounded by total snapshot bytes, while
                # an incremental backup needs only the prior sealed manifest.
                with self.assertRaisesRegex(MigrationError, "exceeds its limit"):
                    self.client().prepare(max_bytes=manifest_bytes)
                self.server.requests.clear()
                with self.assertRaisesRegex(MigrationError, "prior hosted manifest exceeds"):
                    self.client().prior_catalog(key_id=key_id,
                        crypto_helper=str(helper), max_bytes=manifest_bytes - 1)
                self.assertEqual([request["action"] for request in self.server.requests],
                                 ["latest", "manifest"])
                self.assertEqual(self.server.get_requests, [])
                self.server.requests.clear()
                self.server.get_requests.clear()
                prior_id, files = self.client().prior_catalog(
                    key_id=key_id, crypto_helper=str(helper), max_bytes=manifest_bytes)
                self.assertEqual(prior_id, staged.snapshot_id)
                self.assertEqual(len(files), 1)
                self.assertEqual(files[0]["path"], "2026/09/27/fixture.jsonl")
                self.assertEqual([request["action"] for request in self.server.requests],
                                 ["latest", "manifest"])
                self.assertEqual(self.server.get_requests,
                                 [PREFIX + f"manifests/{staged.snapshot_id}.cvmanifest"])
                self.server.mutate_get = lambda key, body: (
                    bytes([body[0] ^ 1]) + body[1:]
                    if key.startswith("manifests/") else body)
                with self.assertRaises(MigrationError):
                    self.client().prior_catalog(key_id=key_id,
                        crypto_helper=str(helper), max_bytes=5_000_000)
                self.server.mutate_get = None
                empty_home = root / "empty-home"
                empty_home.mkdir(mode=0o700)
                recovered = root / "recovered-vault"
                delete_test_key(helper, key_id)
                key_id = None
                with self.assertRaises(MigrationError):
                    download_encrypted_snapshot(str(empty_home), str(recovered),
                                                read_store, receipt, max_bytes=5_000_000,
                                                crypto_helper=str(helper))
                key_id = import_recovery_key(str(recovered), saved.recovery_key,
                                             crypto_helper=str(helper))
                result = download_encrypted_snapshot(
                    str(empty_home), str(recovered), read_store, receipt,
                    max_bytes=5_000_000, crypto_helper=str(helper))
                restored = root / "restored"
                restore_snapshot(str(empty_home), str(recovered), str(restored),
                                 crypto_helper=str(helper))
                self.assertEqual(result.snapshot_id, saved.snapshot_id)
                self.assertEqual((restored / "sessions/2026/09/27/fixture.jsonl").read_bytes(),
                                 content)
            finally:
                if key_id is not None:
                    delete_test_key(helper, key_id)


if __name__ == "__main__":
    unittest.main()
