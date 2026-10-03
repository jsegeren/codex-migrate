"""Operator transport safety tests; not proof of a successful hosted backup."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError
from urllib.request import Request

SPEC = importlib.util.spec_from_file_location(
    "vercel_preview_transport", Path(__file__).parents[1] / "ops/vercel_preview_transport.py")
TRANSPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TRANSPORT)
ORIGIN = "https://codex-migrate-abc-joshuas-projects-d3a5c48d.vercel.app"


class PreviewTransportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / ".vercel").mkdir()
        (self.root / ".vercel/project.json").write_text("{}")
        self.opener = TRANSPORT.PreviewOpener(ORIGIN, self.root)

    def request(self, **kwargs):
        return Request(ORIGIN + "/api/hosted-enrollment", data=b'{"action":"resolve"}',
                       headers={"Authorization": "Bearer test-only", "Content-Type": "application/json"},
                       method="POST", **kwargs)

    def fake_run(self, command, **kwargs):
        # The synthetic credential must occur only in stdin, never CLI argv.
        self.assertNotIn("test-only", " ".join(command))
        self.assertEqual(command[:3], [TRANSPORT.CLI, "curl", "/api/hosted-enrollment"])
        self.assertEqual(command[-3:], ["--", "--config", "-"])
        config = kwargs["input"].decode()
        self.assertIn('proto = "=https"', config)
        self.assertIn("max-redirs = 0", config)
        self.assertIn("header = \"Authorization: Bearer test-only\"", config)
        curl_home = Path(kwargs["env"]["CURL_HOME"])
        self.assertTrue((curl_home / ".curlrc").is_file())
        self.assertEqual((curl_home / ".curlrc").read_bytes(), b"")
        self.assertEqual((curl_home / ".curlrc").stat().st_mode & 0o777, 0o600)
        header_line = next(line for line in config.splitlines() if line.startswith("dump-header"))
        path = Path(json.loads(header_line.split(" = ", 1)[1]))
        path.write_bytes(b"HTTP/1.1 200 Connection established\r\n\r\nHTTP/2 200\r\nContent-Type: application/json\r\n\r\n")
        kwargs["stdout"].write(b'{"real":"response"}')
        kwargs["stderr"].write(b"private provider diagnostic")
        return subprocess.CompletedProcess(command, 0)

    def test_real_response_shape_and_stdin_only_credentials(self):
        with patch.object(TRANSPORT.subprocess, "run", side_effect=self.fake_run):
            with self.opener.open(self.request()) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers.get("Content-Type"), "application/json")
                self.assertEqual(json.loads(response.read()), {"real": "response"})

    def test_inherited_execution_auth_and_governance_overrides_are_stripped(self):
        injected = {name: "untrusted" for name in (
            "VERCEL_REAL_CLI", "VERCEL_TOKEN", "NODE_OPTIONS", "NODE_PATH",
            "DYLD_INSERT_LIBRARIES", "VERCEL_GOVERNANCE_AUDIT_PATH",
            "HTTPS_PROXY", "CURL_HOME", "SSL_CERT_FILE")}
        with patch.dict(os.environ, injected), patch.object(
                TRANSPORT.subprocess, "run", side_effect=self.fake_run) as run:
            self.opener.open(self.request()).close()
        environment = run.call_args.kwargs["env"]
        self.assertEqual({key: value for key, value in environment.items() if key != "CURL_HOME"},
                         TRANSPORT.CLI_ENVIRONMENT)
        self.assertTrue((set(environment) - {"CURL_HOME"}).isdisjoint(injected))
        self.assertNotEqual(environment["CURL_HOME"], injected["CURL_HOME"])

    def test_real_curl_does_not_fall_back_to_operator_startup_file(self):
        curl = Path("/usr/bin/curl")
        if not curl.is_file():
            self.skipTest("system curl unavailable")
        operator_home = self.root / "operator-home"
        curl_home = self.root / "private-curl-home"
        operator_home.mkdir()
        curl_home.mkdir()
        (operator_home / ".curlrc").write_text("--not-a-real-curl-option\n")
        (curl_home / ".curlrc").touch(mode=0o600)
        result = subprocess.run([str(curl), "--version"],
            env={"PATH": "/usr/bin:/bin", "HOME": str(operator_home), "CURL_HOME": str(curl_home)},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, b"")

    def test_only_exact_project_preview_origin_allowed(self):
        for origin in ("https://codexbackup.segeren.com", "http://localhost:3000", ORIGIN + ".evil",
                       ORIGIN + "/", ORIGIN + "?token=secret", "https://user@" + ORIGIN[8:]):
            with self.assertRaises(ValueError):
                TRANSPORT.PreviewOpener(origin, self.root)

    def test_unlinked_workspace_refused(self):
        (self.root / ".vercel/project.json").unlink()
        with self.assertRaises(ValueError):
            TRANSPORT.PreviewOpener(ORIGIN, self.root)

    def test_foreign_destination_and_routes_refused_before_cli(self):
        for url in ("https://evil.example/api/hosted-enrollment", ORIGIN + "/api/purchase",
                    ORIGIN + "/api/hosted-enrollment?secret=x", ORIGIN + "/api/hosted-enrollment/",
                    ORIGIN + "/api/../hosted-enrollment"):
            with patch.object(TRANSPORT.subprocess, "run") as run:
                with self.assertRaises(URLError):
                    self.opener.open(Request(url, data=b"{}", method="POST"))
                run.assert_not_called()

    def test_get_and_oversize_and_nonbytes_refused(self):
        for method, body in (("GET", b"{}"), ("POST", b"x" * (TRANSPORT.LIMIT + 1)),
                             ("POST", "private")):
            with self.assertRaises(URLError), patch.object(TRANSPORT.subprocess, "run") as run:
                self.opener.open(Request(ORIGIN + "/api/hosted-enrollment", data=body, method=method))
            run.assert_not_called()

    def test_header_injection_and_unexpected_header_refused(self):
        for key, value in (("Authorization", "secret\r\nurl = evil"), ("Cookie", "private"),
                           ("X-Hosted-Upload-Lease", "secret\x00")):
            request = self.request()
            request.add_header(key, value)
            with self.assertRaises(URLError), patch.object(TRANSPORT.subprocess, "run") as run:
                self.opener.open(request)
            run.assert_not_called()

    def test_timeout_and_provider_failure_are_redacted(self):
        for failure in (subprocess.TimeoutExpired(["private"], 30), OSError("secret")):
            with patch.object(TRANSPORT.subprocess, "run", side_effect=failure):
                with self.assertRaises(URLError) as caught:
                    self.opener.open(self.request())
                self.assertNotIn("secret", str(caught.exception))
                self.assertNotIn("private", str(caught.exception))

    def test_nonzero_cli_exit_cannot_return_success(self):
        with patch.object(TRANSPORT.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)):
            with self.assertRaises(URLError):
                self.opener.open(self.request())

    def test_context_restores_constructors_and_does_not_touch_object_transport(self):
        from codex_migrate import vault_http_store
        original = [module.build_opener for module in
                    (TRANSPORT.enrollment, TRANSPORT.recovery, TRANSPORT.upload, vault_http_store)]
        with self.assertRaises(RuntimeError):
            with TRANSPORT.protected_preview(ORIGIN, self.root):
                self.assertIs(TRANSPORT.enrollment.build_opener(), TRANSPORT.recovery.build_opener())
                self.assertIs(vault_http_store.build_opener, original[-1])
                raise RuntimeError("synthetic")
        self.assertEqual(original, [module.build_opener for module in
                         (TRANSPORT.enrollment, TRANSPORT.recovery, TRANSPORT.upload, vault_http_store)])


if __name__ == "__main__":
    unittest.main()
