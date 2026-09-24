"""Opt-in process-interruption test using an exact packaged Mac engine.

Set CODEX_MIGRATE_VAULT_INTERRUPTION_TEST=yes and CODEX_MIGRATE_TEST_ENGINE to
the packaged engine. Only synthetic transcripts and a disposable Vault are used.
"""

import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import tempfile
import time
import unittest


@unittest.skipUnless(
    platform.system() == "Darwin"
    and os.environ.get("CODEX_MIGRATE_VAULT_INTERRUPTION_TEST") == "yes",
    "opt in to packaged Vault interruption test",
)
class PackagedVaultInterruptionTests(unittest.TestCase):
    def test_killed_backup_preserves_last_verified_snapshot_and_retry(self):
        engine_name = os.environ.get("CODEX_MIGRATE_TEST_ENGINE")
        if not engine_name:
            self.skipTest("set CODEX_MIGRATE_TEST_ENGINE to a packaged engine")
        engine = Path(engine_name).resolve()
        helper = engine.parents[1] / "CodexVaultCrypto"
        self.assertTrue(engine.is_file() and helper.is_file())
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("PYTHON", "DYLD_"))}
        env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"

        with tempfile.TemporaryDirectory(prefix="codex-vault-killed-backup-") as temporary:
            root = Path(temporary)
            home = root / "source"
            sessions = home / ".codex/sessions"
            sessions.mkdir(parents=True)
            transcript = sessions / "fixture.jsonl"
            transcript.write_text(json.dumps({"type": "session_meta", "payload": {
                "id": "44444444-4444-4444-8444-444444444444"}}) + "\n")
            vault = root / "vault"
            command = [str(engine), "vault", "--source-home", str(home),
                       "backup", "--destination", str(vault), "--apply", "--json"]
            key_id = None
            process = None
            try:
                first = subprocess.run(command, env=env, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.PIPE, timeout=120)
                self.assertEqual(first.returncode, 0, "initial packaged backup failed")
                key_id = json.loads((vault / "vault.json").read_text())["key_id"]
                previous_reference = (vault / "latest.json").read_bytes()
                previous_objects = set((vault / "objects").rglob("*.cvchunk"))

                # A large, incompressible synthetic transcript leaves enough
                # time to interrupt after an encrypted chunk is stored but
                # before the new snapshot can become latest.
                with transcript.open("a", encoding="utf-8") as stream:
                    for _ in range(96):
                        stream.write(json.dumps({"type": "response_item", "payload": {
                            "content": base64.b64encode(os.urandom(512 * 1024)).decode("ascii")
                        }}) + "\n")
                source_digest = hashlib.sha256(transcript.read_bytes()).hexdigest()
                process = subprocess.Popen(command, env=env, stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL, start_new_session=True)
                deadline = time.monotonic() + 120
                while time.monotonic() < deadline:
                    if set((vault / "objects").rglob("*.cvchunk")) - previous_objects:
                        break
                    if process.poll() is not None:
                        self.fail("backup finished before a new encrypted chunk was observed")
                    time.sleep(0.01)
                else:
                    self.fail("backup did not store a new encrypted chunk in time")
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=15)
                self.assertEqual(process.returncode, -signal.SIGKILL)
                process = None
                self.assertEqual((vault / "latest.json").read_bytes(), previous_reference)
                verified = subprocess.run(
                    [str(engine), "vault", "--source-home", str(home), "verify",
                     "--vault", str(vault), "--json"],
                    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=120)
                self.assertEqual(verified.returncode, 0, "previous snapshot no longer verifies")
                self.assertEqual(hashlib.sha256(transcript.read_bytes()).hexdigest(), source_digest)

                retried = subprocess.run(command, env=env, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.PIPE, timeout=120)
                self.assertEqual(retried.returncode, 0, "backup did not recover after interruption")
                self.assertNotEqual((vault / "latest.json").read_bytes(), previous_reference)
                verified_retry = subprocess.run(
                    [str(engine), "vault", "--source-home", str(home), "verify",
                     "--vault", str(vault), "--json"],
                    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=120)
                self.assertEqual(verified_retry.returncode, 0, "retried snapshot did not verify")
                self.assertEqual(hashlib.sha256(transcript.read_bytes()).hexdigest(), source_digest)
            finally:
                if process is not None and process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=15)
                if key_id is not None:
                    deleted = subprocess.run([str(helper), "delete-key", "--key-id", key_id],
                                             env=env, stdout=subprocess.DEVNULL,
                                             stderr=subprocess.PIPE, timeout=15)
                    self.assertEqual(deleted.returncode, 0, "fixture Vault key cleanup failed")
