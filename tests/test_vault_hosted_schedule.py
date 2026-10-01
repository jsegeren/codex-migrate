import io
import json
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import plistlib
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import URLError

from codex_migrate.cli import parser
from codex_migrate.errors import MigrationError
from codex_migrate.vault_hosted_schedule import (
    LABEL, _cost_metrics, _paths, _rotation_path, _write_run_status,
    hosted_schedule_status, install_hosted_schedule, remove_hosted_schedule,
    run_hosted_scheduled_backup,
)
from codex_migrate.vault_hosted_upload_client import HostedUploadClient
from codex_migrate.vault_hosted_recovery_client import HostedRecoveryClient
from codex_migrate.vault_hosted_connection import active_binding, connection_path
from codex_migrate.vault_schedule import prepare_update, resume_after_update


ACCOUNT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
VAULT = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
SEAT = "22222222-2222-4222-8222-222222222222"
DEVICE = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
NEW_DEVICE = "11111111-1111-4111-8111-111111111111"
SNAPSHOT = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
NEXT = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
KEY = "ffffffff-ffff-4fff-8fff-ffffffffffff"
METADATA = {"format": "codex-vault", "version": 1, "key_id": KEY,
            "created_at": "2026-09-29T00:00:00+00:00"}
BUSINESS_METADATA = {**METADATA, "storage_codec": "lzfse-v1",
                     "recovery_mode": "business-v1"}


