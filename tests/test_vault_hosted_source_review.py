"""A source review diagnoses gaps without becoming a bypass or losing history."""

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from codex_migrate.cli import main, parser
from codex_migrate.errors import MigrationError
from codex_migrate.vault_hosted_source_review import review_hosted_source
from codex_migrate.vault_hosted_schedule import MAX_PRIOR_BYTES


ACCOUNT = "11111111-1111-4111-8111-111111111111"
DEVICE = "22222222-2222-4222-8222-222222222222"
SNAPSHOT = "33333333-3333-4333-8333-333333333333"
KEY = "44444444-4444-4444-8444-444444444444"
THREAD = "55555555-5555-4555-8555-555555555555"
OTHER = "66666666-6666-4666-8666-666666666666"
WORKER = "https://synthetic-worker.example.test"
PREFIX = "codex_migrate.vault_hosted_source_review."


class HostedSourceReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        (self.home / ".codex/sessions").mkdir(parents=True)
        self.metadata = self.home / "vault.json"
        self.metadata.write_text(json.dumps({"format": "codex-vault", "version": 1,
            "key_id": KEY, "created_at": "2026-10-03T00:00:00+00:00"}))
        self.metadata.chmod(0o600)
        self.helper = self.home / "helper"
        self.helper.write_text("#!/bin/sh\nexit 1\n")
        self.helper.chmod(0o700)
        self.upload = Mock(_account_id=ACCOUNT, _worker_origin=WORKER)
        self.recovery = Mock()
        self.pointer = (ACCOUNT, WORKER, {"snapshotId": SNAPSHOT, "sourceCoverage": "complete"})
        self.recovery._latest.return_value = self.pointer
        self.prior = []
        self.recovery.prior_catalog.side_effect = lambda **_kwargs: (SNAPSHOT, self.catalog())
        self.enrollment = Mock()
        self.enrollment.backup_clients.return_value = (self.upload, self.recovery)
        patcher = patch(PREFIX + "HostedEnrollmentClient", return_value=self.enrollment)
        patcher.start()
        self.addCleanup(patcher.stop)

    def transcript(self, name="synthetic.jsonl", thread=THREAD, messages=1, collection="sessions"):
        folder = self.home / ".codex" / collection
        folder.mkdir(exist_ok=True)
        path = folder / name
        rows = [{"type": "session_meta", "payload": {"id": thread}}] if thread else []
        rows += [{"type": "response_item", "payload": {
            "role": "user", "content": [{"text": "PRIVATE BODY sentinel"}]}}] * messages
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        return path

    def review(self):
        return review_hosted_source(str(self.home), DEVICE, str(self.metadata),
                                    crypto_helper=str(self.helper))

    def catalog(self):
        # Real native catalogs contain these file facts even when the tested
        # loss decision only needs identity/path. Keep fixtures structurally real.
        return [{"size": 1, "sha256": "a" * 64, "records": 5,
                 "user_messages": 0, "assistant_messages": 0, "titles": [], **row}
                for row in self.prior]

    def assert_no_remote_writes(self):
        self.assertEqual(self.upload.mock_calls, [])
        self.assertEqual({call[0] for call in self.recovery.mock_calls},
                         {"_latest", "prior_catalog"})
        self.assertFalse((self.home / "Library").exists())
        self.assertFalse((self.home / "vault-review.json").exists())

    def test_missing_thread_is_bound_to_authenticated_base_and_not_approved(self):
        path = self.transcript()
        content = path.read_bytes()
        self.prior = [{"collection": "active", "path": "gone.jsonl",
                       "thread_id": OTHER, "identity_state": "verified"}]
        result = self.review()
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(result["base_snapshot_id"], SNAPSHOT)
        self.assertEqual(result["missing_thread_ids"], [OTHER])
        self.assertFalse(result["applied"])
        self.assertFalse(result["rebaseline_authorized"])
        self.assertFalse(result["automatic_protection_verified"])
        self.recovery.prior_catalog.assert_called_once_with(
            key_id=KEY, crypto_helper=str(self.helper), max_bytes=MAX_PRIOR_BYTES,
            expected_snapshot_id=SNAPSHOT, expected_account_id=ACCOUNT)
        self.assertEqual(path.read_bytes(), content)
        self.assertNotIn("PRIVATE BODY", json.dumps(result))
        self.assertNotIn("sha256", json.dumps(result))
        self.assert_no_remote_writes()

    def test_rename_and_archive_move_use_id_not_title_or_path(self):
        self.transcript("new-name.jsonl", collection="archived_sessions")
        self.prior = [{"collection": "active", "path": "old-name.jsonl",
                       "thread_id": THREAD, "identity_state": "verified", "titles": ["old title"]}]
        result = self.review()
        self.assertEqual(result["missing_verified_threads"], 0)
        # The existing whole-tree guard still requires review if the entire
        # transcript source vanishes; one archive move retains that source.
        self.assertEqual(result["missing_sources"], [])
        self.assertEqual(result["status"], "no_loss_detected")
        self.assert_no_remote_writes()

    def test_unidentified_exact_byte_moves_count_copies(self):
        path = self.transcript(thread=None, collection="archived_sessions")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.prior = [{"collection": "active", "path": name,
                       "identity_state": "unverified", "sha256": digest}
                      for name in ("copy-a.jsonl", "copy-b.jsonl")]
        result = self.review()
        self.assertEqual(result["missing_unidentified_transcripts"], 1)
        self.assertEqual(result["missing_files"], [{"collection": "active", "path": "copy-b.jsonl"}])
        self.assert_no_remote_writes()

    def test_wiped_source_remains_a_gap_not_a_fresh_first_backup(self):
        self.prior = [{"collection": "active", "path": "old.jsonl",
                       "thread_id": THREAD, "identity_state": "verified"},
                      {"collection": "paginated", "path": OTHER + ".jsonl",
                       "thread_id": OTHER, "identity_state": "verified"}]
        result = self.review()
        self.assertEqual(result["source_entries"], 0)
        self.assertEqual(result["missing_verified_threads"], 2)
        self.assertEqual(result["missing_sources"], ["transcripts", "paginated"])
        self.assertEqual(result["status"], "needs_review")
        self.assert_no_remote_writes()

    def test_corrupt_transcript_is_not_treated_as_empty_and_error_is_redacted(self):
        path = self.transcript()
        path.write_text("PRIVATE BODY invalid JSON hv1_not-a-real-token")
        with self.assertRaisesRegex(MigrationError, "could not be verified") as caught:
            self.review()
        self.assertNotIn("PRIVATE BODY", str(caught.exception))
        self.assert_no_remote_writes()

    def test_same_id_conflicts_require_review_never_silent_merge(self):
        self.transcript("first.jsonl")
        self.transcript("second.jsonl", messages=2)
        self.prior = [{"collection": "active", "path": "old.jsonl",
                       "thread_id": THREAD, "identity_state": "verified"}]
        result = self.review()
        self.assertEqual(result["ambiguous_entries"], 2)
        self.assertEqual(result["missing_verified_threads"], 1)
        self.assertEqual(result["status"], "needs_review")

    def test_valid_smaller_history_reports_lost_messages(self):
        self.transcript(messages=1)
        self.prior = [{"collection": "active", "path": "synthetic.jsonl",
                       "thread_id": THREAD, "identity_state": "verified",
                       "user_messages": 3, "assistant_messages": 1}]
        result = self.review()
        self.assertEqual(result["missing_verified_threads"], 0)
        self.assertEqual(result["at_risk_thread_ids"], [THREAD])
        self.assertEqual(result["status"], "needs_review")

    def test_samples_are_bounded_without_hiding_total(self):
        self.prior = [{"collection": "active", "path": str(index) + ".jsonl",
                       "thread_id": "00000000-0000-4000-8000-%012d" % index,
                       "identity_state": "verified"} for index in range(30)]
        result = self.review()
        self.assertEqual(result["missing_verified_threads"], 30)
        self.assertEqual(len(result["missing_thread_ids"]), 25)

    def test_no_prior_is_not_a_protection_claim(self):
        self.recovery._latest.return_value = (ACCOUNT, WORKER, None)
        self.recovery.prior_catalog.return_value = (None, [])
        self.recovery.prior_catalog.side_effect = None
        result = self.review()
        self.assertEqual(result["status"], "no_prior_backup")
        self.assertIsNone(result["base_snapshot_id"])
        self.assertFalse(result["automatic_protection_verified"])

    def test_changed_pointer_or_authority_never_produces_a_review(self):
        for side_effect in ([self.pointer, (ACCOUNT, WORKER, {"snapshotId": OTHER})],
                            [(OTHER, WORKER, self.pointer[2])]):
            with self.subTest(side_effect=side_effect):
                self.recovery._latest.side_effect = side_effect
                with self.assertRaisesRegex(MigrationError, "could not be verified"):
                    self.review()
        self.assertEqual(self.upload.mock_calls, [])

    def test_prior_decryption_failure_is_not_a_first_backup(self):
        self.recovery.prior_catalog.side_effect = RuntimeError("PRIVATE BODY recovery material")
        with self.assertRaisesRegex(MigrationError, "could not be verified"):
            self.review()
        self.assertEqual(self.upload.mock_calls, [])

    def test_malformed_prior_metadata_never_becomes_an_id_or_path_sample(self):
        valid = {"collection": "active", "path": "old.jsonl", "thread_id": THREAD,
                 "identity_state": "verified"}
        mutations = [
            {"thread_id": "PRIVATE BODY sentinel"}, {"thread_id": None},
            {"thread_id": "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"},
            {"path": "PRIVATE BODY path"},
            {"path": "/private.jsonl"}, {"path": "../private.jsonl"},
            {"path": "folder//private.jsonl"}, {"path": "folder/./private.jsonl"},
            {"path": "private\\body.jsonl"}, {"path": "private\x00body.jsonl"},
            {"collection": "unknown"}, {"identity_state": "unknown"},
            {"sha256": "PRIVATE BODY hash"}, {"size": True}, {"size": -1},
            {"size": 2**63}, {"records": True}, {"records": -1},
            {"records": None}, {"user_messages": 100}, {"at_risk": "true"},
            {"titles": ["PRIVATE\x00BODY"]},
            {"collection": "paginated", "path": "wrong.jsonl"},
            {"collection": "attachments"},
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.prior = [{**valid, **mutation}]
                with self.assertRaisesRegex(MigrationError, "could not be verified") as caught:
                    self.review()
                self.assertNotIn("PRIVATE", str(caught.exception))
                self.assert_no_remote_writes()

    def test_duplicate_prior_paths_refuse_a_review(self):
        self.prior = [{"collection": "active", "path": "same.jsonl",
                       "thread_id": THREAD, "identity_state": "verified"}] * 2
        with self.assertRaisesRegex(MigrationError, "could not be verified"):
            self.review()
        self.assert_no_remote_writes()

    def test_legacy_v1_catalog_does_not_invent_verified_identity(self):
        self.prior = [{"collection": "active", "path": "old.jsonl",
                       "thread_id": None, "identity_state": None, "records": None,
                       "user_messages": None, "assistant_messages": None}]
        result = self.review()
        self.assertEqual(result["missing_verified_threads"], 0)
        self.assertEqual(result["missing_unidentified_transcripts"], 1)

    def test_source_change_during_scan_refuses_review(self):
        path = self.transcript()
        from codex_migrate.vault_identity import scan_transcript
        def change(*args):
            result = scan_transcript(*args)
            path.write_bytes(path.read_bytes() + b'{}\n')
            return result
        with patch(PREFIX + "scan_transcript", side_effect=change):
            with self.assertRaisesRegex(MigrationError, "could not be verified"):
                self.review()

    def test_missing_pasted_attachment_is_reported_without_its_body(self):
        path = self.transcript()
        row = {"type": "response_item", "payload": {"role": "user", "content": [
            {"text": "/Users/old/.codex/attachments/" + OTHER + "/pasted-text.txt"}]}}
        path.write_bytes(path.read_bytes() + (json.dumps(row) + "\n").encode())
        result = self.review()
        self.assertEqual(result["missing_attachments"], 1)
        self.assertEqual(result["missing_attachment_paths"], [OTHER + "/pasted-text.txt"])
        folder = self.home / ".codex/attachments" / OTHER
        folder.mkdir(parents=True)
        (folder / "pasted-text.txt").write_text("PRIVATE BODY attachment")
        self.assertEqual(self.review()["missing_attachments"], 0)

    def test_linked_or_unsafe_source_is_not_an_empty_review(self):
        outside = self.home / "outside.jsonl"
        outside.write_text("{}\n")
        (self.home / ".codex/sessions/linked.jsonl").symlink_to(outside)
        with self.assertRaisesRegex(MigrationError, "could not be verified"):
            self.review()

    def test_no_authentication_or_identity_files_are_read(self):
        self.transcript()
        for name in ("auth.json", "installation_id"):
            (self.home / ".codex" / name).write_text("PRIVATE auth sentinel")
            (self.home / ".codex" / name).chmod(0o000)
            self.addCleanup((self.home / ".codex" / name).chmod, 0o600)
        self.assertEqual(self.review()["source_entries"], 1)
        self.assert_no_remote_writes()

    def test_invalid_device_or_metadata_refused_before_enrollment(self):
        for device, metadata in (("bad", str(self.metadata)), (DEVICE, "relative/vault.json")):
            with self.assertRaises(MigrationError):
                review_hosted_source(str(self.home), device, metadata,
                                     crypto_helper=str(self.helper))
        self.enrollment.backup_clients.assert_not_called()

    def test_paginated_source_is_streamed_validated_and_compared_by_thread_id(self):
        database = self.home / ".codex/thread_history_1.sqlite"
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE thread_items (thread_id TEXT, turn_id TEXT, "
                "item_id TEXT, rollout_ordinal INTEGER, created_at_ms INTEGER, item_json TEXT, "
                "item_type TEXT, updated_at_ordinal INTEGER)")
            connection.execute("CREATE TABLE thread_history_projection_state (thread_id TEXT, "
                "next_rollout_byte_offset INTEGER, next_rollout_ordinal INTEGER)")
            connection.execute("INSERT INTO thread_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (THREAD, "turn-1", "item-1", 1, 100,
                 json.dumps({"id": "item-1", "type": "userMessage", "text": "PRIVATE BODY"}),
                 "userMessage", 1))
        self.prior = [{"collection": "active", "path": "old.jsonl",
                       "thread_id": THREAD, "identity_state": "verified"}]
        result = self.review()
        self.assertEqual(result["source_entries"], 1)
        self.assertEqual(result["missing_verified_threads"], 0)
        self.assertEqual(result["missing_sources"], ["transcripts"])
        self.assertEqual(result["status"], "needs_review")
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE thread_items SET item_json='null'")
        with self.assertRaisesRegex(MigrationError, "could not be verified"):
            self.review()

    def test_cli_is_read_only_without_apply_option(self):
        args = ["vault", "hosted-source-review", "--device-id", DEVICE,
                "--key-metadata", str(self.metadata), "--crypto-helper", str(self.helper)]
        self.assertEqual(parser().parse_args(args).vault_command, "hosted-source-review")
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser().parse_args(args + ["--apply"])
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["vault", "--source-home", str(self.home)] + args[1:]), 0)
        self.assertIn("Read-only diagnosis", output.getvalue())
        self.assertNotIn(THREAD, output.getvalue())
        self.assert_no_remote_writes()


if __name__ == "__main__":
    unittest.main()
