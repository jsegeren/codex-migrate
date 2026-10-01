"""First backup can be exercised without enabling any real user's schedule."""

from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from codex_migrate.cli import main, parser
from codex_migrate.errors import MigrationError
from codex_migrate.vault_hosted_manual import back_up_hosted_history
from codex_migrate.vault_hosted_schedule import MAX_PRIOR_BYTES, SERVICE_ORIGIN
from codex_migrate.vault_schedule import UPDATE_GUARD_VERSION, _update_lock


ACCOUNT = "11111111-1111-4111-8111-111111111111"
DEVICE = "22222222-2222-4222-8222-222222222222"
SNAPSHOT = "33333333-3333-4333-8333-333333333333"
KEY = "44444444-4444-4444-8444-444444444444"
OTHER = "55555555-5555-4555-8555-555555555555"


class HostedManualTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        self.metadata = {"format": "codex-vault", "version": 1,
                         "key_id": KEY, "created_at": "2026-09-30T00:00:00+00:00"}
        self.path = self.home / "vault.json"
        self.write_metadata(self.metadata)
        self.helper = self.home / "helper"
        self.helper.write_text("#!/bin/sh\nexit 1\n")
        self.helper.chmod(0o700)
        self.client = Mock()
        self.upload = SimpleNamespace(_account_id=ACCOUNT)
        self.recovery = Mock()
        self.client.backup_clients.return_value = (self.upload, self.recovery)
        self.run = Mock()
        self.result = {"snapshotId": SNAPSHOT, "sourceCoverage": "complete",
                       "atRiskThreads": 0}
        self.run.back_up_live_history.return_value = self.result
        self.catalog = [{"collection": "active", "path": "synthetic.jsonl",
                         "thread_id": KEY, "at_risk": False}]
        self.recovery.prior_catalog.return_value = (SNAPSHOT, self.catalog)
        self.enrollment = self.patch("HostedEnrollmentClient", return_value=self.client)
        self.live = self.patch("HostedLiveBackupRun", return_value=self.run)

    def patch(self, name, **kwargs):
        patcher = patch("codex_migrate.vault_hosted_manual." + name, **kwargs)
        value = patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def write_metadata(self, value):
        self.path.write_text(json.dumps(value))
        self.path.chmod(0o600)

    def backup(self, **kwargs):
        return back_up_hosted_history(str(self.home), DEVICE, str(self.path),
            crypto_helper=str(self.helper), **{"apply": True, **kwargs})

    def test_first_backup_opens_exact_remote_manifest_without_enabling_schedule(self):
        result = self.backup()
        self.enrollment.assert_called_once_with(SERVICE_ORIGIN)
        self.live.assert_called_once_with(self.upload, self.recovery, str(self.home))
        self.run.back_up_live_history.assert_called_once_with(
            self.metadata, crypto_helper=str(self.helper), max_prior_bytes=MAX_PRIOR_BYTES,
            apply=True)
        self.recovery.prior_catalog.assert_called_once_with(
            key_id=KEY, crypto_helper=str(self.helper), max_bytes=MAX_PRIOR_BYTES,
            expected_snapshot_id=SNAPSHOT, expected_account_id=ACCOUNT)
        self.assertEqual(result, {"applied": True, "snapshot_id": SNAPSHOT,
            "status": "published", "source_coverage": "complete", "at_risk_threads": 0,
            "automatic_protection_verified": False})
        self.assertFalse((self.home / "Library/LaunchAgents").exists())
        self.assertFalse(list(self.home.rglob("hosted-last-good.json")))
        self.assertEqual(json.loads(self.path.read_text()), self.metadata)

    def test_unchanged_is_not_a_new_publication(self):
        self.run.back_up_live_history.return_value = {
            "unchanged": True, "lastGoodSnapshotId": SNAPSHOT,
            "sourceCoverage": "complete", "atRiskThreads": 0}
        self.assertEqual(self.backup()["status"], "unchanged")
        self.assertEqual(self.recovery.prior_catalog.call_args.kwargs[
            "expected_snapshot_id"], SNAPSHOT)

    def test_at_risk_and_unknown_versions_never_claim_protection(self):
        for coverage, risk in (("complete", 1), ("needs_attention", 1), ("unknown", 0)):
            with self.subTest(coverage=coverage, risk=risk):
                self.result.update(sourceCoverage=coverage, atRiskThreads=risk)
                self.catalog[0]["at_risk"] = bool(risk)
                result = self.backup()
                self.assertEqual(result["status"], "needs_attention")
                self.assertFalse(result["automatic_protection_verified"])

    def test_unknown_risk_on_catalog_is_not_silently_zero(self):
        self.catalog[0].pop("at_risk")
        with self.assertRaises(MigrationError):
            self.backup()

    def test_duplicate_rows_of_one_risky_thread_count_once(self):
        self.result["atRiskThreads"] = 1
        self.catalog[0]["at_risk"] = True
        self.catalog.append({**self.catalog[0], "path": "other-location.jsonl"})
        self.catalog.append({"collection": "attachments", "path": "attachment.txt"})
        self.assertEqual(self.backup()["at_risk_threads"], 1)

    def test_changed_pointer_or_wrong_key_cannot_report_success(self):
        self.recovery.prior_catalog.return_value = (OTHER, self.catalog)
        with self.assertRaises(MigrationError):
            self.backup()
        self.recovery.prior_catalog.side_effect = MigrationError("synthetic wrong key")
        with self.assertRaises(MigrationError):
            self.backup()

    def test_malformed_receipt_stops_before_remote_verification(self):
        for field, value in (("snapshotId", "bad"), ("atRiskThreads", False),
                             ("atRiskThreads", 0.0), ("atRiskThreads", -1),
                             ("atRiskThreads", None), ("sourceCoverage", "good")):
            with self.subTest(field=field, value=value):
                self.run.back_up_live_history.return_value = {**self.result, field: value}
                self.recovery.prior_catalog.reset_mock()
                with self.assertRaises(MigrationError):
                    self.backup()
                self.recovery.prior_catalog.assert_not_called()

    def test_network_failures_preserve_existing_retry_journal_and_hide_provider_text(self):
        pending = self.home / "synthetic-pending.json"
        pending.write_text('{"reservation": "same-on-retry"}')
        private = "hv1_secret https://provider.invalid/?grant=private synthetic source text"
        self.run.back_up_live_history.side_effect = RuntimeError(private)
        with self.assertRaises(MigrationError) as raised:
            self.backup()
        self.assertNotIn(private, str(raised.exception))
        self.assertEqual(pending.read_text(), '{"reservation": "same-on-retry"}')
        self.run.back_up_live_history.side_effect = None
        self.assertEqual(self.backup()["status"], "published")
        self.assertEqual(self.client.backup_clients.call_args.args, (DEVICE,))

    def test_plan_requires_no_helper_network_or_local_state(self):
        with self.assertRaisesRegex(MigrationError, "explicit confirmation"):
            self.backup(apply=False)
        self.enrollment.assert_not_called()
        self.assertFalse((self.home / "Library").exists())

    def test_invalid_device_metadata_and_business_key_stop_before_network(self):
        for value in ({**self.metadata, "version": True},
                      {**self.metadata, "recovery_mode": "business-v1"},
                      {**self.metadata, "key_id": "invalid"}):
            self.write_metadata(value)
            with self.assertRaises(MigrationError):
                self.backup()
        self.write_metadata(self.metadata)
        with self.assertRaises(MigrationError):
            back_up_hosted_history(str(self.home), "invalid", str(self.path), apply=True)
        with self.assertRaises(MigrationError):
            back_up_hosted_history(str(self.home), DEVICE, "relative/vault.json", apply=True)
        self.enrollment.assert_not_called()

    def test_linked_or_writable_metadata_is_refused(self):
        target = self.home / "linked.json"
        self.path.rename(target)
        self.path.symlink_to(target)
        with self.assertRaises(MigrationError):
            self.backup()
        self.path.unlink()
        self.write_metadata(self.metadata)
        self.path.chmod(0o666)
        with self.assertRaises(MigrationError):
            self.backup()
        self.enrollment.assert_not_called()

    def test_pending_update_and_concurrent_schedule_block_network(self):
        with patch("codex_migrate.vault_hosted_manual._pending_update", return_value={}):
            with self.assertRaisesRegex(MigrationError, "app update"):
                self.backup()
        with patch("codex_migrate.vault_hosted_manual._update_lock",
                   side_effect=MigrationError("Another backup is running")) as guard:
            with self.assertRaises(MigrationError):
                self.backup()
            guard.assert_called_once_with(str(self.home), nonblocking=True)
        self.enrollment.assert_not_called()

    def test_actual_schedule_lock_prevents_a_manual_run(self):
        with _update_lock(str(self.home)):
            with self.assertRaisesRegex(MigrationError, "using the app"):
                self.backup()
        self.enrollment.assert_not_called()
        self.assertEqual(self.backup()["status"], "published")

    def test_actual_update_marker_blocks_before_provider_or_crypto_work(self):
        with _update_lock(str(self.home)) as marker:
            marker.write_text(json.dumps({"version": UPDATE_GUARD_VERSION, "target_build": 21,
                "expires_at": "2099-01-01T00:00:00+00:00", "deferred": False}))
            marker.chmod(0o600)
        with self.assertRaisesRegex(MigrationError, "app update"):
            self.backup()
        self.enrollment.assert_not_called()
        self.live.assert_not_called()

    def test_result_never_copies_extra_engine_credentials(self):
        self.result["private"] = "synthetic-secret"
        self.assertNotIn("synthetic-secret", json.dumps(self.backup()))

    def test_cli_plan_does_not_open_key_metadata_or_provider(self):
        args = ["vault", "--source-home", "/unused", "hosted-backup",
                "--device-id", DEVICE, "--key-metadata", "/missing/vault.json"]
        parsed = parser().parse_args(args)
        self.assertFalse(parsed.apply)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main(args), 0)
        self.enrollment.assert_not_called()

    def test_cli_apply_routes_exact_arguments_and_outputs_only_safe_result(self):
        output = io.StringIO()
        with patch("codex_migrate.vault_hosted_manual.back_up_hosted_history",
                   return_value={"status": "published", "snapshot_id": SNAPSHOT}) as backup, \
                redirect_stdout(output):
            self.assertEqual(main(["vault", "--source-home", str(self.home), "hosted-backup",
                "--device-id", DEVICE, "--key-metadata", str(self.path),
                "--crypto-helper", str(self.helper), "--apply", "--json"]), 0)
        backup.assert_called_once_with(str(self.home), DEVICE, str(self.path),
                                       crypto_helper=str(self.helper), apply=True)
        self.assertEqual(json.loads(output.getvalue()),
                         {"status": "published", "snapshot_id": SNAPSHOT})
