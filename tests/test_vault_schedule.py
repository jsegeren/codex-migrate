import json
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
import os
from pathlib import Path
import plistlib
import pwd
import select
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from codex_migrate.errors import MigrationError
from codex_migrate.vault_backup import BackupResult
from codex_migrate.vault_recovery import verify_snapshot
from codex_migrate.vault_schedule import (
    LABEL,
    install_schedule,
    plan_schedule,
    prepare_update,
    remove_schedule,
    resume_after_update,
    run_scheduled_backup,
    schedule_status,
)


class VaultScheduleTests(unittest.TestCase):
    key_id = "55555555-5555-4555-8555-555555555555"

    @unittest.skipUnless(sys.platform == "darwin" and
                         os.environ.get("CODEX_MIGRATE_LAUNCHAGENT_TEST") == "yes",
                         "opt in to a real macOS LaunchAgent test")
    def test_packaged_engine_runs_through_real_launch_agent(self):
        binary = os.environ.get("CODEX_MIGRATE_TEST_ENGINE")
        if not binary:
            self.skipTest("set CODEX_MIGRATE_TEST_ENGINE to a packaged engine")
        engine = Path(binary).resolve()
        helper = engine.parents[1] / "CodexVaultCrypto"
        self.assertTrue(engine.is_file() and helper.is_file())
        service = "gui/%d/%s" % (os.getuid(), LABEL)
        if subprocess.run(["/bin/launchctl", "print", service],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            self.skipTest("the account already has a Vault backup agent")
        if (Path.home() / "Library/LaunchAgents" / (LABEL + ".plist")).exists():
            self.skipTest("the account already has a Vault backup configuration")
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("PYTHON", "DYLD_"))}
        env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
        with tempfile.TemporaryDirectory(prefix="codex-vault-launch-agent-") as temporary:
            root = Path(temporary)
            home = root / "source"
            sessions = home / ".codex/sessions"
            sessions.mkdir(parents=True)
            transcript = sessions / "fixture.jsonl"
            transcript.write_text('{"payload":{"message":{"content":"LaunchAgent fixture"}}}\n')
            vault = root / "vault"
            initial = subprocess.run(
                [str(engine), "vault", "--source-home", str(home), "backup",
                 "--destination", str(vault), "--apply", "--json"],
                env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(initial.returncode, 0, "initial packaged backup failed")
            first_snapshot = json.loads(initial.stdout)["snapshot_id"]
            key_id = json.loads((vault / "vault.json").read_text())["key_id"]
            installed = False
            dashboard = None
            kickstart = None
            try:
                install = subprocess.run(
                    [str(engine), "vault", "--source-home", str(home),
                     "schedule", "--vault", str(vault), "--crypto-helper", str(helper),
                     "--apply", "--json"],
                    env=env, capture_output=True, text=True, timeout=60)
                self.assertEqual(install.returncode, 0, "packaged schedule setup failed")
                installed = True
                plist_path = home / "Library/LaunchAgents" / (LABEL + ".plist")
                self.assertEqual(
                    plistlib.loads(plist_path.read_bytes())["EnvironmentVariables"]["HOME"],
                    pwd.getpwuid(os.getuid()).pw_dir,
                )
                status_path = home / "Library/Application Support/Codex Vault/last-run.json"
                # Run the packaged helper alongside a real, intentionally
                # longer scheduled capture. Sparkle's idle/shutdown protocol
                # must refuse replacement while the LaunchAgent is using the
                # bundled engine, then permit it once the capture finishes.
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
                                "packaged helper returned no dashboard (exit %s)" % dashboard.poll())
                parsed = urlsplit(address[len(prefix):])
                self.assertEqual(parsed.hostname, "127.0.0.1")
                token = parse_qs(parsed.fragment).get("token", [None])[0]
                self.assertTrue(token)

                def request(path, method="GET"):
                    connection = HTTPConnection("127.0.0.1", parsed.port, timeout=5)
                    try:
                        headers = {"X-Codex-Migrate-Token": token}
                        if path == "/api/update-shutdown":
                            headers["X-Codex-Migrate-Target-Build"] = "17"
                        connection.request(method, path, headers=headers)
                        response = connection.getresponse()
                        response.read()
                        return response.status
                    finally:
                        connection.close()

                self.assertEqual(request("/api/update-idle"), 200)
                fixture_line = json.dumps({
                    "payload": {"message": {"content": "scheduled backup fixture " + "x" * 65536}}
                }) + "\n"
                with transcript.open("a", encoding="utf-8") as handle:
                    for _ in range(2048):
                        handle.write(fixture_line)
                # launchctl kickstart can wait for a long-running backup to
                # exit, so keep it async while observing the live receipt.
                kickstart = subprocess.Popen(
                    ["/bin/launchctl", "kickstart", "-k", service],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if status_path.exists() and json.loads(status_path.read_text()).get("status") == "running":
                        break
                    time.sleep(0.02)
                else:
                    self.fail("the real scheduled capture was not observed running "
                              "(kickstart=%s, receipt=%s)" % (
                                  kickstart.poll(),
                                  json.loads(status_path.read_text()).get("status")
                                  if status_path.exists() else "missing"))
                self.assertEqual(request("/api/update-idle"), 409)
                self.assertEqual(request("/api/update-shutdown", "POST"), 409)
                deadline = time.monotonic() + 90
                while time.monotonic() < deadline:
                    receipt = json.loads(status_path.read_text())
                    if receipt.get("status") in ("completed", "needs_attention", "failed"):
                        break
                    time.sleep(0.1)
                self.assertEqual(receipt["status"], "completed", "scheduled capture failed")
                kickstart.wait(timeout=15)
                self.assertEqual(kickstart.returncode, 0)
                kickstart = None
                self.assertNotEqual(receipt["snapshot_id"], first_snapshot)
                self.assertEqual(
                    verify_snapshot(str(vault), crypto_helper=str(helper)).snapshot_id,
                    receipt["snapshot_id"],
                )
                self.assertTrue(schedule_status(str(home))["healthy"])
                with transcript.open(encoding="utf-8") as handle:
                    self.assertIn("LaunchAgent fixture", handle.read(100))
                self.assertEqual(request("/api/update-idle"), 200)
                self.assertEqual(request("/api/update-shutdown", "POST"), 200)
                dashboard.wait(timeout=15)
                self.assertEqual(dashboard.returncode, 0)
                dashboard.stdout.close()
                dashboard = None
                marker_path = status_path.parent / "update.json"
                self.assertTrue(marker_path.exists())
                self.assertEqual(json.loads(marker_path.read_text())["target_build"], 17)
                deferred = subprocess.run(
                    [str(engine), "vault", "--source-home", str(home),
                     "scheduled-run", "--config", str(status_path.parent / "schedule.json")],
                    env=env, capture_output=True, text=True, timeout=15)
                self.assertEqual(deferred.returncode, 0, "packaged guard did not defer backup")
                self.assertTrue(json.loads(marker_path.read_text())["deferred"])
                self.assertEqual(json.loads(status_path.read_text())["status"], "failed")
                self.assertEqual(
                    verify_snapshot(str(vault), crypto_helper=str(helper)).snapshot_id,
                    receipt["snapshot_id"],
                )
            finally:
                try:
                    if dashboard is not None:
                        dashboard.terminate()
                        dashboard.wait(timeout=15)
                        dashboard.stdout.close()
                    if kickstart is not None:
                        kickstart.terminate()
                        kickstart.wait(timeout=15)
                    if installed:
                        removed = subprocess.run(
                            [str(engine), "vault", "--source-home", str(home),
                             "schedule-remove", "--apply", "--json"],
                            env=env, capture_output=True, text=True, timeout=15)
                        try:
                            applied = removed.returncode == 0 and json.loads(removed.stdout).get("applied") is True
                        except (ValueError, AttributeError):
                            applied = False
                        if not applied:
                            remove_schedule(str(home))
                        self.assertTrue(applied, "packaged schedule removal did not apply")
                        self.assertNotEqual(
                            subprocess.run(["/bin/launchctl", "print", service],
                                           stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL).returncode,
                            0, "the disposable LaunchAgent was not unloaded",
                        )
                finally:
                    subprocess.run([str(helper), "delete-key", "--key-id", key_id],
                                   env=env, check=True, capture_output=True, timeout=15)

    def fixture(self, root: Path):
        home = root / "home"
        vault = root / "vault"
        helper = root / "CodexVaultCrypto"
        home.mkdir(mode=0o700)
        vault.mkdir(mode=0o700)
        (vault / "vault.json").write_text(json.dumps({
            "format": "codex-vault", "version": 1, "key_id": self.key_id,
            "created_at": "2026-09-23T00:00:00+00:00",
        }), encoding="utf-8")
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
            self.assertEqual(config["vault_key_id"], self.key_id)
            self.assertEqual(config["interval_seconds"], 12 * 3600)
            plist = plistlib.loads(plist_path.read_bytes())
            self.assertEqual(plist["Label"], LABEL)
            self.assertEqual(plist["StartInterval"], 12 * 3600)
            self.assertEqual(plist["EnvironmentVariables"]["HOME"],
                             pwd.getpwuid(os.getuid()).pw_dir)
            self.assertEqual(plist["ProgramArguments"], [
                str(engine), "vault", "--source-home", str(home.resolve()),
                "scheduled-run", "--config", str(config_path.resolve()),
            ])
            launchctl.assert_called_once_with([
                "bootstrap", "gui/%d" % os.getuid(), str(plist_path.resolve()),
            ])

    def test_install_refuses_when_account_home_cannot_be_resolved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home, vault, helper, verified = self.fixture(root)
            engine = root / "engine"
            engine.write_text("fixture", encoding="utf-8")
            with patch("codex_migrate.vault_schedule.verify_snapshot",
                       return_value=verified), \
                    patch("codex_migrate.vault_schedule.pwd.getpwuid",
                          side_effect=KeyError("fixture")), \
                    patch("codex_migrate.vault_schedule._loaded", return_value=False):
                with self.assertRaisesRegex(MigrationError, "account home folder"):
                    install_schedule(str(home), str(vault), crypto_helper=str(helper),
                                     engine_command=[str(engine)])
            self.assertFalse((home / "Library").exists())

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
                str(home.resolve()), str(vault.resolve()), crypto_helper=str(helper),
                require_existing_key_id=self.key_id)
            last_run = json.loads((config_path.parent / "last-run.json").read_text(
                encoding="utf-8"))
            self.assertEqual(last_run["status"], "completed")
            self.assertEqual(last_run["snapshot_id"], "safe-snapshot")
            self.assertNotIn("key_id", last_run)
            self.assertNotIn("recovery_key", last_run)

    def test_update_guard_defers_a_scheduled_run_and_catches_up_after_relaunch(self):
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
            marker_path = config_path.parent / "update.json"
            self.assertFalse(prepare_update(str(home), lambda: False, 17))
            self.assertFalse(marker_path.exists())
            self.assertTrue(prepare_update(str(home), lambda: True, 17))
            self.assertEqual(marker_path.stat().st_mode & 0o777, 0o600)
            self.assertFalse(prepare_update(str(home), lambda: True, 16))
            self.assertEqual(json.loads(marker_path.read_text())["target_build"], 17)
            with patch("codex_migrate.vault_schedule.backup") as backup:
                self.assertEqual(run_scheduled_backup(str(config_path)), 0)
            backup.assert_not_called()
            self.assertTrue(json.loads(marker_path.read_text())["deferred"])
            self.assertEqual(json.loads((config_path.parent / "last-run.json").read_text())["status"],
                             "failed")
            with patch("codex_migrate.vault_schedule._loaded", return_value=True), \
                    patch("codex_migrate.vault_schedule.subprocess.Popen") as start:
                resume_after_update(str(home), 16)
            self.assertTrue(marker_path.exists(), "the old app must not clear the update guard")
            with patch("codex_migrate.vault_schedule._loaded", return_value=True), \
                    patch("codex_migrate.vault_schedule.subprocess.Popen") as start:
                resume_after_update(str(home), 17)
            self.assertFalse(marker_path.exists())
            self.assertEqual(start.call_args.args[0], [
                "/bin/launchctl", "kickstart", "-k", "gui/%d/%s" % (os.getuid(), LABEL)])
            completed = BackupResult(
                destination=str(vault), snapshot_id="caught-up-snapshot",
                transcript_files=1, transcript_bytes=99, chunks=1,
                key_id="private-key-id", recovery_key=None,
            )
            with patch("codex_migrate.vault_schedule.backup", return_value=completed) as backup:
                self.assertEqual(run_scheduled_backup(str(config_path)), 0)
            backup.assert_called_once()
            self.assertEqual(json.loads((config_path.parent / "last-run.json").read_text())["status"],
                             "completed")

    def test_update_guard_is_not_granted_while_backup_holds_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            home.mkdir(mode=0o700)
            from codex_migrate.vault_schedule import _update_lock
            with _update_lock(str(home)):
                self.assertFalse(prepare_update(str(home), lambda: True, 17))
            self.assertTrue(prepare_update(str(home), lambda: True, 17))

    def test_expired_update_guard_cannot_disable_future_scheduled_backups(self):
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
            self.assertTrue(prepare_update(str(home), lambda: True, 17))
            marker_path = config_path.parent / "update.json"
            marker = json.loads(marker_path.read_text())
            marker["expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
            marker_path.write_text(json.dumps(marker), encoding="utf-8")
            completed = BackupResult(
                destination=str(vault), snapshot_id="after-expiry",
                transcript_files=1, transcript_bytes=99, chunks=1,
                key_id="private-key-id", recovery_key=None,
            )
            with patch("codex_migrate.vault_schedule.backup", return_value=completed) as backup:
                self.assertEqual(run_scheduled_backup(str(config_path)), 0)
            backup.assert_called_once()
            self.assertFalse(marker_path.exists())

    def test_missing_external_vault_fails_without_creating_a_replacement(self):
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
            shutil.rmtree(vault)
            with patch("codex_migrate.vault_schedule._loaded", return_value=True):
                status = schedule_status(str(home))
            self.assertFalse(status["healthy"])
            self.assertIn("missing or changed", status["error"])
            self.assertEqual(run_scheduled_backup(str(config_path)), 1)
            self.assertFalse(vault.exists())
            self.assertEqual(json.loads((config_path.parent / "last-run.json").read_text())["status"], "failed")

    def test_replaced_vault_identity_fails_without_writing_a_snapshot(self):
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
            metadata = vault / "vault.json"
            changed = json.loads(metadata.read_text())
            changed["key_id"] = "66666666-6666-4666-8666-666666666666"
            metadata.write_text(json.dumps(changed), encoding="utf-8")
            config_path = home / "Library/Application Support/Codex Vault/schedule.json"
            self.assertEqual(run_scheduled_backup(str(config_path)), 1)
            self.assertFalse((vault / "backup.lock").exists())
            self.assertEqual(json.loads((config_path.parent / "last-run.json").read_text())["status"], "failed")

    def test_legacy_schedule_requires_reenablement_and_does_not_back_up(self):
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
            legacy = json.loads(config_path.read_text())
            legacy["version"] = 1
            del legacy["vault_key_id"]
            config_path.write_text(json.dumps(legacy), encoding="utf-8")
            with patch("codex_migrate.vault_schedule._loaded", return_value=True):
                status = schedule_status(str(home))
            self.assertFalse(status["healthy"])
            self.assertEqual(status["vault"], str(vault.resolve()))
            self.assertEqual(status["interval_hours"], 24)
            self.assertIn("run a verified backup", status["error"])
            with patch("codex_migrate.vault_schedule.backup") as backup:
                self.assertEqual(run_scheduled_backup(str(config_path)), 1)
            backup.assert_not_called()

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
