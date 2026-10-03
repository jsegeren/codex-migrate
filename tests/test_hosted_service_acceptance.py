"""Safety tests for the operator harness, not evidence of a real cloud run."""
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location(
    "hosted_service_acceptance", Path(__file__).parents[1] / "ops/hosted_service_acceptance.py")
HARNESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HARNESS)


class AcceptanceSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name).resolve()
        self.root = self.parent / "case"

    def test_fixture_exact_inventory_and_auth_sentinel(self):
        self.assertEqual(HARNESS.prepare(self.root), {"fixture_prepared": True})
        root, source = HARNESS.checked_fixture(self.root)
        self.assertEqual(root, self.root)
        case = json.loads((root / HARNESS.MARKER).read_text())["caseId"]
        self.assertEqual((source / ".codex" / HARNESS.RELATIVE).read_bytes(), HARNESS.fixture_bytes(case))
        self.assertIn(b"NEVER-BACK-UP-AUTH", (source / ".codex/auth.json").read_bytes())

    def test_prepare_refuses_existing_home_without_changes(self):
        self.root.mkdir()
        sentinel = self.root / "personal.txt"
        sentinel.write_text("do not edit")
        with self.assertRaises(ValueError):
            HARNESS.prepare(self.root)
        self.assertEqual(sentinel.read_text(), "do not edit")
        self.assertEqual(list(self.root.iterdir()), [sentinel])

    def test_modified_transcript_refused_before_network(self):
        HARNESS.prepare(self.root)
        transcript = self.root / "source-home/.codex" / HARNESS.RELATIVE
        transcript.write_text("actual customer content")
        with self.assertRaises(ValueError), patch.object(HARNESS, "HostedEnrollmentClient") as client:
            HARNESS.checked_fixture(self.root)
        client.assert_not_called()

    def test_additional_codex_files_refused(self):
        HARNESS.prepare(self.root)
        (self.root / "source-home/.codex/config.toml").write_text("personal")
        with self.assertRaises(ValueError):
            HARNESS.checked_fixture(self.root)

    def test_symlink_refused(self):
        HARNESS.prepare(self.root)
        (self.root / "source-home/.codex/link").symlink_to(self.parent)
        with self.assertRaises(ValueError):
            HARNESS.checked_fixture(self.root)

    def test_group_readable_recovery_key_refused(self):
        self.root.mkdir(mode=0o700)
        path = self.root / "recovery-key"
        path.write_text("synthetic")
        path.chmod(0o640)
        with self.assertRaises(ValueError):
            HARNESS.private_file(path)

    def test_public_origin_and_lookalike_rejected(self):
        for origin in ("https://codexbackup.segeren.com", "http://localhost:3000",
                       "https://codex-migrate-abc-joshuas-projects-d3a5c48d.vercel.app.evil.com",
                       "https://codex-migrate-abc-joshuas-projects-d3a5c48d.vercel.app/?token=x"):
            self.assertIsNone(HARNESS.PREVIEW.fullmatch(origin))
        self.assertIsNotNone(HARNESS.PREVIEW.fullmatch(
            "https://codex-migrate-abc123-joshuas-projects-d3a5c48d.vercel.app"))

    def test_receipt_does_not_clobber(self):
        path = self.parent / "receipt.json"
        HARNESS.write_new(path, b'{"original":true}')
        with self.assertRaises(FileExistsError):
            HARNESS.write_new(path, b"bad")
        self.assertEqual(json.loads(path.read_text()), {"original": True})
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def args_and_remote(self):
        HARNESS.prepare(self.root)
        metadata = self.parent / "metadata.json"
        key_id = "11111111-1111-4111-8111-111111111111"
        HARNESS.write_new(metadata, json.dumps({"format": "codex-vault", "version": 1,
            "key_id": key_id, "created_at": "2026-10-03T00:00:00+00:00"}).encode())
        args = SimpleNamespace(root=str(self.root), metadata=str(metadata), crypto_helper="synthetic-helper",
            service_origin="https://codex-migrate-abc-joshuas-projects-d3a5c48d.vercel.app",
            account_id=key_id, vault_id="22222222-2222-4222-8222-222222222222",
            device_id="33333333-3333-4333-8333-333333333333")
        case = json.loads((self.root / HARNESS.MARKER).read_text())["caseId"]
        expected = HARNESS.fixture_bytes(case)
        snapshot = "44444444-4444-4444-8444-444444444444"
        catalog = [{"collection": "active", "path": HARNESS.RELATIVE.split("sessions/", 1)[1],
            "thread_id": HARNESS.THREAD, "size": len(expected),
            "sha256": hashlib.sha256(expected).hexdigest(), "at_risk": False}]
        upload = Mock(_account_id=args.account_id, _vault_id=args.vault_id)
        upload.service_request_counts.return_value = {"post": 2}
        upload.worker_attempt_counts.return_value = {"put": 3}
        recovery = Mock()
        recovery.latest_snapshot.return_value = None
        recovery.prior_catalog.return_value = (snapshot, catalog)
        run = Mock()
        run.pending.return_value = None
        run.back_up_live_history.side_effect = [
            {"snapshotId": snapshot, "sourceCoverage": "complete", "atRiskThreads": 0},
            {"unchanged": True, "lastGoodSnapshotId": snapshot}]
        return args, upload, recovery, run, snapshot

    def test_live_state_overlap_refused_without_mkdir(self):
        for parent in (Path.home() / ".codex", Path.home() / "Library/Application Support/Codex Vault"):
            target = parent / "synthetic-test-must-not-be-created"
            with patch.object(Path, "mkdir") as mkdir, self.assertRaises(ValueError):
                HARNESS.prepare(target)
            mkdir.assert_not_called()

    def test_publish_fixture_rejection_precedes_clients(self):
        args, _, _, _, _ = self.args_and_remote()
        (self.root / "source-home/.codex/config.toml").write_text("personal")
        with patch.object(HARNESS, "clients") as clients, self.assertRaises(ValueError):
            HARNESS.publish(args)
        clients.assert_not_called()

    def test_publish_binds_authenticated_catalog(self):
        args, upload, recovery, run, _ = self.args_and_remote()
        recovery.prior_catalog.return_value[1][0]["sha256"] = "0" * 64
        with patch.object(HARNESS, "clients", return_value=(upload, recovery)), \
                patch.object(HARNESS, "HostedLiveBackupRun", return_value=run), self.assertRaises(ValueError):
            HARNESS.publish(args)
        self.assertFalse((self.root / "published.json").exists())

    def test_substitution_after_backup_blocks_receipt(self):
        args, upload, recovery, run, _ = self.args_and_remote()
        result = run.back_up_live_history.side_effect
        def substitute(*a, **kw):
            (self.root / "source-home/.codex" / HARNESS.RELATIVE).write_text("substituted")
            return next(result)
        run.back_up_live_history.side_effect = substitute
        with patch.object(HARNESS, "clients", return_value=(upload, recovery)), \
                patch.object(HARNESS, "HostedLiveBackupRun", return_value=run), self.assertRaises(ValueError):
            HARNESS.publish(args)
        self.assertFalse((self.root / "published.json").exists())

    def test_lost_local_receipt_reconciles_exact_remote_snapshot(self):
        args, upload, recovery, run, snapshot = self.args_and_remote()
        original = HARNESS.write_new
        def fail_receipt(path, data):
            if path.name == "published.json":
                raise OSError("synthetic interrupted receipt write")
            original(path, data)
        with patch.object(HARNESS, "clients", return_value=(upload, recovery)), \
                patch.object(HARNESS, "HostedLiveBackupRun", return_value=run):
            with patch.object(HARNESS, "write_new", side_effect=fail_receipt), self.assertRaises(OSError):
                HARNESS.publish(args)
            recovery.latest_snapshot.return_value = {"snapshotId": snapshot, "sourceCoverage": "complete"}
            run.back_up_live_history.side_effect = None
            run.back_up_live_history.return_value = {"unchanged": True, "lastGoodSnapshotId": snapshot}
            self.assertEqual(HARNESS.publish(args)["snapshotId"], snapshot)
        self.assertTrue((self.root / "published.json").exists())

    def test_nonempty_unowned_vault_refused(self):
        args, upload, recovery, run, snapshot = self.args_and_remote()
        recovery.latest_snapshot.return_value = {"snapshotId": snapshot, "sourceCoverage": "complete"}
        with patch.object(HARNESS, "clients", return_value=(upload, recovery)), \
                patch.object(HARNESS, "HostedLiveBackupRun", return_value=run), self.assertRaises(ValueError):
            HARNESS.publish(args)
        run.back_up_live_history.assert_not_called()

    def test_interrupted_checks_reconcile_without_a_new_snapshot(self):
        for stage in ("ack", "catalog", "unchanged"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temp:
                self.parent = Path(temp).resolve()
                self.root = self.parent / "case"
                args, upload, recovery, run, snapshot = self.args_and_remote()
                if stage == "ack":
                    run.back_up_live_history.side_effect = OSError("synthetic lost ack")
                elif stage == "catalog":
                    recovery.prior_catalog.side_effect = OSError("synthetic lost catalog")
                else:
                    run.back_up_live_history.side_effect = [
                        {"snapshotId": snapshot, "sourceCoverage": "complete", "atRiskThreads": 0},
                        OSError("synthetic lost unchanged check")]
                with patch.object(HARNESS, "clients", return_value=(upload, recovery)), \
                        patch.object(HARNESS, "HostedLiveBackupRun", return_value=run):
                    with self.assertRaises(OSError):
                        HARNESS.publish(args)
                    recovery.latest_snapshot.return_value = {"snapshotId": snapshot, "sourceCoverage": "complete"}
                    recovery.prior_catalog.side_effect = None
                    run.back_up_live_history.side_effect = None
                    run.back_up_live_history.return_value = {"unchanged": True, "lastGoodSnapshotId": snapshot}
                    self.assertEqual(HARNESS.publish(args)["snapshotId"], snapshot)

    def recovery_args(self):
        args, upload, recovery, run, snapshot = self.args_and_remote()
        with patch.object(HARNESS, "clients", return_value=(upload, recovery)), \
                patch.object(HARNESS, "HostedLiveBackupRun", return_value=run):
            publication = HARNESS.publish(args)
        receipt = self.parent / "publication.json"
        HARNESS.write_new(receipt, json.dumps(publication).encode())
        key = self.parent / "key.txt"
        HARNESS.write_new(key, b"CV1-SYNTHETIC-TEST-NOT-A-REAL-KEY")
        self.consumer = self.parent / "consumer"
        self.consumer.mkdir(mode=0o700)
        args.root = str(self.consumer)
        args.publication_receipt = str(receipt)
        args.recovery_key_file = str(key)
        recovery.prepare.return_value = ({"snapshotId": snapshot}, Mock())
        return args, upload, recovery, publication

    def test_recovery_claim_requires_exact_fixture_and_excludes_auth(self):
        args, upload, recovery, publication = self.recovery_args()
        def restore(home, vault, output, **kwargs):
            path = Path(output) / HARNESS.RELATIVE
            path.parent.mkdir(parents=True)
            Path(output).chmod(0o700)
            path.write_bytes(HARNESS.fixture_bytes(publication["caseId"]))
        with patch.object(HARNESS, "clients", return_value=(upload, recovery)), \
                patch.object(HARNESS, "import_encrypted_recovery_key") as imported, \
                patch.object(HARNESS, "download_encrypted_snapshot") as downloaded, \
                patch.object(HARNESS, "restore_snapshot", side_effect=restore):
            result = HARNESS.recover(args)
        self.assertTrue(result["exact_restored_bytes"])
        self.assertFalse(result["complete_release_acceptance"])
        imported.assert_called_once()
        downloaded.assert_called_once()

    def test_recovery_refuses_existing_output_before_network(self):
        args, _, _, _ = self.recovery_args()
        (self.consumer / "restored").mkdir()
        with patch.object(HARNESS, "clients") as clients, self.assertRaises(ValueError):
            HARNESS.recover(args)
        clients.assert_not_called()

    def test_recovery_different_bytes_do_not_create_success_receipt(self):
        args, upload, recovery, _ = self.recovery_args()
        def bad_restore(home, vault, output, **kwargs):
            path = Path(output) / HARNESS.RELATIVE
            path.parent.mkdir(parents=True)
            Path(output).chmod(0o700)
            path.write_bytes(b"corrupt or substituted")
        with patch.object(HARNESS, "clients", return_value=(upload, recovery)), \
                patch.object(HARNESS, "import_encrypted_recovery_key"), \
                patch.object(HARNESS, "download_encrypted_snapshot"), \
                patch.object(HARNESS, "restore_snapshot", side_effect=bad_restore), self.assertRaises(ValueError):
            HARNESS.recover(args)
        self.assertFalse((self.consumer / "recovered.json").exists())

    def test_attempt_is_synced_before_remote_mutation(self):
        args, upload, recovery, run, _ = self.args_and_remote()
        original = HARNESS._fsync_directory
        events = []
        def synced(path):
            events.append("sync")
            original(path)
        original_results = run.back_up_live_history.side_effect
        def remote(*a, **kw):
            self.assertIn("sync", events)
            self.assertTrue((self.root / "attempt.json").exists())
            return next(original_results)
        run.back_up_live_history.side_effect = remote
        with patch.object(HARNESS, "clients", return_value=(upload, recovery)), \
                patch.object(HARNESS, "HostedLiveBackupRun", return_value=run), \
                patch.object(HARNESS, "_fsync_directory", side_effect=synced):
            HARNESS.publish(args)

    def test_protected_symlink_alias_refused_before_mkdir(self):
        fake_home = self.parent / "login"
        fake_home.mkdir()
        actual = self.parent / "codex-data"
        actual.mkdir()
        (fake_home / ".codex").symlink_to(actual, target_is_directory=True)
        with patch.object(Path, "home", return_value=fake_home), \
                patch.object(Path, "mkdir") as mkdir, self.assertRaises(ValueError):
            HARNESS.prepare(actual / "must-not-exist")
        mkdir.assert_not_called()

    def test_receiver_retries_import_download_restore_and_receipt_failures(self):
        for stage in ("import", "download", "restore", "receipt"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temp:
                self.parent = Path(temp).resolve()
                self.root = self.parent / "case"
                args, upload, recovery, publication = self.recovery_args()
                failed = False
                def restored(home, vault, output, **kwargs):
                    nonlocal failed
                    path = Path(output) / HARNESS.RELATIVE
                    path.parent.mkdir(parents=True)
                    Path(output).chmod(0o700)
                    if stage == "restore" and not failed:
                        path.write_bytes(b"partial")
                        failed = True
                        raise OSError("synthetic partial restore")
                    path.write_bytes(HARNESS.fixture_bytes(publication["caseId"]))
                original = HARNESS.write_new
                def write(path, data):
                    nonlocal failed
                    if stage == "receipt" and path.name == "recovered.json" and not failed:
                        failed = True
                        raise OSError("synthetic lost final receipt")
                    original(path, data)
                with patch.object(HARNESS, "clients", return_value=(upload, recovery)), \
                        patch.object(HARNESS, "import_encrypted_recovery_key") as imported, \
                        patch.object(HARNESS, "download_encrypted_snapshot") as downloaded, \
                        patch.object(HARNESS, "restore_snapshot", side_effect=restored), \
                        patch.object(HARNESS, "write_new", side_effect=write):
                    if stage == "import":
                        imported.side_effect = [OSError("synthetic wrong key"), {}]
                    if stage == "download":
                        downloaded.side_effect = [OSError("synthetic interrupted download"), {}]
                    with self.assertRaises(OSError):
                        HARNESS.recover(args)
                    self.assertTrue(HARNESS.recover(args)["exact_restored_bytes"])
                if stage == "restore":
                    self.assertEqual((self.consumer / "restored" / HARNESS.RELATIVE).read_bytes(), b"partial")


if __name__ == "__main__":
    unittest.main()
