import json
import os
from pathlib import Path
import plistlib
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from codex_migrate.cli import parser
from codex_migrate.errors import MigrationError
from codex_migrate.vault_hosted_schedule import (
    LABEL, _paths, hosted_schedule_status, install_hosted_schedule,
    remove_hosted_schedule, run_hosted_scheduled_backup,
)
from codex_migrate.vault_schedule import prepare_update, resume_after_update


ACCOUNT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
VAULT = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
DEVICE = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
SNAPSHOT = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
NEXT = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
KEY = "ffffffff-ffff-4fff-8fff-ffffffffffff"
METADATA = {"format": "codex-vault", "version": 1, "key_id": KEY,
            "created_at": "2026-09-29T00:00:00+00:00"}


class HostedScheduleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hosted-schedule-test-")
        self.addCleanup(self.temporary.cleanup)
        self.home = str(Path(self.temporary.name) / "home")
        Path(self.home).mkdir()
        self.upload = SimpleNamespace(_account_id=ACCOUNT, _vault_id=VAULT)
        self.recovery = SimpleNamespace(
            latest_snapshot=lambda **_kw: {"snapshotId": SNAPSHOT},
            prior_catalog=lambda **_kw: (SNAPSHOT, []))
        self.enrollment = SimpleNamespace(
            backup_clients=lambda *_args, **_kw: (self.upload, self.recovery))

    def _patches(self):
        return (patch("codex_migrate.vault_hosted_schedule.HostedEnrollmentClient",
                      return_value=self.enrollment),
                patch("codex_migrate.vault_hosted_schedule._helper_path",
                      return_value=Path("/synthetic/helper")),
                patch("codex_migrate.vault_hosted_schedule._loaded", return_value=False),
                patch("codex_migrate.vault_hosted_schedule._launchctl"))

    def _install(self):
        a, b, c, d = self._patches()
        with a, b, c, d:
            return install_hosted_schedule(
                self.home, DEVICE, METADATA, engine_command=["/usr/bin/true"],
                apply=True)

    def test_install_requires_decryptable_first_snapshot_and_no_secret_in_plist(self):
        with self.assertRaisesRegex(MigrationError, "explicit confirmation"):
            install_hosted_schedule(self.home, DEVICE, METADATA)
        receipt = self._install()
        self.assertEqual(receipt["last_good_snapshot_id"], SNAPSHOT)
        config_path, _, good_path, plist_path = _paths(self.home)
        config = json.loads(config_path.read_text())
        plist = plistlib.loads(plist_path.read_bytes())
        self.assertEqual(config["device_id"], DEVICE)
        self.assertEqual(config["key_metadata"], METADATA)
        self.assertEqual(plist["StartInterval"], 1800)
        self.assertTrue(plist["RunAtLoad"])
        self.assertEqual(plist["Label"], LABEL)
        command = plist["ProgramArguments"]
        self.assertEqual(command[0], "/usr/bin/true")
        parsed = parser().parse_args(command[1:])
        self.assertEqual(parsed.vault_command, "hosted-scheduled-run")
        self.assertEqual(parsed.config, str(config_path))
        self.assertEqual(json.loads(good_path.read_text())["snapshot_id"], SNAPSHOT)
        self.assertNotIn("workerOrigin", config_path.read_text() + plist_path.read_text())
        self.assertNotIn("hv1_", config_path.read_text() + plist_path.read_text())
        self.assertEqual(config_path.stat().st_mode & 0o077, 0)

    def test_missing_first_snapshot_refuses_schedule(self):
        self.recovery.latest_snapshot = lambda **_kw: None
        a, b, c, d = self._patches()
        with a, b, c, d:
            with self.assertRaisesRegex(MigrationError, "first hosted backup"):
                install_hosted_schedule(
                    self.home, DEVICE, METADATA, engine_command=["/usr/bin/true"],
                    apply=True)
        self.assertFalse(_paths(self.home)[0].exists())

    def test_at_risk_first_snapshot_refuses_protected_schedule(self):
        self.recovery.prior_catalog = lambda **_kw: (SNAPSHOT, [{"at_risk": True}])
        a, b, c, d = self._patches()
        with a, b, c, d:
            with self.assertRaisesRegex(MigrationError, "at-risk threads"):
                install_hosted_schedule(
                    self.home, DEVICE, METADATA, engine_command=["/usr/bin/true"],
                    apply=True)
        self.assertFalse(_paths(self.home)[0].exists())

    def test_launch_agent_failure_rolls_back_configuration_and_receipt(self):
        a, b, c, d = self._patches()
        with a, b, c, d as launchctl:
            launchctl.side_effect = MigrationError("synthetic bootstrap failure")
            with self.assertRaisesRegex(MigrationError, "bootstrap failure"):
                install_hosted_schedule(
                    self.home, DEVICE, METADATA, engine_command=["/usr/bin/true"],
                    apply=True)
        config_path, _, good_path, plist_path = _paths(self.home)
        self.assertFalse(config_path.exists())
        self.assertFalse(good_path.exists())
        self.assertFalse(plist_path.exists())

    def test_unchanged_check_records_check_but_not_new_publication(self):
        self._install()
        config_path, status_path, good_path, _ = _paths(self.home)
        fake_run = SimpleNamespace(back_up_live_history=lambda *_args, **_kw: {
            "unchanged": True, "lastGoodSnapshotId": SNAPSHOT})
        a, b, _, _ = self._patches()
        with a, b, patch("codex_migrate.vault_hosted_schedule.HostedLiveBackupRun",
                         return_value=fake_run):
            self.assertEqual(run_hosted_scheduled_backup(str(config_path)), 0)
        self.assertEqual(json.loads(status_path.read_text())["status"], "unchanged")
        self.assertEqual(json.loads(good_path.read_text())["snapshot_id"], SNAPSHOT)

    def test_failed_check_keeps_prior_verified_receipt(self):
        self._install()
        config_path, status_path, good_path, _ = _paths(self.home)
        before = good_path.read_bytes()

        def fail(*_args, **_kwargs):
            raise MigrationError("synthetic failure with private data")

        fake_run = SimpleNamespace(back_up_live_history=fail)
        a, b, _, _ = self._patches()
        with a, b, patch("codex_migrate.vault_hosted_schedule.HostedLiveBackupRun",
                         return_value=fake_run):
            self.assertEqual(run_hosted_scheduled_backup(str(config_path)), 1)
        self.assertEqual(good_path.read_bytes(), before)
        status = json.loads(status_path.read_text())
        self.assertEqual(status["status"], "failed")
        self.assertNotIn("private data", status["error"])

    def test_new_verified_snapshot_and_ambiguous_risk_are_distinct(self):
        self._install()
        config_path, status_path, good_path, _ = _paths(self.home)
        fake_run = SimpleNamespace(back_up_live_history=lambda *_args, **_kw: {
            "snapshotId": NEXT, "atRiskThreads": 0})
        a, b, _, _ = self._patches()
        with a, b, patch("codex_migrate.vault_hosted_schedule.HostedLiveBackupRun",
                         return_value=fake_run):
            self.assertEqual(run_hosted_scheduled_backup(str(config_path)), 0)
        self.assertEqual(json.loads(status_path.read_text())["status"], "verified")
        self.assertEqual(json.loads(good_path.read_text())["snapshot_id"], NEXT)
        fake_run.back_up_live_history = lambda *_args, **_kw: {"snapshotId": NEXT}
        with a, b, patch("codex_migrate.vault_hosted_schedule.HostedLiveBackupRun",
                         return_value=fake_run):
            self.assertEqual(run_hosted_scheduled_backup(str(config_path)), 0)
        self.assertEqual(json.loads(status_path.read_text())["status"], "needs_attention")
        self.assertEqual(json.loads(good_path.read_text())["snapshot_id"], NEXT)

    def test_at_risk_publication_keeps_prior_green_receipt(self):
        self._install()
        config_path, status_path, good_path, _ = _paths(self.home)
        fake_run = SimpleNamespace(back_up_live_history=lambda *_args, **_kw: {
            "snapshotId": NEXT, "atRiskThreads": 2})
        a, b, _, _ = self._patches()
        with a, b, patch("codex_migrate.vault_hosted_schedule.HostedLiveBackupRun",
                         return_value=fake_run):
            self.assertEqual(run_hosted_scheduled_backup(str(config_path)), 0)
        self.assertEqual(json.loads(status_path.read_text())["status"], "needs_attention")
        self.assertEqual(json.loads(good_path.read_text())["snapshot_id"], SNAPSHOT)

    def test_device_identity_change_refuses_backup(self):
        self._install()
        config_path, status_path, good_path, _ = _paths(self.home)
        self.upload._account_id = DEVICE
        a, b, _, _ = self._patches()
        with a, b, patch("codex_migrate.vault_hosted_schedule.HostedLiveBackupRun") as run:
            self.assertEqual(run_hosted_scheduled_backup(str(config_path)), 1)
            run.assert_not_called()
        self.assertEqual(json.loads(status_path.read_text())["status"], "failed")
        self.assertEqual(json.loads(good_path.read_text())["snapshot_id"], SNAPSHOT)

    def test_status_and_disable_preserve_last_good_receipt(self):
        self._install()
        config_path, status_path, good_path, plist_path = _paths(self.home)
        with patch("codex_migrate.vault_hosted_schedule._loaded", return_value=True):
            status = hosted_schedule_status(self.home)
        self.assertTrue(status["enabled"])
        self.assertFalse(status["healthy"])
        self.assertEqual(status["last_good_snapshot_id"], SNAPSHOT)
        self.assertEqual(status["status"], "awaiting_check")
        a, b, _, _ = self._patches()
        fake_run = SimpleNamespace(back_up_live_history=lambda *_args, **_kw: {
            "unchanged": True, "lastGoodSnapshotId": SNAPSHOT})
        with a, b, patch("codex_migrate.vault_hosted_schedule.HostedLiveBackupRun",
                         return_value=fake_run):
            self.assertEqual(run_hosted_scheduled_backup(str(config_path)), 0)
        with patch("codex_migrate.vault_hosted_schedule._loaded", return_value=True):
            self.assertTrue(hosted_schedule_status(self.home)["healthy"])
        self.assertTrue(status_path.exists())
        with patch("codex_migrate.vault_hosted_schedule._loaded", return_value=True), \
                patch("codex_migrate.vault_hosted_schedule._launchctl") as launchctl:
            self.assertEqual(remove_hosted_schedule(self.home, apply=True),
                             {"enabled": False})
            self.assertEqual(launchctl.call_count, 1)
        self.assertFalse(config_path.exists())
        self.assertFalse(plist_path.exists())
        self.assertTrue(good_path.exists())

    def test_reinstall_does_not_inherit_previous_schedule_health(self):
        self._install()
        config_path, status_path, _, _ = _paths(self.home)
        status_path.write_text(json.dumps({"status": "verified", "checked_at":
                                           "2026-09-29T00:00:00+00:00",
                                           "snapshot_id": SNAPSHOT}))
        self._install()
        self.assertTrue(config_path.exists())
        self.assertEqual(json.loads(status_path.read_text())["status"],
                         "awaiting_check")
        with patch("codex_migrate.vault_hosted_schedule._loaded", return_value=True):
            self.assertFalse(hosted_schedule_status(self.home)["healthy"])

    def test_app_update_restarts_deferred_hosted_check_without_local_schedule(self):
        self._install()
        config_path, status_path, _, _ = _paths(self.home)
        self.assertTrue(prepare_update(self.home, lambda: True, 17))
        self.assertEqual(run_hosted_scheduled_backup(str(config_path)), 0)
        self.assertEqual(json.loads(status_path.read_text())["status"], "failed")
        with patch("codex_migrate.vault_schedule._loaded", return_value=False), \
                patch("codex_migrate.vault_hosted_schedule._loaded", return_value=True), \
                patch("codex_migrate.vault_schedule.subprocess.Popen") as start:
            resume_after_update(self.home, 17)
        self.assertEqual(start.call_args.args[0], [
            "/bin/launchctl", "kickstart", "-k",
            "gui/%d/%s" % (os.getuid(), LABEL)])


if __name__ == "__main__":
    unittest.main()
