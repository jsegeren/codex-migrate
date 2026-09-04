"""Exercise the actual dashboard process, not just a constructed HTTP handler."""
import json
import importlib.util
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, urlopen

from codex_migrate.cli import _port


class DesktopTests(unittest.TestCase):
    def test_port_zero_selects_an_ephemeral_port(self):
        self.assertEqual(_port("0"), 0)

    def test_real_dashboard_startup_and_graceful_shutdown(self):
        root = Path(__file__).resolve().parents[1]
        binary = os.environ.get("CODEX_MIGRATE_TEST_ENGINE")
        command = [binary] if binary else [sys.executable, "-m", "codex_migrate"]
        with tempfile.TemporaryDirectory() as temporary:
            env = dict(os.environ, PYTHONPATH=str(root / "src"))
            if binary:
                env = {key: value for key, value in env.items()
                       if not key.startswith(("PYTHON", "DYLD_"))}
                env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
            process = subprocess.Popen(command + [
                "serve", "--port", "0", "--no-open", "--target", "person@fixture.local",
                "--target-home", "/Users/person", "--source-home", temporary,
                "--state-dir", temporary + "/state",
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
            try:
                self.assertTrue(select.select([process.stdout], [], [], 20)[0], "Dashboard startup timed out")
                line = process.stdout.readline().decode()
                prefix = "Codex Migrate dashboard: "
                self.assertTrue(line.startswith(prefix), "Expected a dashboard-ready message")
                url = urlparse(line[len(prefix):].strip())
                self.assertEqual(url.hostname, "127.0.0.1")
                self.assertGreater(url.port, 0)
                token = parse_qs(url.fragment)["token"][0]
                request = Request("http://127.0.0.1:%d/api/status" % url.port,
                                  headers={"X-Codex-Migrate-Token": token})
                with urlopen(request, timeout=3) as response:
                    state = json.load(response)
                self.assertFalse(state["apply"])
                self.assertEqual(state["status"], "idle")
                base = "http://127.0.0.1:%d" % url.port
                with urlopen(base + "/", timeout=3) as response:
                    html = response.read().decode()
                    self.assertIn("Backup required before replacement", html)
                    self.assertIn("There is no skip-backup option", html)
                    self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
                with self.assertRaises(HTTPError) as denied:
                    urlopen(base + "/api/status", timeout=3)
                self.assertEqual(denied.exception.code, 403)
                denied.exception.close()
                forbidden = Request(base + "/api/action", data=b'{"action":"start"}',
                                    headers={"X-Codex-Migrate-Token": token,
                                             "Content-Type": "application/json"})
                with self.assertRaises(HTTPError) as read_only:
                    urlopen(forbidden, timeout=3)
                self.assertEqual(read_only.exception.code, 400)
                read_only.exception.close()
                process.terminate()
                process.wait(timeout=15)
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=5)

    def test_release_build_requires_signing_and_notarization(self):
        if sys.platform != "darwin":
            self.skipTest("macOS release guard")
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run([sys.executable, str(root / "desktop/build.py"), "--release"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("release requires --identity and --notary-profile", result.stderr)

    def test_release_requires_clean_source_and_records_revision(self):
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location("desktop_build", root / "desktop/build.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with patch.object(module.subprocess, "check_output", side_effect=["abc123\n", " M source.py\n"]):
            with self.assertRaisesRegex(ValueError, "clean committed"):
                module.source_receipt(release=True)
        with patch.object(module.subprocess, "check_output", side_effect=["abc123\n", ""]):
            receipt = module.source_receipt(release=True)
        self.assertEqual(receipt["source_revision"], "abc123")
        self.assertFalse(receipt["source_dirty"])
        self.assertEqual(receipt["build_mode"], "release")


if __name__ == "__main__":
    unittest.main()
