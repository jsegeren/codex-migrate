"""The reserved prior history must be checked before any hosted staging."""

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from codex_migrate.errors import MigrationError
from codex_migrate.vault_identity import title_index
from codex_migrate.vault_hosted_chunk_journal import HostedChunkJournal
from codex_migrate.vault_hosted_live_stage import stage_reserved_hosted_snapshot
from codex_migrate.vault_hosted_recovery_client import HostedRecoveryClient
from codex_migrate.vault_hosted_snapshot_stage import (
    _missing_unidentified_transcripts, _missing_verified_threads,
    stage_hosted_snapshot,
)
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

    def test_wiped_transcript_source_cannot_replace_prior_hosted_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            source.mkdir(mode=0o700)
            (source / ".codex").mkdir(mode=0o700)
            journal_dir = Path(temporary) / "journal"
            journal_dir.mkdir(mode=0o700)
            with HostedChunkJournal(
                    journal_dir, account_id=ACCOUNT, vault_id=VAULT,
                    reservation_id=RESERVATION, snapshot_id=SNAPSHOT,
                    key_id=KEY, base_snapshot_id=BASE) as journal, patch(
                    "codex_migrate.vault_hosted_snapshot_stage.source_fingerprint",
                    return_value=None), patch(
                    "codex_migrate.vault_hosted_snapshot_stage.stage_hosted_snapshot_tail"
                    ) as upload:
                with self.assertRaisesRegex(MigrationError,
                                            "transcript history disappeared"):
                    stage_hosted_snapshot(
                        str(source), self.metadata,
                        [{"collection": "active", "path": "lost.jsonl"}],
                        journal, object(), crypto_helper="/unused-helper",
                        apply=True)
                upload.assert_not_called()

    def test_partial_deletion_requires_review_but_archive_move_does_not(self):
        original = {"collection": "active", "path": "old.jsonl",
                    "thread_id": BASE, "identity_state": "verified"}
        other = {"collection": "active", "path": "other.jsonl",
                 "thread_id": OTHER, "identity_state": "verified"}
        self.assertTrue(_missing_verified_threads([original, other], [other]))
        self.assertFalse(_missing_verified_threads(
            [original], [{**original, "collection": "archived",
                          "path": "moved.jsonl"}]))
        self.assertFalse(_missing_verified_threads(
            [original], [{**original, "collection": "paginated",
                          "path": BASE + ".jsonl"}]))
        self.assertTrue(_missing_verified_threads(
            [original], [{**original, "identity_state": "needs_review"}]))

    def test_unidentified_transcript_deletion_and_ambiguous_move_stop(self):
        first = {"collection": "active", "path": "one.jsonl",
                 "identity_state": "unverified", "sha256": "a" * 64}
        second = {**first, "path": "two.jsonl"}
        self.assertTrue(_missing_unidentified_transcripts(
            [first, second], [second]))
        self.assertTrue(_missing_unidentified_transcripts(
            [first], [{**first, "path": "new.jsonl", "sha256": "b" * 64}]))
        self.assertFalse(_missing_unidentified_transcripts(
            [first], [{**first, "sha256": "b" * 64}]))
        self.assertFalse(_missing_unidentified_transcripts(
            [first], [{**first, "collection": "archived", "path": "new.jsonl"}]))
        self.assertTrue(_missing_unidentified_transcripts(
            [first, second], [{**first, "collection": "archived",
                              "path": "new.jsonl"}]))

    def test_partial_unidentified_wipe_does_not_publish_a_new_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            active = source / ".codex/sessions/current.jsonl"
            active.parent.mkdir(parents=True, mode=0o700)
            active.write_text(
                '{"type":"session_meta","payload":{"id":"' + OTHER + '"}}\n',
                encoding="utf-8")
            journal_dir = Path(temporary) / "journal"
            journal_dir.mkdir(mode=0o700)
            staged = SimpleNamespace(size=active.stat().st_size,
                                     sha256="a" * 64, chunks=[])
            with HostedChunkJournal(
                    journal_dir, account_id=ACCOUNT, vault_id=VAULT,
                    reservation_id=RESERVATION, snapshot_id=SNAPSHOT,
                    key_id=KEY, base_snapshot_id=BASE) as journal, patch(
                    "codex_migrate.vault_hosted_snapshot_stage.published_source_facts",
                    return_value=({}, None)), patch(
                    "codex_migrate.vault_hosted_snapshot_stage.stage_remote_aware_file_windowed",
                    return_value=staged), patch(
                    "codex_migrate.vault_hosted_snapshot_stage.stage_hosted_snapshot_tail"
                    ) as publish:
                with self.assertRaisesRegex(MigrationError,
                                            "without a verified thread ID disappeared"):
                    stage_hosted_snapshot(
                        str(source), self.metadata,
                        [{"collection": "active", "path": "lost.jsonl",
                          "sha256": "b" * 64, "identity_state": "unverified"}],
                        journal, object(), crypto_helper="/unused-helper",
                        apply=True)
                publish.assert_not_called()

    def test_partial_wipe_does_not_publish_a_new_hosted_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            active = source / ".codex/sessions/current.jsonl"
            active.parent.mkdir(parents=True, mode=0o700)
            active.write_text(
                '{"type":"session_meta","payload":{"id":"' + OTHER + '"}}\n',
                encoding="utf-8")
            journal_dir = Path(temporary) / "journal"
            journal_dir.mkdir(mode=0o700)
            staged = SimpleNamespace(size=active.stat().st_size,
                                     sha256="a" * 64, chunks=[])
            with HostedChunkJournal(
                    journal_dir, account_id=ACCOUNT, vault_id=VAULT,
                    reservation_id=RESERVATION, snapshot_id=SNAPSHOT,
                    key_id=KEY, base_snapshot_id=BASE) as journal, patch(
                    "codex_migrate.vault_hosted_snapshot_stage.published_source_facts",
                    return_value=({}, None)), patch(
                    "codex_migrate.vault_hosted_snapshot_stage.stage_remote_aware_file_windowed",
                    return_value=staged), patch(
                    "codex_migrate.vault_hosted_snapshot_stage.stage_hosted_snapshot_tail"
                    ) as publish:
                with self.assertRaisesRegex(MigrationError,
                                            "verified Codex thread disappeared"):
                    stage_hosted_snapshot(
                        str(source), self.metadata,
                        [{"collection": "active", "path": "lost.jsonl",
                          "thread_id": BASE, "identity_state": "verified"}],
                        journal, object(), crypto_helper="/unused-helper",
                        apply=True)
                publish.assert_not_called()

    def test_damaged_optional_title_index_does_not_block_intact_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            codex = source / ".codex"
            active = codex / "sessions/current.jsonl"
            active.parent.mkdir(parents=True, mode=0o700)
            original = ('{"type":"session_meta","payload":{"id":"' + OTHER + '"}}\n')
            active.write_text(original, encoding="utf-8")
            index = codex / "session_index.jsonl"
            index.write_text("{broken\n", encoding="utf-8")
            with self.assertRaises(MigrationError):
                title_index(str(source))
            journal_dir = Path(temporary) / "journal"
            journal_dir.mkdir(mode=0o700)
            staged = SimpleNamespace(size=active.stat().st_size,
                                     sha256="a" * 64, chunks=[], objects=())
            with HostedChunkJournal(
                    journal_dir, account_id=ACCOUNT, vault_id=VAULT,
                    reservation_id=RESERVATION, snapshot_id=SNAPSHOT,
                    key_id=KEY, base_snapshot_id=None) as journal, patch(
                    "codex_migrate.vault_hosted_snapshot_stage.published_source_facts",
                    return_value=({}, None)), patch(
                    "codex_migrate.vault_hosted_snapshot_stage.stage_remote_aware_file_windowed",
                    return_value=staged), patch(
                    "codex_migrate.vault_hosted_snapshot_stage.stage_hosted_snapshot_tail",
                    return_value=()) as tail, patch(
                    "codex_migrate.vault_hosted_snapshot_stage.record_source_facts"):
                result = stage_hosted_snapshot(
                    str(source), self.metadata, [], journal, object(),
                    crypto_helper="/unused-helper", apply=True)
                self.assertEqual(result.transcript_files, 1)
                self.assertEqual(tail.call_args.args[1]["files"][0]["titles"], [])
            self.assertEqual(active.read_text(encoding="utf-8"), original)
            self.assertEqual(index.read_text(encoding="utf-8"), "{broken\n")

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
            expected_snapshot_id=BASE, expected_account_id=ACCOUNT,
            include_chunks=True)
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
