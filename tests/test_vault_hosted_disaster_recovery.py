from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from codex_migrate.cli import main, parser
from codex_migrate.errors import MigrationError
from codex_migrate.vault_hosted_disaster_recovery import recover_hosted_snapshot


ACCOUNT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
VAULT = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
DEVICE = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
SNAPSHOT = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
WORKER = "https://backup-worker.example.test"


class HostedDisasterRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hosted-restore-test-")
        self.addCleanup(self.temporary.cleanup)
        self.home = str(Path(self.temporary.name) / "home")
        Path(self.home).mkdir()
        self.output = str(Path(self.temporary.name) / "restored")
        self.upload = SimpleNamespace(_account_id=ACCOUNT, _worker_origin=WORKER)
        self.pointer = (ACCOUNT, WORKER, {"snapshotId": SNAPSHOT,
                                         "totalObjects": 3, "totalBytes": 300})
        self.prepared = []

        def prepare(**kwargs):
            self.prepared.append(kwargs)
            return {"version": 1, "snapshot_id": SNAPSHOT}, object()

        self.recovery = SimpleNamespace(_latest=lambda: self.pointer,
                                        prepare=prepare)
        self.enrollment = SimpleNamespace(
            backup_clients=lambda *_args, **_kw: (self.upload, self.recovery))
        catalog = patch("codex_migrate.vault_hosted_disaster_recovery.snapshot_catalog",
                        return_value=[{"collection": "active", "thread_id": None,
                                       "path": "synthetic.jsonl", "at_risk": False}])
        self.catalog = catalog.start()
        self.addCleanup(catalog.stop)

    def _patches(self):
        return (patch("codex_migrate.vault_hosted_disaster_recovery._helper_path",
                      return_value=Path("/synthetic/helper")),
                patch("codex_migrate.vault_hosted_disaster_recovery.HostedEnrollmentClient",
                      return_value=self.enrollment),
                patch("codex_migrate.vault_hosted_disaster_recovery.download_encrypted_snapshot",
                      return_value=SimpleNamespace(
                          vault=self.output, snapshot_id=SNAPSHOT,
                          downloaded_files=3, reused_files=0,
                          encrypted_bytes_checked=300, transcript_files=1)))

    def test_explicit_recovery_binds_pointer_and_returns_verified_staging_only(self):
        helper, enrollment, download = self._patches()
        with helper, enrollment, download as receiver:
            result = recover_hosted_snapshot(
                self.home, self.output, DEVICE, max_bytes=400,
                snapshot_id=SNAPSHOT, apply=True)
        self.assertEqual(result["vault"], self.output)
        self.assertEqual(result["snapshot_id"], SNAPSHOT)
        self.assertEqual(result["transcript_files"], 1)
        self.assertFalse(result["needs_attention"])
        self.assertEqual(result["at_risk_sources"], 0)
        self.catalog.assert_called_once_with(self.output, snapshot=SNAPSHOT,
                                             crypto_helper="/synthetic/helper")
        self.assertEqual(self.prepared, [{
            "max_bytes": 400, "expected_pointer": self.pointer,
            "selected_snapshot_id": SNAPSHOT}])
        self.assertEqual(receiver.call_args.args[0:2],
                         (str(Path(self.home).resolve()), self.output))
        self.assertEqual(receiver.call_args.kwargs["max_bytes"], 400)
        self.assertFalse((Path(self.home) / ".codex").exists())

    def test_recovered_ciphertext_does_not_hide_incomplete_conversations(self):
        self.catalog.return_value = [
            {"collection": "active", "thread_id": SNAPSHOT,
             "path": "current.jsonl", "at_risk": True},
            {"collection": "paginated", "thread_id": SNAPSHOT,
             "path": SNAPSHOT + ".jsonl", "at_risk": True},
            {"collection": "attachments", "thread_id": None,
             "path": "pasted-text.txt", "at_risk": False},
        ]
        helper, enrollment, download = self._patches()
        with helper, enrollment, download:
            result = recover_hosted_snapshot(
                self.home, self.output, DEVICE, max_bytes=400, apply=True)
        self.assertTrue(result["needs_attention"])
        self.assertEqual(result["at_risk_sources"], 2)

    def test_plan_and_bad_limit_do_not_open_credentials(self):
        with patch("codex_migrate.vault_hosted_disaster_recovery.HostedEnrollmentClient") as client:
            with self.assertRaisesRegex(MigrationError, "explicit confirmation"):
                recover_hosted_snapshot(self.home, self.output, DEVICE, max_bytes=400)
            with self.assertRaisesRegex(MigrationError, "size limit"):
                recover_hosted_snapshot(self.home, self.output, DEVICE,
                                        max_bytes=0, apply=True)
            client.assert_not_called()

    def test_pointer_or_worker_substitution_refuses_download(self):
        self.pointer = (DEVICE, WORKER, self.pointer[2])
        helper, enrollment, download = self._patches()
        with helper, enrollment, download as receiver:
            with self.assertRaisesRegex(MigrationError, "authority changed"):
                recover_hosted_snapshot(self.home, self.output, DEVICE,
                                        max_bytes=400, apply=True)
            receiver.assert_not_called()
        self.pointer = (ACCOUNT, "https://other-worker.example.test", self.pointer[2])
        helper, enrollment, download = self._patches()
        with helper, enrollment, download as receiver:
            with self.assertRaisesRegex(MigrationError, "authority changed"):
                recover_hosted_snapshot(self.home, self.output, DEVICE,
                                        max_bytes=400, apply=True)
            receiver.assert_not_called()

    def test_hidden_cli_requires_apply_and_no_secret_argument(self):
        options = parser().parse_args([
            "vault", "--source-home", self.home, "hosted-recover",
            "--device-id", DEVICE, "--output", self.output,
            "--max-bytes", "400", "--snapshot", SNAPSHOT, "--apply"])
        self.assertEqual(options.vault_command, "hosted-recover")
        self.assertTrue(options.apply)
        self.assertEqual(options.snapshot, SNAPSHOT)

    def test_cli_distinguishes_verified_ciphertext_from_complete_history(self):
        printed = io.StringIO()
        warning = io.StringIO()
        with patch("codex_migrate.vault_hosted_disaster_recovery.recover_hosted_snapshot",
                   return_value={"vault": self.output, "needs_attention": True,
                                 "at_risk_sources": 2}), redirect_stdout(printed), \
                redirect_stderr(warning):
            self.assertEqual(main([
                "vault", "--source-home", self.home, "hosted-recover",
                "--device-id", DEVICE, "--output", self.output,
                "--max-bytes", "400", "--apply"]), 0)
        self.assertIn("Encrypted hosted snapshot verified", printed.getvalue())
        self.assertIn("2 conversation source(s) have missing or changed content",
                      warning.getvalue())


if __name__ == "__main__":
    unittest.main()
