"""The reserved prior history must be checked before any hosted staging."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from codex_migrate.errors import MigrationError
from codex_migrate.vault_hosted_chunk_journal import HostedChunkJournal
from codex_migrate.vault_hosted_live_stage import stage_reserved_hosted_snapshot
from codex_migrate.vault_hosted_recovery_client import HostedRecoveryClient
from codex_migrate.vault_hosted_upload_client import HostedUploadClient


ACCOUNT = "11111111-1111-4111-8111-111111111111"
VAULT = "22222222-2222-4222-8222-222222222222"
RESERVATION = "33333333-3333-4333-8333-333333333333"
SNAPSHOT = "44444444-4444-4444-8444-444444444444"
KEY = "55555555-5555-4555-8555-555555555555"
BASE = "66666666-6666-4666-8666-666666666666"
OTHER = "77777777-7777-4777-8777-777777777777"
TOKEN = "hv1_" + "a" * 43
SERVICE = "http://127.0.0.1:49111"


class HostedLiveStageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name) / "journal"
        self.directory.mkdir(mode=0o700)
        self.upload = HostedUploadClient(
            SERVICE, "http://127.0.0.1:49112", TOKEN, ACCOUNT, VAULT,
            allow_loopback_http=True)
        self.recovery = HostedRecoveryClient(
            SERVICE, TOKEN, VAULT, allow_loopback_http=True)
        self.metadata = {"format": "codex-vault", "version": 1,
                         "key_id": KEY, "created_at": "2026-09-27T00:00:00+00:00"}

    def journal(self, *, base=BASE):
        return HostedChunkJournal(
            self.directory, account_id=ACCOUNT, vault_id=VAULT,
            reservation_id=RESERVATION, snapshot_id=SNAPSHOT,
            key_id=KEY, base_snapshot_id=base)

    def stage(self, journal, **changes):
        return stage_reserved_hosted_snapshot(
            "/unused-home", self.metadata, journal, self.upload, self.recovery,
            crypto_helper="/unused-helper", max_prior_bytes=5_000_000,
            apply=True, **changes)

    def test_prior_catalog_precedes_transcript_stage_and_binds_base(self):
        catalog = [{"thread_id": "example"}]
        events = []
        with self.journal() as journal, patch.object(
                self.recovery, "prior_catalog",
                side_effect=lambda **_: (events.append("prior") or (BASE, catalog))) as prior, \
                patch("codex_migrate.vault_hosted_live_stage.stage_hosted_snapshot",
                      side_effect=lambda *_, **__: events.append("stage") or "staged") as stage:
            self.assertEqual(self.stage(journal), "staged")
        self.assertEqual(events, ["prior", "stage"])
        prior.assert_called_once_with(
            key_id=KEY, crypto_helper="/unused-helper", max_bytes=5_000_000,
            expected_snapshot_id=BASE, expected_account_id=ACCOUNT)
        self.assertEqual(stage.call_args.args[2], catalog)
        self.assertEqual(stage.call_args.args[3], journal)

    def test_first_backup_requires_authenticated_empty_history(self):
        with self.journal(base=None) as journal, patch.object(
                self.recovery, "prior_catalog", return_value=(None, [])) as prior, \
                patch("codex_migrate.vault_hosted_live_stage.stage_hosted_snapshot",
                      return_value="staged") as stage:
            self.assertEqual(self.stage(journal), "staged")
        self.assertIsNone(prior.call_args.kwargs["expected_snapshot_id"])
        self.assertEqual(stage.call_args.args[2], [])

    def test_changed_or_unavailable_prior_never_stages(self):
        with self.journal() as journal, patch.object(
                self.recovery, "prior_catalog", return_value=(OTHER, [])), \
                patch("codex_migrate.vault_hosted_live_stage.stage_hosted_snapshot") as stage:
            with self.assertRaisesRegex(MigrationError, "changed after reservation"):
                self.stage(journal)
            stage.assert_not_called()
        with self.journal() as journal, patch.object(
                self.recovery, "prior_catalog",
                side_effect=MigrationError("The hosted recovery service is unavailable.")), \
                patch("codex_migrate.vault_hosted_live_stage.stage_hosted_snapshot") as stage:
            with self.assertRaisesRegex(MigrationError, "unavailable"):
                self.stage(journal)
            stage.assert_not_called()

    def test_mismatched_client_or_unconfirmed_run_never_reads_or_stages(self):
        foreign = HostedUploadClient(
            SERVICE, "http://127.0.0.1:49112", TOKEN, OTHER, VAULT,
            allow_loopback_http=True)
        with self.journal() as journal, patch.object(
                self.recovery, "prior_catalog") as prior, patch(
                "codex_migrate.vault_hosted_live_stage.stage_hosted_snapshot") as stage:
            with self.assertRaisesRegex(MigrationError, "explicit confirmation"):
                stage_reserved_hosted_snapshot(
                    "/unused-home", self.metadata, journal, self.upload,
                    self.recovery, crypto_helper="/unused-helper",
                    max_prior_bytes=5_000_000)
            with self.assertRaisesRegex(MigrationError, "do not match"):
                stage_reserved_hosted_snapshot(
                    "/unused-home", self.metadata, journal, foreign,
                    self.recovery, crypto_helper="/unused-helper",
                    max_prior_bytes=5_000_000, apply=True)
            prior.assert_not_called()
            stage.assert_not_called()

    def test_legacy_unbound_journal_cannot_mean_empty_prior_history(self):
        with HostedChunkJournal(
                self.directory, account_id=ACCOUNT, vault_id=VAULT,
                reservation_id=RESERVATION, snapshot_id=SNAPSHOT,
                key_id=KEY) as journal, patch.object(
                self.recovery, "prior_catalog") as prior, patch(
                "codex_migrate.vault_hosted_live_stage.stage_hosted_snapshot") as stage:
            with self.assertRaisesRegex(MigrationError,
                                        "reservation base was not recorded"):
                self.stage(journal)
            prior.assert_not_called()
            stage.assert_not_called()


if __name__ == "__main__":
    unittest.main()