class HostedScheduleTests(unittest.TestCase):
    def test_cost_metrics_distinguish_restaged_and_reused_content(self):
        metrics = _cost_metrics(0, published={
            "restagedPlaintextBytes": 42,
            "reusedPlaintextBytes": 123,
            "encryptedBytes": 321,
            "snapshotId": SNAPSHOT,
        })
        self.assertEqual(metrics["restaged_plaintext_bytes"], 42)
        self.assertEqual(metrics["reused_plaintext_bytes"], 123)
        self.assertEqual(metrics["remote_claimed_ciphertext_bytes"], 321)
        self.assertNotIn("snapshotId", metrics)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hosted-schedule-test-")
        self.addCleanup(self.temporary.cleanup)
        self.home = str(Path(self.temporary.name) / "home")
        Path(self.home).mkdir()
        self.upload = SimpleNamespace(_account_id=ACCOUNT, _vault_id=VAULT)
        self.recovery = SimpleNamespace(
            latest_snapshot=lambda **_kw: {"snapshotId": SNAPSHOT,
                                           "sourceCoverage": "complete"},
            prior_catalog=lambda **_kw: (SNAPSHOT, []))
        self.rotation_calls = []
        self.business_reports = []
        self.enrollment = SimpleNamespace(
            backup_clients=lambda *_args, **_kw: (self.upload, self.recovery),
            create_device=lambda **_kw: NEW_DEVICE,
            rotate_device=self._rotate,
            resolve=lambda device_id, **_kw: {"accountId": ACCOUNT,
                                               "vaultId": VAULT,
                                               "deviceId": device_id})

    def _rotate(self, old_id, new_id, account_id, vault_id, **_kw):
        self.rotation_calls.append((old_id, new_id, account_id, vault_id))
        return {"accountId": account_id, "vaultId": vault_id,
                "deviceId": new_id}

    def _patches(self):
        return (patch("codex_migrate.vault_hosted_schedule.HostedEnrollmentClient",
                      return_value=self.enrollment),
                patch("codex_migrate.vault_hosted_schedule._helper_path",
                      return_value=Path("/synthetic/helper")),
                patch("codex_migrate.vault_hosted_schedule._loaded", return_value=False),
                patch("codex_migrate.vault_hosted_schedule._launchctl"))

    def _business_patches(self):
        def rotate(old_id, new_id, account_id, seat_id, vault_id, **_kw):
            self.rotation_calls.append((old_id, new_id, account_id,
                                        seat_id, vault_id))
            return {"accountId": account_id, "seatId": seat_id,
                    "vaultId": vault_id, "deviceId": new_id}
        enrollment = SimpleNamespace(
            backup_clients=lambda *_args, **_kw: (self.upload, self.recovery),
            create_device=lambda **_kw: NEW_DEVICE,
            rotate_device=rotate,
            report_backup_check=lambda device_id, state, snapshot_id, **_kw:
                self.business_reports.append((device_id, state, snapshot_id)),
            resolve=lambda device_id, **_kw: {"accountId": ACCOUNT,
                "seatId": SEAT, "vaultId": VAULT, "deviceId": device_id,
                "accessPurpose": "worker"})
        return (patch("codex_migrate.vault_hosted_schedule.BusinessHostedEnrollmentClient",
                      return_value=enrollment),
                patch("codex_migrate.vault_hosted_schedule._helper_path",
                      return_value=Path("/synthetic/helper")),
                patch("codex_migrate.vault_hosted_schedule._loaded", return_value=False),
                patch("codex_migrate.vault_hosted_schedule._launchctl"))

    def test_business_schedule_requires_business_key_and_exact_seat(self):
        with self.assertRaisesRegex(MigrationError, "owner and key type"):
            install_hosted_schedule(self.home, DEVICE, BUSINESS_METADATA,
                                    engine_command=["/usr/bin/true"], apply=True)
        with self.assertRaisesRegex(MigrationError, "owner and key type"):
            install_hosted_schedule(self.home, DEVICE, METADATA,
                business_seat_id=SEAT, engine_command=["/usr/bin/true"],
                apply=True)
        a, b, c, d = self._business_patches()
        with a, b, c, d:
            receipt = install_hosted_schedule(self.home, DEVICE,
                BUSINESS_METADATA, business_seat_id=SEAT,
                engine_command=["/usr/bin/true"], apply=True)
        self.assertEqual(receipt["last_good_snapshot_id"], SNAPSHOT)
        config_path, _, _, plist_path = _paths(self.home)
        config = json.loads(config_path.read_text())
        self.assertEqual((config["version"], config["owner_kind"],
                          config["seat_id"]), (3, "business", SEAT))
        self.assertEqual(config["key_metadata"], BUSINESS_METADATA)
        self.assertNotIn("hvb1_", config_path.read_text() +
                         plist_path.read_text())
        self.assertFalse(hosted_schedule_status(self.home)[
            "company_recovery_verified"])
        with a, b, c, d:
            with self.assertRaisesRegex(MigrationError, "existing hosted schedule"):
                install_hosted_schedule(self.home, DEVICE, BUSINESS_METADATA,
                    business_seat_id=SEAT, engine_command=["/usr/bin/true"],
                    apply=True)

    def test_business_scheduled_run_rotates_without_changing_seat_or_vault(self):
        a, b, c, d = self._business_patches()
        with a, b, c, d:
            install_hosted_schedule(self.home, DEVICE, BUSINESS_METADATA,
                business_seat_id=SEAT, engine_command=["/usr/bin/true"],
                apply=True)
        config_path, status_path, good_path, _ = _paths(self.home)
        fake_run = SimpleNamespace(back_up_live_history=lambda *_args, **_kw: {
            "unchanged": True, "lastGoodSnapshotId": SNAPSHOT,
            "atRiskThreads": 0, "sourceCoverage": "complete"})
        with a, b, patch("codex_migrate.vault_hosted_schedule.HostedLiveBackupRun",
                         return_value=fake_run):
            self.assertEqual(run_hosted_scheduled_backup(str(config_path)), 0)
        self.assertEqual(self.rotation_calls,
                         [(DEVICE, NEW_DEVICE, ACCOUNT, SEAT, VAULT)])
        config = json.loads(config_path.read_text())
        self.assertEqual((config["version"], config["device_id"],
                          config["seat_id"]), (3, NEW_DEVICE, SEAT))
        self.assertEqual(json.loads(status_path.read_text())["status"],
                         "unchanged")
        self.assertEqual(json.loads(good_path.read_text())["snapshot_id"],
                         SNAPSHOT)
        self.assertEqual(self.business_reports,
                         [(NEW_DEVICE, "unchanged", SNAPSHOT)])

    def test_business_checkin_failure_marks_run_failed_but_keeps_last_good(self):
        a, b, c, d = self._business_patches()
        with a, b, c, d:
            install_hosted_schedule(self.home, DEVICE, BUSINESS_METADATA,
                business_seat_id=SEAT, engine_command=["/usr/bin/true"],
                apply=True)
        config_path, status_path, good_path, _ = _paths(self.home)
        fake_run = SimpleNamespace(back_up_live_history=lambda *_args, **_kw: {
            "unchanged": True, "lastGoodSnapshotId": SNAPSHOT,
            "atRiskThreads": 0, "sourceCoverage": "complete"})
        with a as business_cls, b, patch(
                "codex_migrate.vault_hosted_schedule.HostedLiveBackupRun",
                return_value=fake_run):
            business_cls.return_value.report_backup_check = Mock(
                side_effect=MigrationError("service unavailable"))
            self.assertEqual(run_hosted_scheduled_backup(str(config_path)), 1)
        self.assertEqual(json.loads(status_path.read_text())["status"], "failed")
        self.assertEqual(json.loads(good_path.read_text())["snapshot_id"], SNAPSHOT)

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

    def test_unknown_thread_risk_refuses_scheduling_but_attachments_are_separate(self):
        self.recovery.prior_catalog = lambda **_kw: (SNAPSHOT, [{"collection": "active"}])
        a, b, c, d = self._patches()
        with a, b, c, d:
            with self.assertRaisesRegex(MigrationError, "at-risk threads"):
                install_hosted_schedule(self.home, DEVICE, METADATA,
                    engine_command=["/usr/bin/true"], apply=True)
        self.recovery.prior_catalog = lambda **_kw: (SNAPSHOT, [{"collection": "attachments"}])
        self._install()

    def test_install_provider_reads_are_excluded_by_backup_and_update_locks(self):
        from codex_migrate.vault_schedule import _update_lock
        a, b, c, d = self._patches()
        with a as client, b, c, d, _update_lock(self.home):
            with self.assertRaises(MigrationError):
                install_hosted_schedule(self.home, DEVICE, METADATA,
                    engine_command=["/usr/bin/true"], apply=True)
            client.assert_not_called()

    def test_partial_first_snapshot_refuses_protected_schedule(self):
        for coverage in ("needs_attention", "unknown"):
            with self.subTest(coverage=coverage):
                self.recovery.latest_snapshot = lambda **_kw: {
                    "snapshotId": SNAPSHOT, "sourceCoverage": coverage}
                a, b, c, d = self._patches()
                with a, b, c, d:
                    with self.assertRaisesRegex(MigrationError, "source coverage"):
                        install_hosted_schedule(
                            self.home, DEVICE, METADATA,
                            engine_command=["/usr/bin/true"], apply=True)
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
        self.assertFalse(connection_path(self.home).exists())

    def test_rotation_crash_repairs_active_reference_before_cleanup(self):
        self._install()
        config_path, _, good_path, _ = _paths(self.home)
        before_good = good_path.read_bytes()
        before_reference = connection_path(self.home).read_bytes()
        fake_run = SimpleNamespace(back_up_live_history=lambda *_args, **_kw: {
            "unchanged": True, "lastGoodSnapshotId": SNAPSHOT,
            "atRiskThreads": 0, "sourceCoverage": "complete"})
        a, b, _, _ = self._patches()
        with a, b, patch("codex_migrate.vault_hosted_schedule._save_active_connection",
                        side_effect=OSError("synthetic disk failure")):
            self.assertEqual(run_hosted_scheduled_backup(str(config_path)), 1)
        self.assertEqual(json.loads(config_path.read_text())["device_id"], NEW_DEVICE)
        self.assertTrue(_rotation_path(self.home).exists())
        self.assertEqual(connection_path(self.home).read_bytes(), before_reference)
        self.assertEqual(good_path.read_bytes(), before_good)
        with a, b, patch("codex_migrate.vault_hosted_schedule.HostedLiveBackupRun",
                        return_value=fake_run):
            self.assertEqual(run_hosted_scheduled_backup(str(config_path)), 0)
        self.assertFalse(_rotation_path(self.home).exists())
        anchor = {"deviceId": DEVICE, "accountId": ACCOUNT, "vaultId": VAULT, "keyId": KEY}
        self.assertEqual(active_binding(self.home, anchor)["deviceId"], NEW_DEVICE)
        self.assertEqual(len(self.rotation_calls), 1)

    def test_stop_then_resume_keeps_rotated_device_and_original_key(self):
        self._install()
        config_path, _, _, _ = _paths(self.home)
        fake_run = SimpleNamespace(back_up_live_history=lambda *_args, **_kw: {
            "unchanged": True, "lastGoodSnapshotId": SNAPSHOT,
            "atRiskThreads": 0, "sourceCoverage": "complete"})
        a, b, c, d = self._patches()
        anchor = {"deviceId": DEVICE, "accountId": ACCOUNT, "vaultId": VAULT, "keyId": KEY}
        with a, b, c, d, patch("codex_migrate.vault_hosted_schedule.HostedLiveBackupRun",
                              return_value=fake_run):
            self.assertEqual(run_hosted_scheduled_backup(str(config_path)), 0)
            remove_hosted_schedule(self.home, expected_binding=anchor, apply=True)
            self.assertFalse(config_path.exists())
            self.assertEqual(active_binding(self.home, anchor)["deviceId"], NEW_DEVICE)
            install_hosted_schedule(self.home, DEVICE, METADATA,
                expected_binding=anchor, engine_command=["/usr/bin/true"], apply=True)
        configuration = json.loads(config_path.read_text())
        self.assertEqual(configuration["device_id"], NEW_DEVICE)
        self.assertEqual(configuration["key_metadata"], METADATA)

    def test_stop_refuses_wrong_owner_and_unfinished_rotation(self):
        self._install()
        config_path, _, _, plist_path = _paths(self.home)
        anchor = {"deviceId": DEVICE, "accountId": ACCOUNT, "vaultId": VAULT, "keyId": KEY}
        with self.assertRaises(MigrationError):
            remove_hosted_schedule(self.home, expected_binding={**anchor, "vaultId": NEXT}, apply=True)
        _rotation_path(self.home).write_text("{}")
        with self.assertRaises(MigrationError):
            remove_hosted_schedule(self.home, expected_binding=anchor, apply=True)
        self.assertTrue(config_path.exists())
        self.assertTrue(plist_path.exists())

    def test_stop_unlink_failures_preserve_identity_and_allow_retry(self):
        anchor = {"deviceId": DEVICE, "accountId": ACCOUNT, "vaultId": VAULT, "keyId": KEY}
        original_unlink = Path.unlink
        for failing_file in ("plist", "config"):
            with self.subTest(failing_file=failing_file):
                self._install()
                config_path, _, _, plist_path = _paths(self.home)
                selected = plist_path if failing_file == "plist" else config_path
                def fail_selected(path, *args, **kwargs):
                    if path == selected:
                        raise OSError("synthetic unlink failure")
                    return original_unlink(path, *args, **kwargs)
                with patch("pathlib.Path.unlink", new=fail_selected), patch(
                        "codex_migrate.vault_hosted_schedule._loaded", return_value=False):
                    with self.assertRaises(OSError):
                        remove_hosted_schedule(self.home, expected_binding=anchor, apply=True)
                self.assertTrue(config_path.exists())
                self.assertTrue(connection_path(self.home).exists())
                self.assertTrue(hosted_schedule_status(self.home, expected_binding=anchor)["can_stop"])
                with patch("codex_migrate.vault_hosted_schedule._loaded", return_value=False):
                    self.assertEqual(remove_hosted_schedule(self.home,
                        expected_binding=anchor, apply=True), {"enabled": False})
                self.assertFalse(config_path.exists())
                self.assertFalse(plist_path.exists())

    def test_unchanged_check_records_check_but_not_new_publication(self):
        self._install()
        config_path, status_path, good_path, _ = _paths(self.home)
        fake_run = SimpleNamespace(back_up_live_history=lambda *_args, **_kw: {
            "unchanged": True, "lastGoodSnapshotId": SNAPSHOT,
            "atRiskThreads": 0, "sourceCoverage": "complete"})
        a, b, _, _ = self._patches()
        with a, b, patch("codex_migrate.vault_hosted_schedule.HostedLiveBackupRun",
                         return_value=fake_run):
            self.assertEqual(run_hosted_scheduled_backup(str(config_path)), 0)
        self.assertEqual(json.loads(status_path.read_text())["status"], "unchanged")
        self.assertEqual(json.loads(good_path.read_text())["snapshot_id"], SNAPSHOT)
        self.assertEqual(self.rotation_calls,
                         [(DEVICE, NEW_DEVICE, ACCOUNT, VAULT)])
        self.assertEqual(json.loads(config_path.read_text())["device_id"], NEW_DEVICE)
        self.assertFalse(_rotation_path(self.home).exists())

        with a, b, patch("codex_migrate.vault_hosted_schedule.HostedLiveBackupRun",
                         return_value=fake_run):
            self.assertEqual(run_hosted_scheduled_backup(str(config_path)), 0)
        self.assertEqual(len(self.rotation_calls), 1)

    def test_verified_backup_reports_incomplete_saved_title_search(self):
        self._install()
        config_path, status_path, _, _ = _paths(self.home)
        fake_run = SimpleNamespace(back_up_live_history=lambda *_args, **_kw: {
            "snapshotId": NEXT, "atRiskThreads": 0,
            "sourceCoverage": "complete",
            "titleIndexUnavailable": True})
        a, b, _, _ = self._patches()
        with a, b, patch("codex_migrate.vault_hosted_schedule.HostedLiveBackupRun",
                         return_value=fake_run):
            self.assertEqual(run_hosted_scheduled_backup(str(config_path)), 0)
        self.assertEqual(json.loads(status_path.read_text())["status"], "verified")
        with patch("codex_migrate.vault_hosted_schedule._loaded", return_value=True):
            status = hosted_schedule_status(self.home)
        self.assertTrue(status["title_index_unavailable"])
        self.assertEqual(status["last_good_snapshot_id"], NEXT)

    def test_private_run_receipt_records_content_free_cost_counts(self):
        self._install()
        self.upload = HostedUploadClient(
            "http://127.0.0.1:49111", "http://127.0.0.1:49112",
            "hv1_" + "a" * 43, ACCOUNT, VAULT, allow_loopback_http=True)
        self.recovery = HostedRecoveryClient("http://127.0.0.1:49111",
            "hv1_" + "a" * 43, VAULT, allow_loopback_http=True)
        config_path, status_path, _, _ = _paths(self.home)
        fake_run = SimpleNamespace(back_up_live_history=lambda *_args, **_kw: {
            "unchanged": True, "lastGoodSnapshotId": SNAPSHOT,
            "atRiskThreads": 0, "sourceCoverage": "complete"})
        a, b, _, _ = self._patches()
        with a, b, patch("codex_migrate.vault_hosted_schedule.HostedLiveBackupRun",
                         return_value=fake_run):
            self.assertEqual(run_hosted_scheduled_backup(str(config_path)), 0)
        status = json.loads(status_path.read_text())
        self.assertGreaterEqual(status["cost_metrics"]["elapsed_ms"], 0)
        self.assertEqual(status["cost_metrics"]["upload_service_attempts"], {})
        self.assertEqual(status["cost_metrics"]["recovery_service_attempts"], {})
        self.assertEqual(status["cost_metrics"]["recovery_worker_attempts"], {"get": 0})
        self.assertEqual(status["cost_metrics"]["worker_attempts"], {
            "head": 0, "put": 0, "put_bytes": 0,
            "put_confirmed": 0, "put_confirmed_bytes": 0,
        })
        self.assertNotIn("hv1_", status_path.read_text())
        history_path = status_path.with_name("hosted-cost-history.json")
        history = json.loads(history_path.read_text())
        self.assertEqual(len(history["runs"]), 1)
        self.assertEqual(history["runs"][0]["status"], "unchanged")
        self.assertNotIn("snapshot_id", history["runs"][0])
        self.assertEqual(history_path.stat().st_mode & 0o077, 0)

    def test_failed_run_records_recovery_attempts_and_preserves_last_good(self):
        self._install()
        self.recovery = HostedRecoveryClient("http://127.0.0.1:49111",
            "hv1_" + "a" * 43, VAULT, allow_loopback_http=True)
        config_path, status_path, good_path, _ = _paths(self.home)
        good_before = good_path.read_bytes()

        def fail_run(*_args, **_kw):
            self.recovery.latest_snapshot(expected_account_id=ACCOUNT)

        a, b, _, _ = self._patches()
        with a, b, patch.object(self.recovery._opener, "open",
                side_effect=URLError("private-title-or-token")), patch(
                "codex_migrate.vault_hosted_schedule.HostedLiveBackupRun",
                return_value=SimpleNamespace(back_up_live_history=fail_run)):
            self.assertEqual(run_hosted_scheduled_backup(str(config_path)), 1)
        self.assertEqual(good_path.read_bytes(), good_before)
        status = json.loads(status_path.read_text())
        self.assertEqual(status["status"], "failed")
        self.assertEqual(status["cost_metrics"]["recovery_service_attempts"], {"latest": 1})
        self.assertEqual(status["cost_metrics"]["recovery_worker_attempts"], {"get": 0})
        history_path = status_path.with_name("hosted-cost-history.json")
        history = json.loads(history_path.read_text())
        self.assertEqual(history["runs"][-1]["cost_metrics"], status["cost_metrics"])
        for private_value in ("hv1_", "private-title-or-token", ACCOUNT, VAULT,
                              SNAPSHOT, "http://", "snapshot_id"):
            self.assertNotIn(private_value, history_path.read_text())
        self.assertEqual(history_path.stat().st_mode & 0o077, 0)

    def test_verified_and_unchanged_runs_persist_nonzero_recovery_cost_counts(self):
        self._install()
        config_path, status_path, _, _ = _paths(self.home)
        for unchanged in (False, True):
            with self.subTest(unchanged=unchanged):
                self.recovery = HostedRecoveryClient("http://127.0.0.1:49111",
                    "hv1_" + "a" * 43, VAULT, allow_loopback_http=True)
                response = io.BytesIO(json.dumps({"accountId": ACCOUNT,
                    "workerOrigin": "http://127.0.0.1:49112",
                    "latest": {"snapshotId": SNAPSHOT, "totalObjects": 3,
                               "totalBytes": 25, "sourceCoverage": "complete"}}).encode())
                response.status = 200
                response.headers = {"Content-Type": "application/json"}

                def run(*_args, **_kw):
                    self.recovery.latest_snapshot(expected_account_id=ACCOUNT)
                    return {"unchanged": unchanged, "snapshotId": SNAPSHOT,
                            "lastGoodSnapshotId": SNAPSHOT, "atRiskThreads": 0,
                            "sourceCoverage": "complete"}

                a, b, _, _ = self._patches()
                with a, b, patch.object(self.recovery._opener, "open",
                        return_value=response), patch(
                        "codex_migrate.vault_hosted_schedule.HostedLiveBackupRun",
                        return_value=SimpleNamespace(back_up_live_history=run)):
                    self.assertEqual(run_hosted_scheduled_backup(str(config_path)), 0)
                status = json.loads(status_path.read_text())
                self.assertEqual(status["status"], "unchanged" if unchanged else "verified")
                self.assertEqual(status["cost_metrics"]["recovery_service_attempts"],
                                 {"latest": 1})
                history = json.loads(status_path.with_name("hosted-cost-history.json").read_text())
                self.assertEqual(history["runs"][-1]["cost_metrics"], status["cost_metrics"])

    def test_cost_history_is_bounded_and_cannot_block_backup_status(self):
        path = Path(self.home) / "hosted-last-run.json"
        with patch("codex_migrate.vault_hosted_schedule._COST_HISTORY_LIMIT", 3):
            for index in range(5):
                sample = {"status": "verified", "checked_at": str(index),
                          "snapshot_id": SNAPSHOT,
                          "cost_metrics": {"elapsed_ms": index}}
                _write_run_status(path, sample)
            history_path = path.with_name("hosted-cost-history.json")
            history = json.loads(history_path.read_text())
            self.assertEqual([row["checked_at"] for row in history["runs"]],
                             ["2", "3", "4"])
            self.assertNotIn(SNAPSHOT, history_path.read_text())
            before = history_path.read_bytes()
            history_path.chmod(0o644)
            _write_run_status(path, {"status": "failed", "checked_at": "5",
                                     "error": "synthetic", "cost_metrics": {"elapsed_ms": 5}})
            self.assertEqual(history_path.read_bytes(), before)
            self.assertEqual(json.loads(path.read_text())["status"], "failed")

    def test_ambiguous_rotation_preserves_pending_id_and_last_good(self):
        self._install()
        config_path, status_path, good_path, _ = _paths(self.home)
        good_before = good_path.read_bytes()
        created = []
        self.enrollment.create_device = lambda **_kw: (
            created.append(NEW_DEVICE) or NEW_DEVICE)
        self.enrollment.rotate_device = lambda *_args, **_kw: (
            (_ for _ in ()).throw(MigrationError("synthetic lost acknowledgement")))
        fake_run = SimpleNamespace(back_up_live_history=lambda *_args, **_kw: {
            "unchanged": True, "lastGoodSnapshotId": SNAPSHOT,
            "atRiskThreads": 0, "sourceCoverage": "complete"})
        a, b, _, _ = self._patches()
        with a, b, patch("codex_migrate.vault_hosted_schedule.HostedLiveBackupRun",
                         return_value=fake_run):
            self.assertEqual(run_hosted_scheduled_backup(str(config_path)), 1)
        pending_path = _rotation_path(self.home)
        self.assertEqual(json.loads(pending_path.read_text()),
                         {"old_device_id": DEVICE, "new_device_id": NEW_DEVICE})
        self.assertEqual(pending_path.stat().st_mode & 0o077, 0)
        self.assertEqual(json.loads(config_path.read_text())["device_id"], DEVICE)
        self.assertEqual(good_path.read_bytes(), good_before)
        self.assertEqual(json.loads(status_path.read_text())["status"], "failed")

        self.enrollment.rotate_device = self._rotate
        with a, b, patch("codex_migrate.vault_hosted_schedule.HostedLiveBackupRun",
                         return_value=fake_run):
            self.assertEqual(run_hosted_scheduled_backup(str(config_path)), 0)
        self.assertEqual(created, [NEW_DEVICE])
        self.assertEqual(self.rotation_calls,
                         [(DEVICE, NEW_DEVICE, ACCOUNT, VAULT)])
        self.assertEqual(json.loads(config_path.read_text())["device_id"], NEW_DEVICE)
        self.assertFalse(pending_path.exists())

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
        history = status_path.with_name("hosted-cost-history.json").read_text()
        self.assertEqual(json.loads(history)["runs"][0]["status"], "failed")
        self.assertNotIn("private data", history)

    def test_new_verified_snapshot_and_ambiguous_risk_are_distinct(self):
        self._install()
        config_path, status_path, good_path, _ = _paths(self.home)
        fake_run = SimpleNamespace(back_up_live_history=lambda *_args, **_kw: {
            "snapshotId": NEXT, "atRiskThreads": 0,
            "sourceCoverage": "complete"})
        a, b, _, _ = self._patches()
        with a, b, patch("codex_migrate.vault_hosted_schedule.HostedLiveBackupRun",
                         return_value=fake_run):
            self.assertEqual(run_hosted_scheduled_backup(str(config_path)), 0)
        self.assertEqual(json.loads(status_path.read_text())["status"], "verified")
        self.assertEqual(json.loads(good_path.read_text())["snapshot_id"], NEXT)
        fake_run.back_up_live_history = lambda *_args, **_kw: {
            "snapshotId": NEXT, "sourceCoverage": "complete"}
        with a, b, patch("codex_migrate.vault_hosted_schedule.HostedLiveBackupRun",
                         return_value=fake_run):
            self.assertEqual(run_hosted_scheduled_backup(str(config_path)), 0)
        self.assertEqual(json.loads(status_path.read_text())["status"], "needs_attention")
        fake_run.back_up_live_history = lambda *_args, **_kw: {"snapshotId": NEXT}
        with a, b, patch("codex_migrate.vault_hosted_schedule.HostedLiveBackupRun",
                         return_value=fake_run):
            self.assertEqual(run_hosted_scheduled_backup(str(config_path)), 0)
        self.assertEqual(json.loads(status_path.read_text())["status"], "needs_attention")
        self.assertEqual(json.loads(good_path.read_text())["snapshot_id"], NEXT)

    def test_ambiguous_risk_cannot_advance_or_green_last_good(self):
        self._install()
        config_path, status_path, good_path, _ = _paths(self.home)
        before = good_path.read_bytes()
        for unchanged in (False, True):
            for risk in (None, False, 0.0, -1, "0", [], {}):
                with self.subTest(unchanged=unchanged, risk=risk):
                    result = {"sourceCoverage": "complete", "atRiskThreads": risk}
                    result.update({"unchanged": True, "lastGoodSnapshotId": NEXT}
                                  if unchanged else {"snapshotId": NEXT})
                    fake_run = SimpleNamespace(
                        back_up_live_history=lambda *_args, **_kw: result)
                    a, b, _, _ = self._patches()
                    with a, b, patch(
                            "codex_migrate.vault_hosted_schedule.HostedLiveBackupRun",
                            return_value=fake_run):
                        self.assertEqual(run_hosted_scheduled_backup(str(config_path)), 0)
                    self.assertEqual(good_path.read_bytes(), before)
                    self.assertEqual(json.loads(status_path.read_text())["status"],
                                     "needs_attention")
                    with patch("codex_migrate.vault_hosted_schedule._loaded", return_value=True):
                        self.assertFalse(hosted_schedule_status(self.home)["healthy"])

    def test_stale_or_unloaded_check_never_implies_background_protection(self):
        self._install()
        _, status_path, good_path, _ = _paths(self.home)
        before = good_path.read_bytes()
        now = datetime.now(timezone.utc)
        for state, age, loaded, expected in (
                ("verified", 10, True, True),
                ("unchanged", 10, True, True),
                ("verified", 3 * 3600, True, False),
                ("unchanged", 3 * 3600, True, False),
                ("verified", 10, False, False),
                ("failed", 10, True, False),
                ("running", 10, True, False),
                ("needs_attention", 10, True, False)):
            with self.subTest(state=state, age=age, loaded=loaded):
                status_path.write_text(json.dumps({
                    "status": state, "snapshot_id": SNAPSHOT,
                    "checked_at": (now - timedelta(seconds=age)).isoformat()}))
                with patch("codex_migrate.vault_hosted_schedule._loaded", return_value=loaded):
                    status = hosted_schedule_status(self.home)
                self.assertEqual(status["healthy"], expected)
                self.assertEqual(status["last_good_snapshot_id"], SNAPSHOT)
                self.assertEqual("error" in status, not expected)
                self.assertEqual(good_path.read_bytes(), before)

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
        fake_run.back_up_live_history = lambda *_args, **_kw: {
            "unchanged": True, "lastGoodSnapshotId": NEXT, "atRiskThreads": 2}
        with a, b, patch("codex_migrate.vault_hosted_schedule.HostedLiveBackupRun",
                         return_value=fake_run):
            self.assertEqual(run_hosted_scheduled_backup(str(config_path)), 0)
        self.assertEqual(json.loads(status_path.read_text())["status"], "needs_attention")
        self.assertEqual(json.loads(good_path.read_text())["snapshot_id"], SNAPSHOT)

    def test_unchanged_partial_service_claim_is_not_healthy(self):
        self._install()
        config_path, status_path, good_path, _ = _paths(self.home)
        fake_run = SimpleNamespace(back_up_live_history=lambda *_args, **_kw: {
            "unchanged": True, "lastGoodSnapshotId": NEXT,
            "atRiskThreads": 0, "sourceCoverage": "needs_attention"})
        a, b, _, _ = self._patches()
        with a, b, patch("codex_migrate.vault_hosted_schedule.HostedLiveBackupRun",
                         return_value=fake_run):
            self.assertEqual(run_hosted_scheduled_backup(str(config_path)), 0)
        self.assertEqual(json.loads(status_path.read_text())["status"], "needs_attention")
        self.assertEqual(json.loads(good_path.read_text())["snapshot_id"], SNAPSHOT)
        with patch("codex_migrate.vault_hosted_schedule._loaded", return_value=True):
            self.assertFalse(hosted_schedule_status(self.home)["healthy"])

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
            "unchanged": True, "lastGoodSnapshotId": SNAPSHOT,
            "atRiskThreads": 0, "sourceCoverage": "complete"})
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
