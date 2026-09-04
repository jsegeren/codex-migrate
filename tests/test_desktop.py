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
    def test_real_engine_internal_bridge_rejects_invalid_payload(self):
        binary = os.environ.get("CODEX_MIGRATE_TEST_ENGINE")
        root = Path(__file__).resolve().parents[1]
        command = [binary] if binary else [sys.executable, str(root / "src/codex_migrate/__main__.py")]
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("PYTHON", "DYLD_"))}
        env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(command + ["_ssh-rsync", "invalid-payload"], cwd=temporary,
                                    env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 76, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn("could not safely start the rsync SSH connection", result.stderr)

    def test_real_engine_inventories_git_storage_dependencies(self):
        from test_git_inventory import GitInventoryTests

        fixture = GitInventoryTests()
        fixture.setUp()
        try:
            root = Path(__file__).resolve().parents[1]
            binary = os.environ.get("CODEX_MIGRATE_TEST_ENGINE")
            command = [binary] if binary else [sys.executable, "-m", "codex_migrate"]
            env = dict(os.environ, PYTHONPATH=str(root / "src"))
            if binary:
                env = {key: value for key, value in env.items() if not key.startswith(("PYTHON", "DYLD_"))}
                env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
            command += ["inventory", "--source-home", str(fixture.home), "--json"]
            result = subprocess.run(command, env=env, capture_output=True, text=True,
                                    check=True, timeout=30)
            report = json.loads(result.stdout)
            self.assertEqual(report["git_missing_paths"], [str(fixture.repo)])
            result = subprocess.run(command + ["--workspace", str(fixture.repo)], env=env,
                                    capture_output=True, text=True, check=True, timeout=30)
            report = json.loads(result.stdout)
            self.assertEqual(report["git_missing_paths"], [])
            self.assertEqual(report["git_issues"], [])
            self.assertEqual(len(report["git_details"]), 2)
            profile = fixture.home / ".codex/work.config.toml"
            profile.write_text('sqlite_home = "PRIVATE_STORAGE_FIXTURE"')
            blocked = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(blocked.returncode, 0)
            self.assertEqual(blocked.stdout, "")
            self.assertIn("sqlite_home setting", blocked.stderr)
            self.assertNotIn("PRIVATE_STORAGE_FIXTURE", blocked.stderr)
            self.assertEqual(profile.read_text(), 'sqlite_home = "PRIVATE_STORAGE_FIXTURE"')
        finally:
            fixture.doCleanups()

    def test_real_browser_helper_starts_without_destination_and_stops(self):
        root = Path(__file__).resolve().parents[1]
        binary = os.environ.get("CODEX_MIGRATE_TEST_ENGINE")
        command = [binary] if binary else [sys.executable, "-m", "codex_migrate"]
        with tempfile.TemporaryDirectory() as temporary:
            env = dict(os.environ, PYTHONPATH=str(root / "src"))
            if binary:
                env = {key: value for key, value in env.items() if not key.startswith(("PYTHON", "DYLD_"))}
                env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
            process = subprocess.Popen(command + ["launch", "--port", "0", "--no-open",
                                       "--source-home", temporary, "--state-dir", temporary + "/state"],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
            try:
                self.assertTrue(select.select([process.stdout], [], [], 60)[0])
                line = process.stdout.readline().decode()
                prefix = "Codex Migrate dashboard: "
                self.assertTrue(line.startswith(prefix), "Helper startup failed")
                url = urlparse(line[len(prefix):].strip())
                self.assertEqual(url.hostname, "127.0.0.1")
                token = parse_qs(url.fragment)["token"][0]
                base = "http://127.0.0.1:%d" % url.port
                request = Request(base + "/api/setup", headers={"X-Codex-Migrate-Token": token})
                with urlopen(request, timeout=3) as response:
                    state = json.load(response)
                self.assertFalse(state["attached"])
                self.assertIsNone(state["saved"])
                # Exercise the bundled selective-engine import and real HTTP
                # configuration, without inspecting or contacting a remote Mac.
                headers = {"X-Codex-Migrate-Token": token,
                           "Content-Type": "application/json", "Origin": base}
                for relative in (".CODEX", ".SSH", ".AGENTS/SKILLS", "STATE"):
                    unsafe = dict(target="person@fixture.invalid", target_home="/Users/person",
                                  workspace_roots=[temporary + "/" + relative], mode="full")
                    with self.assertRaises(HTTPError) as denied:
                        urlopen(Request(base + "/api/setup", data=json.dumps(unsafe).encode(),
                                        headers=headers), timeout=3)
                    self.assertEqual(denied.exception.code, 400)
                    denied.exception.close()
                    with urlopen(request, timeout=3) as response:
                        unchanged = json.load(response)
                    self.assertFalse(unchanged["attached"])
                    self.assertIsNone(unchanged["saved"])
                setup = dict(target="person@fixture.invalid", target_home="/Users/person",
                             workspace_roots=[], mode="skills", components=["personal-skills"])
                with urlopen(Request(base + "/api/setup", data=json.dumps(setup).encode(),
                                     headers=headers), timeout=3) as response:
                    self.assertEqual(response.status, 200)
                with urlopen(Request(base + "/api/status", headers=headers), timeout=3) as response:
                    configured = json.load(response)
                self.assertEqual(configured["migration_mode"], "skills")
                self.assertEqual(configured["components"], ["personal-skills"])
                self.assertEqual(configured["status"], "idle")
                self.assertFalse(configured["apply"])
                with urlopen(Request(base + "/api/support-report", headers=headers), timeout=3) as response:
                    report = json.load(response)
                self.assertEqual(report["report_format"], 1)
                self.assertEqual(report["migration_mode"], "skills")
                self.assertNotIn("fixture.invalid", json.dumps(report))
                if binary:
                    self.assertRegex(report["build"]["source_revision"], r"^[0-9a-f]{40,64}$")
                    self.assertIn(report["build"]["mode"], ("local-test", "release"))
                with self.assertRaises(HTTPError) as denied:
                    urlopen(Request(base + "/api/action", data=b'{"action":"start"}',
                                    headers=headers), timeout=3)
                self.assertEqual(denied.exception.code, 400)
                denied.exception.close()
                process.terminate()
                process.wait(timeout=15)
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=5)

    @unittest.skipUnless(sys.platform == "darwin", "native macOS persistence")
    def test_native_saved_setup_permissions_and_recovery(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary) / "saved-setup-checks"
            subprocess.run(["xcrun", "swiftc", "-parse-as-library",
                            str(root / "desktop/SavedSetup.swift"),
                            str(root / "tests/SavedSetupChecks.swift"), "-o", str(binary)],
                           check=True, capture_output=True, text=True, timeout=60)
            result = subprocess.run([str(binary), temporary], capture_output=True,
                                    text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Saved setup checks passed", result.stdout)

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
                # Allow a bounded cold-start budget on shared macOS runners
                # without weakening any dashboard or safety assertions.
                self.assertTrue(select.select([process.stdout], [], [], 60)[0],
                                "Dashboard startup timed out after 60 seconds")
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
                    self.assertIn('id="restore_recovery"', html)
                    self.assertIn("Current entries will be kept separately, not merged", html)
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
                # A corrupt/incomplete saved recovery proof must not fall
                # through into ordinary inspection. This also exercises the
                # packaged reconciliation imports without making any SSH call.
                from codex_migrate.state import StateStore
                StateStore(temporary + "/state").update(
                    status="failed", phase="recovery_required",
                    recovery={"status": "restore_unconfirmed"},
                    recovery_attempt={"resolved": True})
                blocked = Request(base + "/api/action", data=b'{"action":"inspect"}',
                                  headers={"X-Codex-Migrate-Token": token,
                                           "Content-Type": "application/json"})
                with self.assertRaises(HTTPError) as recovery_block:
                    urlopen(blocked, timeout=3)
                self.assertEqual(recovery_block.exception.code, 400)
                self.assertIn("resolve the previous restoration", recovery_block.exception.read().decode())
                recovery_block.exception.close()
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
