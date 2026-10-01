import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from codex_migrate.errors import MigrationError
from codex_migrate.vault_http_store import CapabilityHttpStore
from codex_migrate.vault_remote_inventory import RemoteInventory, VaultTransferFile
from codex_migrate.vault_remote_transfer import StageResult, StagedObject, stage_encrypted_snapshot


ACCOUNT = "11111111-1111-4111-8111-111111111111"
VAULT = "22222222-2222-4222-8222-222222222222"
SNAPSHOT = "33333333-3333-4333-8333-333333333333"
KEY = f"accounts/{ACCOUNT}/vaults/{VAULT}/metadata/{SNAPSHOT}.json"
RELATIVE_KEY = f"metadata/{SNAPSHOT}.json"
BODY = b"encrypted-test-fixture"
DIGEST = hashlib.sha256(BODY).hexdigest()


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _check(self):
        return (self.path == "/v1/object/" + KEY
                and self.headers.get("Authorization") == "Bearer synthetic.valid")

    def do_HEAD(self):
        if not self._check():
            self.send_response(403)
        elif self.server.conflict:
            self.send_response(409)
        elif KEY not in self.server.objects:
            self.send_response(404)
        else:
            self.send_response(200)
        self.end_headers()

    def do_PUT(self):
        if not self._check():
            self.send_response(403)
        elif self.headers.get("Content-Length") != str(len(BODY)):
            self.send_response(400)
        else:
            value = self.rfile.read(len(BODY))
            if value != BODY or KEY in self.server.objects:
                self.send_response(409)
            else:
                self.server.objects[KEY] = value
                self.send_response(201)
        self.end_headers()

    def do_GET(self):
        self.server.paths.append(self.path)
        if self.server.redirect:
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/stolen")
        elif not self._check():
            self.send_response(403)
        elif KEY not in self.server.objects:
            self.send_response(409)
        else:
            self.send_response(200)
            self.send_header("Content-Length", str(len(BODY)))
        self.end_headers()
        if KEY in self.server.objects and not self.server.redirect:
            self.wfile.write(self.server.objects[KEY])


class CapabilityHttpStoreTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.server.objects = {}
        self.server.conflict = False
        self.server.redirect = False
        self.server.paths = []
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.grants = []

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def store(self):
        def grant(method, key, size, digest):
            self.grants.append((method, key, size, digest))
            return "synthetic.valid"
        return CapabilityHttpStore(
            f"http://127.0.0.1:{self.server.server_port}", ACCOUNT, VAULT,
            {RELATIVE_KEY: (len(BODY), DIGEST)}, grant, allow_loopback_http=True)

    def test_upload_check_reuse_and_streamed_read(self):
        store = self.store()
        self.assertIsNone(store.checked_metadata(RELATIVE_KEY))
        source = io.BytesIO(BODY)
        store.put_if_absent(RELATIVE_KEY, source, len(BODY))
        self.assertEqual(source.tell(), len(BODY))
        self.assertEqual(store.checked_metadata(RELATIVE_KEY), (len(BODY), DIGEST))
        with store.open_read(RELATIVE_KEY) as stream:
            self.assertEqual(stream.read(), BODY)
        self.assertEqual([grant[0] for grant in self.grants],
                         ["HEAD", "PUT", "HEAD", "GET"])
        self.assertTrue(all(grant[1:] == (KEY, len(BODY), DIGEST)
                            for grant in self.grants))

    def test_snapshot_stage_uses_relative_keys_and_reuses_verified_remote_object(self):
        store = self.store()
        item = VaultTransferFile("vault.json", RELATIVE_KEY, len(BODY), DIGEST)
        inventory = RemoteInventory(SNAPSHOT, (item,), len(BODY), True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "vault.json").write_bytes(BODY)
            with patch("codex_migrate.vault_remote_transfer.encrypted_snapshot_inventory",
                       return_value=inventory), patch(
                       "codex_migrate.vault_remote_transfer._vault_root", return_value=root):
                first = stage_encrypted_snapshot(str(root), store)
                repeated = stage_encrypted_snapshot(str(root), store)
        self.assertEqual((first.uploaded_files, first.reused_files), (1, 0))
        self.assertEqual((repeated.uploaded_files, repeated.reused_files), (0, 1))
        self.assertEqual(self.server.objects, {KEY: BODY})

    def test_conflict_and_redirect_fail_closed(self):
        store = self.store()
        self.server.conflict = True
        with self.assertRaises(MigrationError):
            store.checked_metadata(RELATIVE_KEY)
        self.server.conflict = False
        self.server.redirect = True
        with self.assertRaises(MigrationError):
            store.open_read(RELATIVE_KEY)
        self.assertEqual(self.server.paths, ["/v1/object/" + KEY])

    def test_wrong_source_or_scope_cannot_request_grant(self):
        store = self.store()
        with self.assertRaises(MigrationError):
            store.put_if_absent(RELATIVE_KEY, io.BytesIO(b"wrong"), len(BODY))
        with self.assertRaises(MigrationError):
            store.open_read("../" + RELATIVE_KEY)
        self.assertFalse(self.grants)

    def test_rejects_insecure_or_ambiguous_origin(self):
        for origin in ("http://example.com", "https://x.example/path",
                       "https://user:pass@x.example", "https://x.example?q=1"):
            with self.subTest(origin=origin), self.assertRaises(MigrationError):
                CapabilityHttpStore(origin, ACCOUNT, VAULT,
                                    {RELATIVE_KEY: (len(BODY), DIGEST)},
                                    lambda *args: "synthetic.valid")

    def test_stage_result_pages_never_exceed_server_limit(self):
        objects = tuple(StagedObject(RELATIVE_KEY, len(BODY), DIGEST)
                        for _ in range(1025))
        result = StageResult(SNAPSHOT, 1025, 0, 1025 * len(BODY), objects)
        pages = list(result.object_pages())
        self.assertEqual([len(page) for page in pages], [512, 512, 1])
        self.assertEqual(pages[0][0],
                         {"key": RELATIVE_KEY, "bytes": len(BODY), "sha256": DIGEST})


if __name__ == "__main__":
    unittest.main()
