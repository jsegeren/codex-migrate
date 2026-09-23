"""Opt-in synthetic Vault test across a real APFS volume detach/remount.

Run on macOS with CODEX_MIGRATE_EXTERNAL_VAULT_TEST=yes. This does not load
the account-wide LaunchAgent or read the user's Codex home.
"""

import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from codex_migrate.vault_backup import backup
from codex_migrate.vault_recovery import verify_snapshot
from codex_migrate.vault_schedule import install_schedule, run_scheduled_backup


@unittest.skipUnless(platform.system() == "Darwin" and
                     os.environ.get("CODEX_MIGRATE_EXTERNAL_VAULT_TEST") == "yes",
                     "opt-in external-volume acceptance")
class ExternalVolumeVaultTests(unittest.TestCase):
    def tool(self, *command):
        result = subprocess.run(command, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_external_volume_never_becomes_a_new_local_vault(self):
        root = Path(tempfile.mkdtemp(prefix="codex-vault-volume-test-")).resolve()
        mount = root / "mounted"
        mount.mkdir()
        image = root / "fixture.sparseimage"
        helper = root / "CodexVaultCrypto"
        key_id = None
        try:
            if shutil.disk_usage(root).free < 2 * 1024**3:
                self.skipTest("External-volume acceptance requires 2 GiB free")
            self.tool("xcrun", "swiftc", "-parse-as-library", "-O",
                      "-target", platform.machine() + "-apple-macos13.0",
                      "desktop/CodexVaultCrypto.swift", "-o", str(helper))
            self.tool("/usr/bin/hdiutil", "create", "-size", "512m", "-fs", "APFS",
                      "-type", "SPARSE", "-volname", "CodexVaultVolumeFixture",
                      "-nospotlight", str(image))
            self.tool("/usr/bin/hdiutil", "attach", "-nobrowse", "-owners", "on",
                      "-mountpoint", str(mount), str(image))
            self.assertTrue(os.path.ismount(mount))
            self.assertNotEqual(mount.stat().st_dev, root.stat().st_dev)

            source = root / "source"
            sessions = source / ".codex/sessions"
            sessions.mkdir(parents=True)
            transcript = sessions / "fixture.jsonl"
            transcript.write_text(json.dumps({"type": "session_meta", "payload": {
                "id": "44444444-4444-4444-8444-444444444444"}}) + "\n")
            vault = mount / "vault"
            first = backup(str(source), str(vault), crypto_helper=str(helper))
            key_id = first.key_id
            self.assertIsNotNone(first.recovery_key)
            self.assertEqual(verify_snapshot(str(vault), crypto_helper=str(helper)).snapshot_id,
                             first.snapshot_id)
            with patch("codex_migrate.vault_schedule._loaded", return_value=False), \
                    patch("codex_migrate.vault_schedule._launchctl"):
                install_schedule(str(source), str(vault), crypto_helper=str(helper),
                                 engine_command=[str(helper)])
            config = source / "Library/Application Support/Codex Vault/schedule.json"

            self.tool("/usr/bin/hdiutil", "detach", str(mount))
            self.assertFalse(os.path.ismount(mount))
            self.assertEqual(run_scheduled_backup(str(config)), 1)
            self.assertFalse(vault.exists(), "a missing drive must not create a local replacement Vault")

            self.tool("/usr/bin/hdiutil", "attach", "-nobrowse", "-owners", "on",
                      "-mountpoint", str(mount), str(image))
            self.assertTrue(os.path.ismount(mount))
            transcript.write_text(transcript.read_text() + json.dumps({
                "type": "response_item", "payload": {"role": "assistant", "content": "fixture"}}) + "\n")
            self.assertEqual(run_scheduled_backup(str(config)), 0)
            latest = verify_snapshot(str(vault), crypto_helper=str(helper))
            self.assertNotEqual(latest.snapshot_id, first.snapshot_id)
            self.assertEqual(json.loads((config.parent / "last-run.json").read_text())["status"], "completed")
        finally:
            cleanup_error = None
            if key_id is not None:
                try:
                    self.tool(str(helper), "delete-key", "--key-id", key_id)
                except Exception as error:
                    cleanup_error = error
            if os.path.ismount(mount):
                try:
                    self.tool("/usr/bin/hdiutil", "detach", str(mount))
                except Exception as error:
                    cleanup_error = cleanup_error or error
            if mount.exists() and mount.stat().st_dev != root.stat().st_dev:
                raise RuntimeError("Mounted external-volume fixture retained at " + str(root))
            shutil.rmtree(root)
            if cleanup_error is not None:
                raise cleanup_error
