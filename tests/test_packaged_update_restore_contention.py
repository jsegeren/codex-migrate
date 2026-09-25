"""Opt-in physical updater/restore contention test with disposable Codex data.

Run on macOS with CODEX_MIGRATE_RESTORE_CONTENTION_TEST=yes and
CODEX_MIGRATE_TEST_ENGINE pointing at an exact packaged app engine. The test
never reads or changes the account's real Codex home or Vault schedule.
"""

import hashlib
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import platform
import select
import subprocess
import tempfile
import time
import unittest
from urllib.parse import parse_qs, urlsplit


@unittest.skipUnless(platform.system() == "Darwin" and
                     os.environ.get("CODEX_MIGRATE_RESTORE_CONTENTION_TEST") == "yes",
                     "opt in to physical packaged restore contention")
class PackagedRestoreContentionTests(unittest.TestCase):
    def test_update_quit_waits_for_real_vault_restore(self):
        binary = os.environ.get("CODEX_MIGRATE_TEST_ENGINE")
        if not binary:
            self.skipTest("set CODEX_MIGRATE_TEST_ENGINE to a packaged engine")
        engine = Path(binary).resolve()
        helper = engine.parents[2] / "Helpers/CodexVaultCrypto.app/Contents/MacOS/CodexVaultCrypto"
        self.assertTrue(engine.is_file() and helper.is_file())
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("PYTHON", "DYLD_"))}
        env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
        with tempfile.TemporaryDirectory(prefix="codex-vault-restore-contention-") as temporary:
            root = Path(temporary)
            home = root / "source"
            sessions = home / ".codex/sessions"
            sessions.mkdir(parents=True)
            transcript = sessions / "fixture.jsonl"
            line = json.dumps({"payload": {"message": {
                "content": "disposable restore fixture " + "x" * 65536,
            }}}) + "\n"
            with transcript.open("w", encoding="utf-8") as stream:
                for _ in range(2048):
                    stream.write(line)
            source_hash = hashlib.sha256(transcript.read_bytes()).hexdigest()
            vault = root / "vault"
            output = root / "recovered"
            key_id = None
            dashboard = None
            try:
                initial = subprocess.run(
                    [str(engine), "vault", "--source-home", str(home), "backup",
                     "--destination", str(vault), "--apply", "--json"],
                    env=env, capture_output=True, text=True, timeout=120)
                self.assertEqual(initial.returncode, 0, "packaged fixture backup failed")
                key_id = json.loads((vault / "vault.json").read_text())["key_id"]
                snapshot_id = json.loads(initial.stdout)["snapshot_id"]
                dashboard = subprocess.Popen(
                    [str(engine), "launch", "--source-home", str(home),
                     "--state-dir", str(home / ".local/state/codex-migrate-test"),
                     "--port", "0", "--no-open"],
                    env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    text=True, bufsize=1)
                self.assertIsNotNone(dashboard.stdout)
                prefix = "Codex Migrate dashboard: "
                address = ""
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    ready, _, _ = select.select(
                        [dashboard.stdout], [], [], max(0, deadline - time.monotonic()))
                    if not ready:
                        break
                    address = dashboard.stdout.readline().strip()
                    if address.startswith(prefix) or dashboard.poll() is not None:
                        break
                self.assertTrue(address.startswith(prefix),
                                "packaged dashboard did not start (exit %s)" % dashboard.poll())
                parsed = urlsplit(address[len(prefix):])
                self.assertEqual(parsed.hostname, "127.0.0.1")
                token = parse_qs(parsed.fragment).get("token", [None])[0]
                self.assertTrue(token)

                def request(path, method="GET", payload=None):
                    connection = HTTPConnection("127.0.0.1", parsed.port, timeout=5)
                    try:
                        headers = {"X-Codex-Migrate-Token": token}
                        body = None
                        if payload is not None:
                            headers["Content-Type"] = "application/json"
                            body = json.dumps(payload)
                        if path == "/api/update-shutdown":
                            headers["X-Codex-Migrate-Target-Build"] = "17"
                        connection.request(method, path, body=body, headers=headers)
                        response = connection.getresponse()
                        data = json.loads(response.read())
                        return response.status, data
                    finally:
                        connection.close()

                self.assertEqual(request("/api/update-idle")[0], 200)
                status, started = request("/api/vault/restore", "POST", {
                    "vault": str(vault), "output": str(output),
                    "snapshot": snapshot_id, "apply": True,
                })
                self.assertEqual(status, 202)
                self.assertEqual(started["status"], "running",
                                 "fixture restore finished before contention could be tested")
                self.assertEqual(request("/api/update-idle")[0], 409)
                self.assertEqual(request("/api/update-shutdown", "POST")[0], 409)
                self.assertIsNone(dashboard.poll())
                self.assertFalse((home / "Library/Application Support/Codex Vault/update.json").exists())

                deadline = time.monotonic() + 120
                while time.monotonic() < deadline:
                    status, recovered = request("/api/vault/restore-status")
                    self.assertEqual(status, 200)
                    if recovered["status"] in ("completed", "failed"):
                        break
                    time.sleep(0.05)
                self.assertEqual(recovered["status"], "completed", "packaged restore failed")
                self.assertEqual(recovered["snapshot_id"], snapshot_id)
                self.assertEqual(hashlib.sha256(transcript.read_bytes()).hexdigest(), source_hash)
                self.assertEqual(hashlib.sha256((output / "sessions/fixture.jsonl").read_bytes()).hexdigest(),
                                 source_hash)
                self.assertEqual(request("/api/update-idle")[0], 200)
                self.assertEqual(request("/api/update-shutdown", "POST")[0], 200)
                dashboard.wait(timeout=15)
                self.assertEqual(dashboard.returncode, 0)
                dashboard.stdout.close()
                dashboard = None
                marker = home / "Library/Application Support/Codex Vault/update.json"
                self.assertEqual(json.loads(marker.read_text())["target_build"], 17)
            finally:
                if dashboard is not None:
                    dashboard.terminate()
                    dashboard.wait(timeout=15)
                    if dashboard.stdout is not None:
                        dashboard.stdout.close()
                if key_id is not None:
                    deleted = subprocess.run(
                        [str(helper), "delete-key", "--key-id", key_id],
                        env=env, capture_output=True, timeout=15)
                    self.assertEqual(deleted.returncode, 0, "fixture Vault key cleanup failed")
