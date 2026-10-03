"""Intentional loss is one exact review, not a standing deletion permission."""

from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from codex_migrate.cli import main
from codex_migrate.errors import MigrationError
from codex_migrate.vault_hosted_live_run import HostedLiveBackupRun
from codex_migrate.vault_hosted_rebaseline import (
    _deletions, catalog_digest, load_rebaseline, prepare_rebaseline, review_consumed,
)
from codex_migrate.vault_hosted_recovery_client import HostedRecoveryClient
from codex_migrate.vault_hosted_source_review import _inventory
from codex_migrate.vault_hosted_upload_client import HostedUploadClient
from codex_migrate.vault_remote_writer import StagedRemoteFile


ACCOUNT = "11111111-1111-4111-8111-111111111111"
VAULT = "22222222-2222-4222-8222-222222222222"
DEVICE = "33333333-3333-4333-8333-333333333333"
BASE = "44444444-4444-4444-8444-444444444444"
KEY = "55555555-5555-4555-8555-555555555555"
THREAD = "66666666-6666-4666-8666-666666666666"
LOST = "77777777-7777-4777-8777-777777777777"
OTHER = "88888888-8888-4888-8888-888888888888"
SERVICE = "http://127.0.0.1:49111"
WORKER = "http://127.0.0.1:49112"


class HostedRebaselineTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve() / "home"
        self.home.mkdir(mode=0o700)
        self.metadata = {"format": "codex-vault", "version": 1, "key_id": KEY,
                         "created_at": "2026-10-03T00:00:00+00:00"}
        self.metadata_path = self.home / "vault.json"
        self.metadata_path.write_text(json.dumps(self.metadata))
        self.metadata_path.chmod(0o600)
        self.helper = self.home / "helper"
        self.helper.write_text("#!/bin/sh\nexit 1\n")
        self.helper.chmod(0o700)
        self.kept = self.transcript("kept.jsonl", THREAD)
        self.deleted = self.transcript("deleted.jsonl", LOST)
        self.prior = [{**row, "at_risk": False} for row in _inventory(str(self.home))[0]]
        self.deleted.unlink()
        self.upload = HostedUploadClient(SERVICE, WORKER, "hv1_" + "a" * 43,
            ACCOUNT, VAULT, allow_loopback_http=True)
        self.recovery = HostedRecoveryClient(SERVICE, "hv1_" + "a" * 43,
            VAULT, allow_loopback_http=True)
        self.pointer = (ACCOUNT, WORKER, {"snapshotId": BASE, "sourceCoverage": "complete"})
        self.latest = self.patcher_object(self.recovery, "_latest", return_value=self.pointer)
        self.catalogs = {BASE: self.prior}

        def catalog(**kwargs):
            snapshot = kwargs["expected_snapshot_id"]
            result = (snapshot, self.catalogs[snapshot])
            return result + (2,) if kwargs.get("include_version") else result

        self.catalog = self.patcher_object(self.recovery, "prior_catalog", side_effect=catalog)
        enrollment = Mock()
        enrollment.backup_clients.return_value = (self.upload, self.recovery)
        self.enrollment = self.patcher("vault_hosted_rebaseline.HostedEnrollmentClient", return_value=enrollment)
        self.preflight = self.patcher("vault_hosted_live_run.unchanged_published_history", return_value=None)
        self.reserve = self.patcher_object(self.upload, "reserve_with_base",
            side_effect=lambda **kwargs: (kwargs["reservation_id"], BASE))
        self.receipt = self.patcher_object(self.upload, "reservation_receipt", return_value={"state": "active"})
        self.published = self.patcher_object(self.recovery, "published_snapshot",
            side_effect=lambda snapshot, **kwargs: {"snapshotId": snapshot, "totalObjects": 0,
                "totalBytes": 1, "sourceCoverage": "complete"})
        self.manifest = None
        self.patcher("vault_hosted_snapshot_stage.published_source_facts", return_value=({}, None))
        self.patcher("vault_hosted_snapshot_stage.record_source_facts")

        def stage_file(path, *args, **kwargs):
            raw = path.read_bytes()
            return StagedRemoteFile(hashlib.sha256(raw).hexdigest(), len(raw), (), ())

        self.stage_file = self.patcher("vault_hosted_snapshot_stage.stage_remote_aware_file_windowed",
                                       side_effect=stage_file)

        def tail(metadata, manifest, *args, **kwargs):
            self.manifest = manifest
            return ()

        self.tail = self.patcher("vault_hosted_snapshot_stage.stage_hosted_snapshot_tail", side_effect=tail)

        def publish(reservation_id, stage, **kwargs):
            self.catalogs[stage.snapshot_id] = self.manifest["files"]
            return {"snapshotId": stage.snapshot_id, "verifiedObjectCount": 0,
                    "sourceCoverage": "complete", "atRiskThreads": 0}

        self.publish = self.patcher_object(self.upload, "publish_hosted_stage", side_effect=publish)
        self.run = HostedLiveBackupRun(self.upload, self.recovery, str(self.home))

    def patcher(self, name, **kwargs):
        patcher = patch("codex_migrate." + name, **kwargs)
        value = patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def patcher_object(self, obj, name, **kwargs):
        patcher = patch.object(obj, name, **kwargs)
        value = patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def transcript(self, name, thread, messages=2):
        path = self.home / ".codex/sessions" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = [{"type": "session_meta", "payload": {"id": thread}}]
        rows += [{"type": "response_item", "payload": {
            "role": "user", "content": [{"text": "PRIVATE BODY synthetic"}]}}] * messages
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        return path

    def prepare(self):
        return prepare_rebaseline(str(self.home), DEVICE, str(self.metadata_path),
                                  crypto_helper=str(self.helper), apply=True)

    def backup(self, review_id=None):
        return self.run.back_up_live_history(self.metadata, crypto_helper=str(self.helper),
            max_prior_bytes=5_000_000, deletion_review_id=review_id,
            deletion_device_id=None if review_id is None else DEVICE, apply=True)

    def test_prepare_saves_complete_private_report_without_upload(self):
        result = self.prepare()
        path = Path(result["review_file"])
        report = json.loads(path.read_text())
        self.assertEqual(report["missingThreadIds"], [LOST])
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("PRIVATE BODY", path.read_text())
        self.assertFalse(result["rebaseline_authorized"])
        self.reserve.assert_not_called()
        self.publish.assert_not_called()
        self.assertTrue(self.kept.exists())

    def test_success_preserves_old_catalog_and_consumes_single_review(self):
        original = self.kept.read_bytes()
        result = self.prepare()
        receipt = self.backup(result["review_id"])
        self.assertEqual(receipt["sourceCoverage"], "complete")
        self.assertEqual([row["thread_id"] for row in self.manifest["files"]], [THREAD])
        self.assertEqual({row["thread_id"] for row in self.catalogs[BASE]}, {THREAD, LOST})
        self.assertEqual(self.kept.read_bytes(), original)
        self.assertIsNone(self.run.pending())
        self.assertTrue(review_consumed(str(self.home), result["review_id"]))
        self.published.assert_any_call(BASE, expected_account_id=ACCOUNT, expected_worker_origin=WORKER)
        with self.assertRaisesRegex(MigrationError, "consumed"):
            self.backup(result["review_id"])
        self.assertEqual(self.reserve.call_count, 1)

    def test_changed_source_or_base_refuses_before_reservation(self):
        review = self.prepare()["review_id"]
        self.transcript("new.jsonl", OTHER)
        with self.assertRaises(MigrationError):
            self.backup(review)
        self.reserve.assert_not_called()
        (self.home / ".codex/sessions/new.jsonl").unlink()
        self.latest.return_value = (ACCOUNT, WORKER, {"snapshotId": OTHER, "sourceCoverage": "complete"})
        with self.assertRaises(MigrationError):
            self.backup(review)
        self.reserve.assert_not_called()

    def test_pending_approval_cannot_be_resumed_by_normal_backup(self):
        review = self.prepare()["review_id"]
        self.stage_file.side_effect = MigrationError("synthetic interruption")
        with self.assertRaises(MigrationError):
            self.backup(review)
        pending = self.run.pending()
        with self.assertRaisesRegex(MigrationError, "Ordinary backup cannot approve deletion"):
            self.backup()
        with self.assertRaises(MigrationError):
            self.backup(OTHER)
        self.assertEqual(self.run.pending(), pending)
        self.publish.assert_not_called()

    def test_changed_source_during_staging_refuses_publication(self):
        review = self.prepare()["review_id"]
        def altered(path, *args, **kwargs):
            self.transcript("new.jsonl", OTHER)
            raw = path.read_bytes()
            return StagedRemoteFile(hashlib.sha256(raw).hexdigest(), len(raw), (), ())
        self.stage_file.side_effect = altered
        with self.assertRaises(MigrationError):
            self.backup(review)
        self.tail.assert_not_called()
        self.publish.assert_not_called()

    def test_final_source_change_stops_even_after_manifest_staging(self):
        review = self.prepare()["review_id"]
        def altered(metadata, manifest, *args, **kwargs):
            self.manifest = manifest
            self.transcript("new.jsonl", OTHER)
            return ()
        self.tail.side_effect = altered
        with self.assertRaises(MigrationError):
            self.backup(review)
        self.publish.assert_not_called()

    def test_lost_publish_ack_uses_saved_digest_even_without_report_or_live_source(self):
        result = self.prepare()
        review = result["review_id"]
        original_publish = self.publish.side_effect
        def lost_ack(*args, **kwargs):
            original_publish(*args, **kwargs)
            raise MigrationError("synthetic lost ACK")
        self.publish.side_effect = lost_ack
        with self.assertRaises(MigrationError):
            self.backup(review)
        snapshot = self.run.pending()["snapshotId"]
        self.receipt.return_value = {"state": "published", "snapshotId": snapshot, "verifiedObjectCount": 0}
        Path(result["review_file"]).unlink()
        self.kept.unlink()
        self.assertEqual(self.backup(review)["snapshotId"], snapshot)
        self.assertIsNone(self.run.pending())
        self.assertEqual(self.reserve.call_count, 1)
        self.assertEqual(self.publish.call_count, 1)

    def test_lost_ack_wrong_content_is_not_finished_or_consumed(self):
        result = self.prepare()
        self.publish.side_effect = MigrationError("lost ACK")
        with self.assertRaises(MigrationError):
            self.backup(result["review_id"])
        snapshot = self.run.pending()["snapshotId"]
        self.catalogs[snapshot] = self.prior
        self.receipt.return_value = {"state": "published", "snapshotId": snapshot, "verifiedObjectCount": 0}
        with self.assertRaisesRegex(MigrationError, "approved content"):
            self.backup(result["review_id"])
        self.assertIsNotNone(self.run.pending())
        self.assertFalse(review_consumed(str(self.home), result["review_id"]))

    def test_abandon_consumes_approval_before_cleanup_finishes(self):
        review = self.prepare()["review_id"]
        self.stage_file.side_effect = MigrationError("synthetic interruption")
        with self.assertRaises(MigrationError):
            self.backup(review)
        with patch.object(self.upload, "abandon", return_value=None):
            self.assertEqual(self.run.abandon_pending(apply=True), "cleanup_pending")
        self.assertTrue(review_consumed(str(self.home), review))
        with self.assertRaises(MigrationError):
            self.backup(review)
        self.publish.assert_not_called()

    def test_report_tampering_is_not_permission(self):
        result = self.prepare()
        path = Path(result["review_file"])
        value = json.loads(path.read_text())
        value["missingThreadIds"] = []
        path.write_text(json.dumps(value))
        with self.assertRaises(MigrationError):
            self.backup(result["review_id"])
        self.reserve.assert_not_called()

    def test_empty_corrupt_shortened_and_ambiguous_sources_never_get_approval(self):
        original = self.kept.read_bytes()
        for bad in (b"", b"not JSON\n", original.splitlines(keepends=True)[0],
                    original + ('{"type":"session_meta","payload":{"id":"' + OTHER + '"}}\n').encode()):
            with self.subTest(bad_length=len(bad)):
                self.kept.write_bytes(bad)
                with self.assertRaises(MigrationError):
                    self.prepare()
        self.kept.unlink()
        with self.assertRaises(MigrationError):
            self.prepare()
        self.reserve.assert_not_called()

    def test_nonprivate_or_linked_review_is_refused(self):
        result = self.prepare()
        path = Path(result["review_file"])
        path.chmod(0o644)
        with self.assertRaises(MigrationError):
            load_rebaseline(str(self.home), result["review_id"])
        path.chmod(0o600)
        saved = path.with_suffix(".saved")
        path.rename(saved)
        path.symlink_to(saved)
        with self.assertRaises(MigrationError):
            load_rebaseline(str(self.home), result["review_id"])

    def test_content_digest_is_order_independent_but_domain_separated(self):
        self.assertEqual(catalog_digest(self.prior), catalog_digest(list(reversed(self.prior))))
        self.assertNotEqual(catalog_digest(self.prior), catalog_digest(self.prior, prior=True))
        changed = [{**row, "sha256": "a" * 64} for row in self.prior]
        self.assertNotEqual(catalog_digest(self.prior), catalog_digest(changed))

    def test_device_key_and_source_root_are_bound(self):
        review = self.prepare()["review_id"]
        with self.assertRaises(MigrationError):
            self.run.back_up_live_history(self.metadata, crypto_helper=str(self.helper),
                max_prior_bytes=5_000_000, deletion_review_id=review,
                deletion_device_id=OTHER, apply=True)
        self.reserve.assert_not_called()
        codex = self.home / ".codex"
        codex.rename(self.home / ".saved-codex")
        self.transcript("kept.jsonl", THREAD)
        with self.assertRaises(MigrationError):
            self.backup(review)
        self.reserve.assert_not_called()

    def test_review_is_persisted_before_lost_reservation_ack(self):
        review = self.prepare()["review_id"]
        observed = []
        def reserve(**kwargs):
            state = json.loads((self.run._directory / "run.json").read_text())
            self.assertEqual(state["deletionReview"]["reviewId"], review)
            self.assertEqual(state["phase"], "reserving")
            observed.append(kwargs["reservation_id"])
            raise MigrationError("lost reservation ACK")
        self.reserve.side_effect = reserve
        for _ in range(2):
            with self.assertRaises(MigrationError):
                self.backup(review)
        self.assertEqual(len(set(observed)), 1)
        self.publish.assert_not_called()

    def test_reserved_base_race_refuses_put_and_can_be_abandoned(self):
        review = self.prepare()["review_id"]
        self.reserve.side_effect = lambda **kwargs: (kwargs["reservation_id"], OTHER)
        with self.assertRaises(MigrationError):
            self.backup(review)
        self.stage_file.assert_not_called()
        self.publish.assert_not_called()
        with patch.object(self.upload, "abandon", return_value=None):
            self.assertEqual(self.run.abandon_pending(apply=True), "cleanup_pending")
        self.receipt.return_value = {"state": "released"}
        self.assertEqual(self.run.abandon_pending(apply=True), "released")
        self.assertIsNone(self.run.pending())
        with self.assertRaises(MigrationError):
            self.backup(review)

    def test_changed_pending_review_cannot_widen_permission(self):
        result = self.prepare()
        self.stage_file.side_effect = MigrationError("interruption")
        with self.assertRaises(MigrationError):
            self.backup(result["review_id"])
        path = Path(result["review_file"])
        value = json.loads(path.read_text())
        value["sourceDigest"] = "a" * 64
        path.write_text(json.dumps(value))
        with self.assertRaises(MigrationError):
            self.backup(result["review_id"])
        self.publish.assert_not_called()

    def test_partial_approval_fields_or_malformed_version_fail_closed(self):
        review = self.prepare()["review_id"]
        self.stage_file.side_effect = MigrationError("interruption")
        with self.assertRaises(MigrationError):
            self.backup(review)
        path = self.run._directory / "run.json"
        original = json.loads(path.read_text())
        for value in ({**original, "version": 1}, {**original, "version": True},
                      {**original, "deletionReview": {"reviewId": review}},
                      {**original, "baseSnapshotId": OTHER}):
            path.write_text(json.dumps(value))
            with self.assertRaises(MigrationError):
                self.backup(review)
        self.publish.assert_not_called()

    def test_missing_referenced_pasted_text_is_never_approvable(self):
        with self.kept.open("a") as stream:
            stream.write(json.dumps({"type": "response_item", "payload": {"role": "user",
                "content": [{"type": "input_text", "text":
                    "[Pasted text #1] /Users/example/.codex/attachments/" + OTHER + "/pasted-text.txt"}]}}) + "\n")
        with self.assertRaises(MigrationError):
            self.prepare()
        self.reserve.assert_not_called()

    def test_deleted_attachment_is_in_the_complete_report(self):
        self.prior.append({"collection": "attachments", "path": OTHER + "/pasted-text.txt",
            "size": 17, "sha256": "a" * 64, "thread_id": None, "identity_state": "unverified",
            "records": 0, "user_messages": 0, "assistant_messages": 0, "titles": [], "at_risk": False})
        self.catalog.side_effect = lambda **kwargs: (
            (kwargs["expected_snapshot_id"], self.catalogs[kwargs["expected_snapshot_id"]], 4)
            if kwargs.get("include_version") else
            (kwargs["expected_snapshot_id"], self.catalogs[kwargs["expected_snapshot_id"]]))
        result = self.prepare()
        report = json.loads(Path(result["review_file"]).read_text())
        self.assertEqual(report["missingAttachments"], [OTHER + "/pasted-text.txt"])
        self.assertEqual(result["missing_attachments"], 1)
        self.assertEqual(self.backup(result["review_id"])["sourceCoverage"], "complete")

    def test_record_shrink_on_a_moved_verified_thread_is_refused(self):
        before = {**self.prior[0], "thread_id": THREAD, "path": "old.jsonl",
                  "records": 3, "user_messages": 1, "assistant_messages": 1}
        after = {**before, "collection": "archived", "path": "new.jsonl", "records": 2}
        deleted = {**before, "thread_id": LOST, "path": "deleted.jsonl"}
        with self.assertRaises(MigrationError):
            _deletions([before, deleted], [after], [])
        with self.assertRaises(MigrationError):
            _deletions([before, deleted], [{**after, "collection": "paginated",
                                          "path": THREAD + ".jsonl"}], [])

    def test_duplicate_prior_representations_cannot_hide_a_larger_version(self):
        before = {**self.prior[0], "thread_id": THREAD, "records": 4}
        smaller = {**before, "collection": "archived", "path": "small.jsonl", "records": 3}
        after = {**before, "path": "moved.jsonl", "records": 3}
        deleted = {**before, "thread_id": LOST, "path": "deleted.jsonl"}
        with self.assertRaises(MigrationError):
            _deletions([before, smaller, deleted], [after], [])

    def test_malformed_lost_ack_catalog_never_consumes_the_review(self):
        result = self.prepare()
        self.publish.side_effect = MigrationError("lost ACK")
        with self.assertRaises(MigrationError):
            self.backup(result["review_id"])
        snapshot = self.run.pending()["snapshotId"]
        self.receipt.return_value = {"state": "published", "snapshotId": snapshot, "verifiedObjectCount": 0}
        current = _inventory(str(self.home))[0][0]
        for catalog in ([{**current, "records": True, "at_risk": False}],
                        [{**current, "path": "../unsafe.jsonl", "at_risk": False}],
                        [{**current, "at_risk": False}] * 2):
            self.catalogs[snapshot] = catalog
            with self.assertRaises(MigrationError):
                self.backup(result["review_id"])
            self.assertFalse(review_consumed(str(self.home), result["review_id"]))
        self.assertIsNotNone(self.run.pending())

    def test_report_does_not_truncate_a_large_deletion_list(self):
        prototype = self.prior[0]
        self.prior[:] = [row for row in self.prior if row["thread_id"] == THREAD]
        for index in range(30):
            self.prior.append({**prototype, "path": str(index) + ".jsonl",
                "thread_id": "00000000-0000-4000-8000-%012d" % index})
        result = self.prepare()
        value = json.loads(Path(result["review_file"]).read_text())
        self.assertEqual(len(value["missingThreadIds"]), 30)
        self.assertEqual(result["missing_verified_threads"], 30)

    def test_default_staging_still_refuses_deletion_without_review(self):
        with self.assertRaisesRegex(MigrationError, "thread disappeared"):
            self.backup()
        self.publish.assert_not_called()

    def test_non_boolean_or_missing_explicit_confirmation_is_refused(self):
        from codex_migrate.vault_hosted_manual import back_up_hosted_history
        for changes in ({"deletion_review_id": OTHER},
                        {"confirm_intentional_deletions": True},
                        {"deletion_review_id": OTHER, "confirm_intentional_deletions": 1}):
            with self.assertRaises(MigrationError):
                back_up_hosted_history(str(self.home), DEVICE, str(self.metadata_path),
                                       crypto_helper=str(self.helper), apply=True, **changes)
        self.reserve.assert_not_called()

    def test_cli_planning_and_missing_confirmation_do_not_upload(self):
        with patch("codex_migrate.vault_hosted_manual.back_up_hosted_history") as backup, redirect_stdout(io.StringIO()):
            self.assertEqual(main(["vault", "hosted-confirm-deletions", "--device-id", DEVICE,
                "--key-metadata", str(self.metadata_path), "--review-id", OTHER]), 0)
            backup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
