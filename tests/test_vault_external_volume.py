"""Opt-in synthetic Vault tests across ordinary and case-sensitive APFS volumes.

Run on macOS with CODEX_MIGRATE_EXTERNAL_VAULT_TEST=yes. This does not load
the account-wide LaunchAgent or read the user's Codex home.
"""

import base64
import hashlib
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
        self.exercise_external_volume("APFS")

    def test_missing_case_sensitive_external_volume_never_becomes_a_new_local_vault(self):
        self.exercise_external_volume("Case-sensitive APFS")

    def test_case_sensitive_source_restore_refuses_case_collision_on_ordinary_apfs(self):
        packaged_engine = os.environ.get("CODEX_MIGRATE_TEST_ENGINE")
        if not packaged_engine:
            self.skipTest("set CODEX_MIGRATE_TEST_ENGINE to a packaged engine")
        helper = Path(packaged_engine).resolve().parents[1] / "CodexVaultCrypto"
        self.assertTrue(helper.is_file())
        root = Path(tempfile.mkdtemp(prefix="codex-vault-case-source-test-")).resolve()
        sensitive_mount = root / "case-sensitive"
        ordinary_mount = root / "ordinary"
        sensitive_mount.mkdir()
        ordinary_mount.mkdir()
        key_id = None
        try:
            if shutil.disk_usage(root).free < 2 * 1024**3:
                self.skipTest("Case-sensitive source acceptance requires 2 GiB free")
            for mount, filesystem, name in (
                (sensitive_mount, "Case-sensitive APFS", "CodexVaultCaseSource"),
                (ordinary_mount, "APFS", "CodexVaultOrdinaryOutput"),
            ):
                image = root / (mount.name + ".sparseimage")
                self.tool("/usr/bin/hdiutil", "create", "-size", "256m", "-fs", filesystem,
                          "-type", "SPARSE", "-volname", name, "-nospotlight", str(image))
                self.tool("/usr/bin/hdiutil", "attach", "-nobrowse", "-owners", "on",
                          "-mountpoint", str(mount), str(image))
                self.assertTrue(os.path.ismount(mount))
            probe = sensitive_mount / "CaseProbe"
            probe.write_text("fixture", encoding="utf-8")
            self.assertFalse((sensitive_mount / "caseprobe").exists())
            probe.unlink()
            probe = ordinary_mount / "CaseProbe"
            probe.write_text("fixture", encoding="utf-8")
            self.assertTrue((ordinary_mount / "caseprobe").exists())
            probe.unlink()

            source = sensitive_mount / "source"
            sessions = source / ".codex/sessions"
            sessions.mkdir(parents=True)
            original = {}
            for name, thread_id in (
                ("Thread.jsonl", "44444444-4444-4444-8444-444444444444"),
                ("thread.jsonl", "55555555-5555-4555-8555-555555555555"),
            ):
                content = json.dumps({"type": "session_meta", "payload": {"id": thread_id}}) + "\n"
                (sessions / name).write_text(content, encoding="utf-8")
                original[name] = content
            vault = root / "vault"
            backup_result = subprocess.run([
                packaged_engine, "vault", "--source-home", str(source), "backup",
                "--destination", str(vault), "--apply", "--json",
            ], capture_output=True, text=True, timeout=120)
            self.assertEqual(backup_result.returncode, 0, "case-sensitive source backup failed")
            key_id = json.loads((vault / "vault.json").read_text())["key_id"]
            self.assertEqual(verify_snapshot(str(vault), crypto_helper=str(helper)).transcript_files, 2)

            def restore(output):
                return subprocess.run([
                    packaged_engine, "vault", "--source-home", str(source), "restore",
                    "--vault", str(vault), "--snapshot", "latest", "--output", str(output),
                    "--apply", "--json",
                ], capture_output=True, text=True, timeout=120)

            preserved = sensitive_mount / "restored"
            self.assertEqual(restore(preserved).returncode, 0,
                             "case-sensitive restore failed to retain distinct filenames")
            for name, content in original.items():
                self.assertEqual((preserved / "sessions" / name).read_text(), content)

            collision = ordinary_mount / "restored"
            self.assertNotEqual(restore(collision).returncode, 0,
                                "ordinary APFS silently merged distinct transcripts")
            self.assertFalse((collision / "restore-receipt.json").exists())
            staged = collision / "sessions/Thread.jsonl"
            self.assertTrue(staged.is_file())
            self.assertIn(staged.read_text(), original.values())
            self.assertEqual(verify_snapshot(str(vault), crypto_helper=str(helper)).transcript_files, 2)
            for name, content in original.items():
                self.assertEqual((sessions / name).read_text(), content)
        finally:
            cleanup_error = None
            if key_id is not None:
                try:
                    self.tool(str(helper), "delete-key", "--key-id", key_id)
                except Exception as error:
                    cleanup_error = error
            for mount in (sensitive_mount, ordinary_mount):
                if os.path.ismount(mount):
                    try:
                        self.tool("/usr/bin/hdiutil", "detach", str(mount))
                    except Exception as error:
                        cleanup_error = cleanup_error or error
                if mount.exists() and mount.stat().st_dev != root.stat().st_dev:
                    raise RuntimeError("Mounted case-source fixture retained at " + str(root))
            shutil.rmtree(root)
            if cleanup_error is not None:
                raise cleanup_error

    def test_full_external_volume_keeps_last_verified_snapshot_and_recovers(self):
        packaged_engine = os.environ.get("CODEX_MIGRATE_TEST_ENGINE")
        if not packaged_engine:
            self.skipTest("set CODEX_MIGRATE_TEST_ENGINE to a packaged engine")
        root = Path(tempfile.mkdtemp(prefix="codex-vault-full-volume-test-")).resolve()
        mount = root / "mounted"
        mount.mkdir()
        image = root / "fixture.sparseimage"
        helper = Path(packaged_engine).resolve().parents[1] / "CodexVaultCrypto"
        self.assertTrue(helper.is_file())
        key_id = None
        try:
            if shutil.disk_usage(root).free < 2 * 1024**3:
                self.skipTest("External-volume acceptance requires 2 GiB free")
            self.tool("/usr/bin/hdiutil", "create", "-size", "512m", "-fs", "APFS",
                      "-type", "SPARSE", "-volname", "CodexVaultFullFixture",
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

            def packaged_backup():
                return subprocess.run([
                    packaged_engine, "vault", "--source-home", str(source),
                    "backup", "--destination", str(vault), "--apply", "--json",
                ], capture_output=True, text=True, timeout=120)

            initial = packaged_backup()
            self.assertEqual(initial.returncode, 0, "initial packaged backup failed")
            key_id = json.loads((vault / "vault.json").read_text())["key_id"]
            first = verify_snapshot(str(vault), crypto_helper=str(helper))
            first_reference = (vault / "latest.json").read_bytes()
            # A new snapshot genuinely needs more than the space left below.
            # Its source content is synthetic and kept off the mounted volume.
            with transcript.open("a", encoding="utf-8") as stream:
                for _ in range(48):
                    stream.write(json.dumps({"type": "response_item", "payload": {
                        "content": base64.b64encode(os.urandom(1024 * 1024)).decode("ascii"),
                    }}) + "\n")
            source_digest = hashlib.sha256(transcript.read_bytes()).hexdigest()
            pressure = mount / "disposable-space-pressure"
            free_mib = shutil.disk_usage(mount).free // (1024 * 1024)
            self.assertGreater(free_mib, 100)
            self.tool("/bin/dd", "if=/dev/zero", "of=" + str(pressure),
                      "bs=1048576", "count=" + str(free_mib - 24))
            self.assertLess(shutil.disk_usage(mount).free, 32 * 1024 * 1024)
            failed = packaged_backup()
            self.assertNotEqual(failed.returncode, 0, "full Vault volume unexpectedly published a snapshot")
            self.assertEqual((vault / "latest.json").read_bytes(), first_reference)
            self.assertEqual(verify_snapshot(str(vault), crypto_helper=str(helper)).snapshot_id,
                             first.snapshot_id)
            self.assertEqual(hashlib.sha256(transcript.read_bytes()).hexdigest(), source_digest)
            pressure.unlink()
            retried = packaged_backup()
            self.assertEqual(retried.returncode, 0, "backup did not recover after space was freed")
            self.assertNotEqual(verify_snapshot(str(vault), crypto_helper=str(helper)).snapshot_id,
                                first.snapshot_id)
            self.assertEqual(hashlib.sha256(transcript.read_bytes()).hexdigest(), source_digest)
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
                raise RuntimeError("Mounted full-volume fixture retained at " + str(root))
            shutil.rmtree(root)
            if cleanup_error is not None:
                raise cleanup_error

    def exercise_external_volume(self, filesystem):
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
            self.tool("/usr/bin/hdiutil", "create", "-size", "512m", "-fs", filesystem,
                      "-type", "SPARSE", "-volname", "CodexVaultVolumeFixture",
                      "-nospotlight", str(image))
            self.tool("/usr/bin/hdiutil", "attach", "-nobrowse", "-owners", "on",
                      "-mountpoint", str(mount), str(image))
            self.assertTrue(os.path.ismount(mount))
            self.assertNotEqual(mount.stat().st_dev, root.stat().st_dev)
            probe = mount / "CaseProbe"
            probe.write_text("test", encoding="utf-8")
            self.assertEqual((mount / "caseprobe").exists(), filesystem == "APFS")
            probe.unlink()

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
            packaged_engine = os.environ.get("CODEX_MIGRATE_TEST_ENGINE")
            with patch("codex_migrate.vault_schedule._loaded", return_value=False), \
                    patch("codex_migrate.vault_schedule._launchctl"):
                install_schedule(str(source), str(vault), crypto_helper=str(helper),
                                 engine_command=[packaged_engine or str(helper)])
            config = source / "Library/Application Support/Codex Vault/schedule.json"

            def scheduled_run():
                if packaged_engine:
                    result = subprocess.run([
                        packaged_engine, "vault", "--source-home", str(source),
                        "scheduled-run", "--config", str(config),
                    ], capture_output=True, text=True, timeout=60)
                    self.assertNotIn("fixture", result.stdout + result.stderr)
                    return result.returncode
                return run_scheduled_backup(str(config))

            self.tool("/usr/bin/hdiutil", "detach", str(mount))
            self.assertFalse(os.path.ismount(mount))
            self.assertEqual(scheduled_run(), 1)
            self.assertFalse(vault.exists(), "a missing drive must not create a local replacement Vault")

            self.tool("/usr/bin/hdiutil", "attach", "-nobrowse", "-owners", "on",
                      "-mountpoint", str(mount), str(image))
            self.assertTrue(os.path.ismount(mount))
            transcript.write_text(transcript.read_text() + json.dumps({
                "type": "response_item", "payload": {"role": "assistant", "content": "fixture"}}) + "\n")
            self.assertEqual(scheduled_run(), 0)
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
