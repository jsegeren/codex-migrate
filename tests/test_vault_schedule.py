import json
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import plistlib
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from codex_migrate.errors import MigrationError
from codex_migrate.vault_backup import BackupResult
from codex_migrate.vault_schedule import (
    LABEL,
    install_schedule,
    plan_schedule,
    remove_schedule,
    run_scheduled_backup,
    schedule_status,
)


class VaultScheduleTests(unittest.TestCase):
    def fixture(self, root: Path):
        home = root / "home"
        vault = root / "vault"
        helper = root / "CodexVaultCrypto"
        home.mkdir(mode=0o700)
        vault.mkdir(mode=0o700)
        helper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        helper.chmod(0o700)
        verified = SimpleNamespace(vault=str(vault.resolve()))
        return home, vault, helper, verified

    def test_plan_verifies_existing_vault_without_installing_anything(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home, vault, helper, verified = self.fixture(root)
            with patch("codex_migrate.vault_schedule.verify_snapshot",
                       return_value=verified) as verify:
                result = plan_schedule(
                    str(home), str(vault), crypto_helper=str(helper))
            self.assertFalse(result.applied)
            self.assertEqual(result.interval_hours, 24)
            verify.assert_called_once_with(str(vault), crypto_helper=str(helper))
            self.assertFalse((home / "Library").exists())

    def test_install_writes_private_control_files_and_loads_launch_agent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home, vault, helper, verified = self.fixture(root)
            engine = root / "Codex Migrate"
            engine.write_text("fixture", encoding="utf-8")
            engine.chmod(0o700)
            with patch("codex_migrate.vault_schedule.verify_snapshot",
                       return_value=verified), \
                    patch("codex_migrate.vault_schedule._loaded", return_value=False), \
                    patch("codex_migrate.vault_schedule._launchctl") as launchctl:
                result = install_schedule(
                    str(home), str(vault), interval_hours=12,
                    crypto_helper=str(helper), engine_command=[str(engine)])

            self.assertTrue(result.applied)
            config_path = home / "Library/Application Support/Codex Vault/schedule.json"
            plist_path = home / "Library/LaunchAgents" / (LABEL + ".plist")
            self.assertEqual(config_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(plist_path.stat().st_mode & 0o777, 0o600)
            config = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(config["vault"], str(vault.resolve()))
            self.assertEqual(config["interval_seconds"], 12 * 3600)
            plist = plistlib.loads(plist_path.read_bytes())
            self.assertEqual(plist["Label"], LABEL)
            self.assertEqual(plist["StartInterval"], 12 * 3600)
            self.assertEqual(plist["ProgramArguments"], [
                str(engine), "vault", "--source-home", str(home.resolve()),
                "scheduled-run", "--config", str(config_path.resolve()),
            ])
            launchctl.assert_called_once_with([
                "bootstrap", "gui/%d" % os.getuid(), str(plist_path.resolve()),
            ])

    def test_status_reports_loaded_schedule_and_last_completed_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home, vault, helper, verified = self.fixture(root)
            engine = root / "engine"
            engine.write_text("fixture", encoding="utf-8")
            engine.chmod(0o700)
            with patch("codex_migrate.vault_schedule.verify_snapshot",
                       return_value=verified), \
                    patch("codex_migrate.vault_schedule._loaded", return_value=False), \
                    patch("codex_migrate.vault_schedule._launchctl"):
                install_schedule(
                    str(home), str(vault), crypto_helper=str(helper),
                    engine_command=[str(engine)])
            status_path = home / "Library/Application Support/Codex Vault/last-run.json"
            status_path.write_text(json.dumps({
                "status": "completed", "completed_at": datetime.now(timezone.utc).isoformat(),
                "snapshot_id": "fixture-snapshot", "transcript_files": 2,
                "transcript_bytes": 100,
            }), encoding="utf-8")
            status_path.chmod(0o600)
            with patch("codex_migrate.vault_schedule._loaded", return_value=True):
                result = schedule_status(str(home))
            self.assertTrue(result["enabled"])
            self.assertTrue(result["healthy"])
            self.assertEqual(result["interval_hours"], 24)
            self.assertEqual(result["last_run"]["status"], "completed")

    def test_status_does_not_call_an_overdue_backup_healthy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home, vault, helper, verified = self.fixture(root)
            engine = root / "engine"
            engine.write_text("fixture", encoding="utf-8")
            engine.chmod(0o700)
            with patch("codex_migrate.vault_schedule.verify_snapshot",
                       return_value=verified), \
                    patch("codex_migrate.vault_schedule._loaded", return_value=False), \
                    patch("codex_migrate.vault_schedule._launchctl"):
                install_schedule(str(home), str(vault), crypto_helper=str(helper),
                                 engine_command=[str(engine)])
            config_path = home / "Library/Application Support/Codex Vault/schedule.json"
            status_path = config_path.parent / "last-run.json"
            old = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat()
            configuration = json.loads(config_path.read_text(encoding="utf-8"))
            configuration["installed_at"] = old
            config_path.write_text(json.dumps(configuration), encoding="utf-8")
            status_path.write_text(json.dumps({
                "status": "completed", "completed_at": old,
                "snapshot_id": "old-snapshot", "transcript_files": 2,
                "transcript_bytes": 100,
            }), encoding="utf-8")
            status_path.chmod(0o600)
            with patch("codex_migrate.vault_schedule._loaded", return_value=True):
                result = schedule_status(str(home))
            self.assertFalse(result["healthy"])
            self.assertIn("overdue", result["error"])

    def test_schedule_reinstall_does_not_reuse_old_success_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home, vault, helper, verified = self.fixture(root)
            engine = root / "engine"
            engine.write_text("fixture", encoding="utf-8")
            engine.chmod(0o700)
            with patch("codex_migrate.vault_schedule.verify_snapshot",
                       return_value=verified), \
                    patch("codex_migrate.vault_schedule._loaded", return_value=False), \
                    patch("codex_migrate.vault_schedule._launchctl"):
                install_schedule(str(home), str(vault), crypto_helper=str(helper),
                                 engine_command=[str(engine)])
            status_path = home / "Library/Application Support/Codex Vault/last-run.json"
            old_receipts = [
                {"status": "completed", "completed_at": "2026-09-18T00:00:00Z",
                 "snapshot_id": "old-snapshot", "transcript_files": 2,
                 "transcript_bytes": 100},
                {"status": "running", "started_at": "2026-09-18T00:00:00Z"},
                {"status": "failed", "failed_at": "2026-09-18T00:00:00Z",
                 "error": "Automatic backup stopped safely. The previous verified snapshot and local Codex data were not changed."},
            ]
            for receipt in old_receipts:
                status_path.write_text(json.dumps(receipt), encoding="utf-8")
                status_path.chmod(0o600)
                with patch("codex_migrate.vault_schedule._loaded", return_value=True):
                    result = schedule_status(str(home))
                self.assertTrue(result["enabled"])
                self.assertNotIn("last_run", result)

    def test_schedule_without_any_run_becomes_overdue(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home, vault, helper, verified = self.fixture(root)
            engine = root / "engine"
            engine.write_text("fixture", encoding="utf-8")
            engine.chmod(0o700)
            with patch("codex_migrate.vault_schedule.verify_snapshot",
                       return_value=verified), \
                    patch("codex_migrate.vault_schedule._loaded", return_value=False), \
                    patch("codex_migrate.vault_schedule._launchctl"):
                install_schedule(str(home), str(vault), crypto_helper=str(helper),
                                 engine_command=[str(engine)])
            config_path = home / "Library/Application Support/Codex Vault/schedule.json"
            configuration = json.loads(config_path.read_text(encoding="utf-8"))
            configuration["installed_at"] = (
                datetime.now(timezone.utc) - timedelta(days=4)).isoformat()
            config_path.write_text(json.dumps(configuration), encoding="utf-8")
            with patch("codex_migrate.vault_schedule._loaded", return_value=True):
                result = schedule_status(str(home))
            self.assertFalse(result["healthy"])
            self.assertIn("overdue", result["error"])

    def test_stalled_running_receipt_does_not_look_healthy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home, vault, helper, verified = self.fixture(root)
            engine = root / "engine"
            engine.write_text("fixture", encoding="utf-8")
            engine.chmod(0o700)
            with patch("codex_migrate.vault_schedule.verify_snapshot",
                       return_value=verified), \
                    patch("codex_migrate.vault_schedule._loaded", return_value=False), \
                    patch("codex_migrate.vault_schedule._launchctl"):
                install_schedule(str(home), str(vault), crypto_helper=str(helper),
                                 engine_command=[str(engine)])
            config_path = home / "Library/Application Support/Codex Vault/schedule.json"
            status_path = config_path.parent / "last-run.json"
            started = datetime.now(timezone.utc) - timedelta(days=4)
            configuration = json.loads(config_path.read_text(encoding="utf-8"))
            configuration["installed_at"] = (started - timedelta(days=1)).isoformat()
            config_path.write_text(json.dumps(configuration), encoding="utf-8")
            status_path.write_text(json.dumps({
                "status": "running", "started_at": started.isoformat(),
            }), encoding="utf-8")
            status_path.chmod(0o600)
            with patch("codex_migrate.vault_schedule._loaded", return_value=True):
                result = schedule_status(str(home))
            self.assertFalse(result["healthy"])
            self.assertIn("overdue", result["error"])

    def test_scheduled_run_reuses_key_and_records_content_free_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home, vault, helper, verified = self.fixture(root)
            engine = root / "engine"
            engine.write_text("fixture", encoding="utf-8")
            engine.chmod(0o700)
            with patch("codex_migrate.vault_schedule.verify_snapshot",
                       return_value=verified), \
                    patch("codex_migrate.vault_schedule._loaded", return_value=False), \
                    patch("codex_migrate.vault_schedule._launchctl"):
                install_schedule(
                    str(home), str(vault), crypto_helper=str(helper),
                    engine_command=[str(engine)])
            config_path = home / "Library/Application Support/Codex Vault/schedule.json"
            completed = BackupResult(
                destination=str(vault), snapshot_id="safe-snapshot",
                transcript_files=3, transcript_bytes=400, chunks=2,
                key_id="private-key-id", recovery_key=None,
            )
            with patch("codex_migrate.vault_schedule.backup",
                       return_value=completed) as backup:
                self.assertEqual(run_scheduled_backup(str(config_path)), 0)
            backup.assert_called_once_with(
                str(home.resolve()), str(vault.resolve()), crypto_helper=str(helper))
            last_run = json.loads((config_path.parent / "last-run.json").read_text(
                encoding="utf-8"))
            self.assertEqual(last_run["status"], "completed")
            self.assertEqual(last_run["snapshot_id"], "safe-snapshot")
            self.assertNotIn("key_id", last_run)
            self.assertNotIn("recovery_key", last_run)

    def test_failed_run_exposes_no_exception_or_customer_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home, vault, helper, verified = self.fixture(root)
            engine = root / "engine"
            engine.write_text("fixture", encoding="utf-8")
            engine.chmod(0o700)
            with patch("codex_migrate.vault_schedule.verify_snapshot",
                       return_value=verified), \
                    patch("codex_migrate.vault_schedule._loaded", return_value=False), \
                    patch("codex_migrate.vault_schedule._launchctl"):
                install_schedule(
                    str(home), str(vault), crypto_helper=str(helper),
                    engine_command=[str(engine)])
            config_path = home / "Library/Application Support/Codex Vault/schedule.json"
            with patch("codex_migrate.vault_schedule.backup",
                       side_effect=RuntimeError("PRIVATE CUSTOMER CONTENT")):
                self.assertEqual(run_scheduled_backup(str(config_path)), 1)
            last_run = (config_path.parent / "last-run.json").read_text(encoding="utf-8")
            self.assertIn("stopped safely", last_run)
            self.assertNotIn("PRIVATE CUSTOMER CONTENT", last_run)

    def test_remove_unloads_service_but_preserves_vault(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home, vault, helper, verified = self.fixture(root)
            (vault / "keep-me").write_text("ciphertext", encoding="utf-8")
            engine = root / "engine"
            engine.write_text("fixture", encoding="utf-8")
            engine.chmod(0o700)
            with patch("codex_migrate.vault_schedule.verify_snapshot",
                       return_value=verified), \
                    patch("codex_migrate.vault_schedule._loaded", return_value=False), \
                    patch("codex_migrate.vault_schedule._launchctl"):
                install_schedule(
                    str(home), str(vault), crypto_helper=str(helper),
                    engine_command=[str(engine)])
            with patch("codex_migrate.vault_schedule._loaded", return_value=True), \
                    patch("codex_migrate.vault_schedule._launchctl") as launchctl:
                self.assertEqual(remove_schedule(str(home)), {"enabled": False})
            launchctl.assert_called_once_with([
                "bootout", "gui/%d/%s" % (os.getuid(), LABEL),
            ])
            self.assertTrue((vault / "keep-me").exists())
            self.assertFalse((home / "Library/Application Support/Codex Vault/schedule.json").exists())
            self.assertFalse((home / "Library/LaunchAgents" / (LABEL + ".plist")).exists())

    def test_world_writable_configuration_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home, _, _, _ = self.fixture(root)
            config = home / "Library/Application Support/Codex Vault/schedule.json"
            config.parent.mkdir(parents=True)
            config.write_text("{}", encoding="utf-8")
            config.chmod(0o666)
            plist = home / "Library/LaunchAgents" / (LABEL + ".plist")
            plist.parent.mkdir(parents=True)
            plist.write_text("fixture", encoding="utf-8")
            with self.assertRaisesRegex(MigrationError, "unsafe permissions"):
                schedule_status(str(home))

    def test_unsafe_last_run_is_never_exposed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home, vault, helper, verified = self.fixture(root)
            engine = root / "engine"
            engine.write_text("fixture", encoding="utf-8")
            engine.chmod(0o700)
            with patch("codex_migrate.vault_schedule.verify_snapshot",
                       return_value=verified), \
                    patch("codex_migrate.vault_schedule._loaded", return_value=False), \
                    patch("codex_migrate.vault_schedule._launchctl"):
                install_schedule(
                    str(home), str(vault), crypto_helper=str(helper),
                    engine_command=[str(engine)])
            status_path = home / "Library/Application Support/Codex Vault/last-run.json"
            status_path.write_text(json.dumps({
                "status": "failed", "error": "PRIVATE CUSTOMER CONTENT",
                "failed_at": "2026-09-18T00:00:00Z",
            }), encoding="utf-8")
            status_path.chmod(0o666)
            with patch("codex_migrate.vault_schedule._loaded", return_value=True):
                result = schedule_status(str(home))
            self.assertEqual(result["last_run"], {"status": "unknown"})
            self.assertNotIn("PRIVATE CUSTOMER CONTENT", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
