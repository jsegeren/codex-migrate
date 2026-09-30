"""A quiet hosted check must neither reserve storage nor invent protection."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from codex_migrate.vault_hosted_no_change import (
    _transcript_state, unchanged_published_history,
)


ACCOUNT = "11111111-1111-4111-8111-111111111111"
VAULT = "22222222-2222-4222-8222-222222222222"
KEY = "33333333-3333-4333-8333-333333333333"
SNAPSHOT = "44444444-4444-4444-8444-444444444444"
OTHER = "55555555-5555-4555-8555-555555555555"
THREAD = "66666666-6666-4666-8666-666666666666"


class Recovery:
    def __init__(self, size):
        self.pointer = {"snapshotId": SNAPSHOT, "totalObjects": 4,
                        "totalBytes": 100, "sourceCoverage": "complete"}
        self.catalog = [{"collection": "active", "path": "thread.jsonl",
                         "size": size, "thread_id": THREAD, "titles": [],
                         "at_risk": False}]
        self.catalog_reads = 0
        self.pointer_reads = 0
        self.change_pointer_after_first = False

    def latest_snapshot(self, *, expected_account_id):
        assert expected_account_id == ACCOUNT
        self.pointer_reads += 1
        if self.change_pointer_after_first and self.pointer_reads > 1:
            return {**self.pointer, "snapshotId": OTHER}
        return self.pointer

    def prior_catalog(self, **kwargs):
        assert kwargs["expected_snapshot_id"] == SNAPSHOT
        assert kwargs["expected_account_id"] == ACCOUNT
        self.catalog_reads += 1
        return SNAPSHOT, self.catalog


class HostedNoChangeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        sessions = self.home / ".codex/sessions"
        sessions.mkdir(parents=True)
        self.transcript = sessions / "thread.jsonl"
        self.transcript.write_bytes(b"synthetic prior turn\n")
        self.recovery = Recovery(self.transcript.stat().st_size)
        self.hint = _transcript_state(str(self.home))

    def check(self):
        with patch("codex_migrate.vault_hosted_no_change.published_source_index",
                   return_value=(self.hint, None)), patch(
                "codex_migrate.vault_hosted_no_change.title_index",
                return_value={}):
            return unchanged_published_history(
                str(self.home), self.home / "runs", self.recovery,
                account_id=ACCOUNT, vault_id=VAULT, key_id=KEY,
                crypto_helper="/unused", max_prior_bytes=1000)

    def test_exact_sealed_inventory_returns_a_check_not_a_new_snapshot(self):
        self.assertEqual(self.check(), {
            "unchanged": True, "lastGoodSnapshotId": SNAPSHOT,
            "lastGoodObjectCount": 4, "sourceCoverage": "complete",
            "atRiskThreads": 0})
        self.assertEqual(self.recovery.catalog_reads, 1)
        self.assertEqual(self.recovery.pointer_reads, 2)

    def test_changed_source_skips_manifest_download_and_requires_staging(self):
        with self.transcript.open("ab") as stream:
            stream.write(b"new turn\n")
        self.assertIsNone(self.check())
        self.assertEqual(self.recovery.catalog_reads, 0)
        (self.home / ".codex/thread_history_1.sqlite").write_bytes(b"new database")
        self.assertIsNone(self.check())
        self.assertEqual(self.recovery.catalog_reads, 0)

    def test_changed_title_or_server_pointer_cannot_be_called_unchanged(self):
        self.recovery.catalog[0]["titles"] = ["old title"]
        self.assertIsNone(self.check())
        self.recovery.catalog[0]["titles"] = []
        self.recovery.pointer_reads = 0
        self.recovery.change_pointer_after_first = True
        self.assertIsNone(self.check())

    def test_attachment_change_cannot_be_called_unchanged(self):
        attachment = (self.home / ".codex/attachments" / OTHER /
                      "pasted-text.txt")
        attachment.parent.mkdir(parents=True)
        attachment.write_bytes(b"synthetic attached prompt")
        self.recovery.catalog.append({
            "collection": "attachments", "path": OTHER + "/pasted-text.txt",
            "size": attachment.stat().st_size, "thread_id": None, "titles": [],
        })
        self.hint = _transcript_state(str(self.home))
        self.assertEqual(self.check()["lastGoodSnapshotId"], SNAPSHOT)
        attachment.write_bytes(b"changed attached prompt")
        self.assertIsNone(self.check())
        attachment.unlink()
        self.assertIsNone(self.check())

    def test_unchanged_at_risk_catalog_never_becomes_clean(self):
        self.recovery.catalog[0]["at_risk"] = True
        self.assertEqual(self.check()["atRiskThreads"], 1)
        del self.recovery.catalog[0]["at_risk"]
        self.assertEqual(self.check()["atRiskThreads"], 1)

    def test_unchanged_catalog_does_not_promote_partial_service_claim(self):
        self.recovery.pointer["sourceCoverage"] = "needs_attention"
        self.assertEqual(self.check()["sourceCoverage"], "needs_attention")
