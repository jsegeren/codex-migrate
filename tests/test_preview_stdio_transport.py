"""Pipe safety proofs only; not cloud recovery or VM acceptance evidence."""
import base64
from email.message import Message
import json
import os
from pathlib import Path
import socket
import sys
import threading
import unittest
from unittest.mock import patch
from urllib.error import URLError
from urllib.request import Request

OPS = str(Path(__file__).parents[1] / "ops")
sys.path.insert(0, OPS)
try:
    import preview_stdio_transport as RELAY
finally:
    sys.path.remove(OPS)
ORIGIN = "https://codex-migrate-abc-joshuas-projects-d3a5c48d.vercel.app"


class RelayTests(unittest.TestCase):
    def setUp(self):
        self.a, self.b = socket.socketpair()
        self.addCleanup(self.a.close)
        self.addCleanup(self.b.close)
        self.ar, self.aw = self.a.makefile("rb"), self.a.makefile("wb")
        self.br, self.bw = self.b.makefile("rb"), self.b.makefile("wb")
        for stream in (self.ar, self.aw, self.br, self.bw):
            self.addCleanup(stream.close)
        self.frames = RELAY.Frames(self.br, self.bw)
        self.client = RELAY.StdioRecoveryOpener(ORIGIN, self.ar, self.aw)

    def request(self, path="/api/hosted-recovery", data=b"{}", headers=None):
        return Request(ORIGIN + path, data=data,
                       headers=headers or {"Authorization": "Bearer synthetic-only"}, method="POST")

    def claim(self):
        return {"type": "request", "id": 1, "path": "/api/hosted-recovery",
                "headers": {"Authorization": "Bearer synthetic-only"},
                "body": base64.b64encode(b"{}").decode(), "timeout": 1}

    def opener(self):
        headers = Message()
        headers["Content-Type"] = "application/json"
        headers["Set-Cookie"] = "do-not-copy"
        class Fake:
            origin = ORIGIN
            def open(_, request, timeout):
                self.assertEqual(request.full_url, ORIGIN + "/api/hosted-recovery")
                self.assertEqual(request.get_header("Authorization"), "Bearer synthetic-only")
                return RELAY.Response(b'{"scoped":true}', 403, headers)
        return Fake()

    def test_roundtrip_preserves_real_status_and_safe_headers(self):
        failure = []
        def server():
            try:
                value = self.frames.read(2)
                self.frames.write(RELAY.relay_request(self.opener(), value, 1), 2)
            except Exception as error:
                failure.append(error)
        thread = threading.Thread(target=server)
        thread.start()
        with self.client.open(self.request(), timeout=2) as response:
            self.assertEqual(response.status, 403)
            self.assertEqual(json.loads(response.read()), {"scoped": True})
            self.assertIsNone(response.headers.get("Set-Cookie"))
        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(failure, [])

    def test_host_refuses_route_destination_sequence_and_unexpected_fields(self):
        for changes in ({"path": "/api/hosted-upload"}, {"path": "/api/purchase"},
                        {"path": "https://evil.example"}, {"path": "/api/hosted-recovery?x=y"},
                        {"id": True}, {"id": 2}, {"timeout": True}, {"timeout": 121},
                        {"extra": "sensitive"}, {"headers": {"Cookie": "private"}},
                        {"headers": {"Authorization": "x\r\nY:evil"}},
                        {"body": "invalid%"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                RELAY.relay_request(self.opener(), {**self.claim(), **changes}, 1)

    def test_client_rejects_foreign_origin_and_upload_before_writing(self):
        for request in (self.request("/api/hosted-upload"), self.request("/api/hosted-recovery/"),
                        Request("https://evil.example/api/hosted-recovery", data=b"{}"),
                        self.request(data=b"x" * (RELAY.LIMIT + 1))):
            with self.assertRaises(URLError):
                self.client.open(request, timeout=1)
        self.b.settimeout(.05)
        with self.assertRaises(socket.timeout):
            self.b.recv(1)

    def test_client_refuses_wrong_reply_and_redacts_provider_contents(self):
        response = {"type": "response", "id": 1, "status": 200,
                    "headers": {}, "body": base64.b64encode(b"{}").decode()}
        for changes in ({"id": 2}, {"id": True}, {"status": True}, {"status": 600},
                        {"headers": {"Set-Cookie": "secret"}}, {"body": "secret%"},
                        {"extra": "secret"}):
            self.client.sequence = 0
            self.frames.write({**response, **changes}, 1)
            with self.assertRaises(URLError) as caught:
                self.client.open(self.request(), timeout=1)
            self.assertNotIn("secret", str(caught.exception))
            self.frames.read(1)

    def test_partial_frame_timeout_is_bounded(self):
        os.write(self.a.fileno(), b'{"secret":')
        with self.assertRaises(ValueError):
            self.frames.read(.02)

    def test_oversized_frame_refused(self):
        with patch.object(RELAY, "FRAME_LIMIT", 64):
            os.write(self.a.fileno(), b"x" * 65)
            with self.assertRaises(ValueError):
                self.frames.read(.1)

    def test_multiple_frames_buffered_without_reordering(self):
        os.write(self.a.fileno(), b'{"id":1}\n{"id":2}\n')
        self.assertEqual(self.frames.read(1), {"id": 1})
        self.assertEqual(self.frames.read(1), {"id": 2})

    def test_duplicate_json_fields_refused(self):
        os.write(self.a.fileno(), b'{"id":1,"id":2}\n')
        with self.assertRaises(ValueError):
            self.frames.read(1)

    def test_duplicate_case_header_and_control_injection_refused(self):
        for headers in ({"Authorization": "x", "authorization": "y"},
                        {"Authorization": "x\x00"}, {"Content-Type": "x\n"}):
            with self.assertRaises(ValueError):
                RELAY.checked_headers(headers, RELAY.HEADERS)

    def test_context_does_not_change_upload_or_r2_and_restores_on_failure(self):
        from codex_migrate import vault_hosted_upload_client as upload, vault_http_store as store
        old = [m.build_opener for m in (RELAY.enrollment, RELAY.recovery, upload, store)]
        with patch.object(RELAY.sys, "stdin", type("Input", (), {"buffer": self.ar})()), \
                patch.object(RELAY.sys, "stdout", type("Output", (), {"buffer": self.aw})()):
            with self.assertRaises(RuntimeError):
                with RELAY.stdio_recovery(ORIGIN):
                    self.assertIs(RELAY.enrollment.build_opener(), RELAY.recovery.build_opener())
                    self.assertIs(upload.build_opener, old[2])
                    self.assertIs(store.build_opener, old[3])
                    raise RuntimeError("test")
        self.assertEqual([m.build_opener for m in (RELAY.enrollment, RELAY.recovery, upload, store)], old)

    def test_owned_child_end_to_end_no_credentials_in_command(self):
        child = """import sys,json
claim={"type":"request","id":1,"path":"/api/hosted-recovery","headers":{"Authorization":"Bearer synthetic-only"},"body":"e30=","timeout":1}
print(json.dumps(claim),flush=True)
response=json.loads(sys.stdin.readline())
passed=response['status']==403
print(json.dumps({'type':'result','passed':passed,'action':'recover'}),flush=True)
sys.exit(0 if passed else 1)
"""
        # The child code contains only a synthetic fixture, never a real bearer.
        with patch.object(RELAY, "PreviewOpener", return_value=self.opener()):
            result = RELAY.relay_process([sys.executable, "-c", child], ORIGIN, OPS, max_seconds=5)
        self.assertEqual(result, {"passed": True, "action": "recover",
                                  "relayed_api_requests": 1, "complete_release_acceptance": False})

    def test_child_failures_are_redacted_and_not_a_success(self):
        children = ["print('secret')", "import sys;sys.stderr.write('secret');sys.exit(1)",
            "import json;print(json.dumps({'type':'result','passed':True,'action':'recover'}));raise SystemExit(1)",
            "import json;print(json.dumps({'type':'result','passed':True,'action':'recover'}));print('secret')",
            "import time;time.sleep(30)"]
        for child in children:
            with self.subTest(child=child), patch.object(RELAY, "PreviewOpener", return_value=self.opener()):
                with self.assertRaises(ValueError) as caught:
                    RELAY.relay_process([sys.executable, "-c", child], ORIGIN, OPS, max_seconds=1)
                self.assertEqual(str(caught.exception), "protected_recovery_relay_failed")


if __name__ == "__main__":
    unittest.main()
