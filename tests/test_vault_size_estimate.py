"""Synthetic-only checks for the operator's read-only Vault sizing tool."""

import json
import os
from pathlib import Path
import platform
import runpy
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "ops/vault-size-estimate.py"


def estimator():
    return runpy.run_path(str(SCRIPT))["estimate"]


@unittest.skipUnless(platform.system() == "Darwin", "macOS Compression framework required")
class VaultSizeEstimateTests(unittest.TestCase):
    def fixture(self, home, body):
        active = home / ".codex/sessions/2026/09/26/active.jsonl"
        archived = home / ".codex/archived_sessions/archived.jsonl"
        active.parent.mkdir(parents=True)
        archived.parent.mkdir(parents=True)
        active.write_bytes(body)
        archived.write_bytes(body)
        return active, archived

    def extra_sources(self, home):
        attachment = (home / ".codex/attachments" /
                      "55555555-5555-4555-8555-555555555555/pasted-text.txt")
        attachment.parent.mkdir(parents=True)
        attachment.write_bytes(b"PRIVATE-ATTACHMENT-ONLY-PROMPT" * 50)
        database = home / ".codex/thread_history_1.sqlite"
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE thread_items (thread_id TEXT, turn_id TEXT, "
                               "item_id TEXT, rollout_ordinal INTEGER, created_at_ms INTEGER, "
                               "item_json TEXT, item_type TEXT, updated_at_ordinal INTEGER)")
            connection.execute("CREATE TABLE thread_history_projection_state ("
                               "thread_id TEXT, next_rollout_byte_offset INTEGER, "
                               "next_rollout_ordinal INTEGER)")
            connection.execute("INSERT INTO thread_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                               ("44444444-4444-4444-8444-444444444444", "turn-1", "item-1",
                                1, 100, json.dumps({"id": "item-1", "type": "userMessage",
                                                    "text": "PRIVATE-DATABASE-ONLY-WORK"}),
                                "userMessage", 1))
        return attachment, database

    def test_deduplicates_identical_transcripts_without_writing_a_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            body = (json.dumps({"payload": {"message": {"content": "hello " * 1000}}})
                    + "\n").encode()
            active, archived = self.fixture(home, body)
            original_files = set(home.rglob("*"))
            result = estimator()(str(home))
            self.assertEqual(set(home.rglob("*")), original_files)
            self.assertEqual(result["transcripts"], 2)
            self.assertEqual(result["raw_transcript_bytes"], len(body) * 2)
            self.assertEqual(result["unique_chunks"], 1)
            self.assertEqual(result["duplicate_chunks"], 1)
            self.assertLess(result["empty_vault_object_bytes"], len(body))
            self.assertTrue(result["readable_text_estimate_complete"])
            self.assertGreater(result["readable_text_bytes"], 0)
            self.assertLess(result["readable_text_gzip_bytes"], result["readable_text_bytes"])
            self.assertEqual(active.read_bytes(), body)
            self.assertEqual(archived.read_bytes(), body)

    def test_unreadable_record_makes_text_estimate_explicitly_incomplete(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            good = b'{"payload":{"text":"valuable"}}\n'
            bad = b"not-json\n"
            self.fixture(home, good + bad)
            result = estimator()(str(home))
            self.assertEqual(result["raw_transcript_bytes"], 2 * len(good + bad))
            self.assertFalse(result["readable_text_estimate_complete"])
            self.assertEqual(result["unreadable_or_oversized_records"], 2)
            self.assertEqual(result["unreadable_or_oversized_bytes"], 2 * len(bad))

    def test_storage_only_preserves_object_sizing_without_parsing_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            self.fixture(home, b"not-json\n" * 1000)
            full = estimator()(str(home))
            storage = estimator()(str(home), storage_only=True)
            self.assertEqual(storage["empty_vault_object_bytes"],
                             full["empty_vault_object_bytes"])
            self.assertEqual(storage["unique_chunks"], full["unique_chunks"])
            self.assertEqual(storage["raw_transcript_bytes"],
                             full["raw_transcript_bytes"])
            self.assertTrue(storage["storage_only"])
            self.assertFalse(storage["readable_text_estimate_complete"])
            self.assertEqual(storage["readable_text_bytes"], 0)
            self.assertEqual(storage["readable_text_gzip_bytes"], 0)
            self.assertEqual(storage["unreadable_or_oversized_records"], 0)

    def test_full_scope_counts_attachments_and_paginated_history_without_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            self.fixture(home, b'{"payload":{"text":"synthetic transcript"}}\n')
            attachment, database = self.extra_sources(home)
            original_files = set(home.rglob("*"))
            original_db = database.read_bytes()
            result = estimator()(str(home), storage_only=True,
                                 include_extra_sources=True)
            self.assertEqual(result["attachments"], 1)
            self.assertEqual(result["raw_attachment_bytes"], attachment.stat().st_size)
            self.assertEqual(result["paginated_threads"], 1)
            self.assertGreater(result["raw_paginated_bytes"], 0)
            self.assertTrue(result["estimate_complete"])
            self.assertGreater(result["empty_vault_object_bytes"],
                               estimator()(str(home), storage_only=True)["empty_vault_object_bytes"])
            self.assertEqual(set(home.rglob("*")), original_files)
            self.assertEqual(database.read_bytes(), original_db)
            self.assertNotIn("PRIVATE", json.dumps(result))
            extras = estimator()(str(home), storage_only=True,
                                 extra_sources_only=True)
            self.assertEqual(extras["transcripts"], 0)
            self.assertEqual(extras["raw_transcript_bytes"], 0)
            self.assertEqual(extras["raw_attachment_bytes"], result["raw_attachment_bytes"])
            self.assertEqual(extras["raw_paginated_bytes"], result["raw_paginated_bytes"])
            self.assertIn("only", extras["scope"])
            with self.assertRaisesRegex(ValueError, "storage-only"):
                estimator()(str(home), include_extra_sources=True)

    def test_changed_live_database_is_reported_as_an_incomplete_estimate(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            self.fixture(home, b'{"payload":{"text":"synthetic"}}\n')
            self.extra_sources(home)
            estimate = estimator()
            states = iter(("before", "after"))
            with patch.dict(estimate.__globals__, {
                    "source_fingerprint": lambda _: next(states)}):
                result = estimate(str(home), storage_only=True,
                                  extra_sources_only=True)
            self.assertTrue(result["paginated_source_changed"])
            self.assertFalse(result["estimate_complete"])
            self.assertGreater(result["raw_paginated_bytes"], 0)

    def test_valid_final_record_without_newline_is_counted_as_readable(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            body = b'{"payload":{"text":"valuable final record"}}'
            self.fixture(home, body)
            result = estimator()(str(home))
            self.assertTrue(result["readable_text_estimate_complete"])
            self.assertEqual(result["readable_record_source_bytes"], len(body) * 2)
            self.assertEqual(result["unreadable_or_oversized_records"], 0)
            self.assertGreater(result["readable_text_bytes"], 0)

    def test_oversized_record_is_counted_without_retaining_its_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            oversized = b'{"payload":{"text":"' + b"X" * 500 + b'"}}\n'
            good = b'{"payload":{"text":"small"}}\n'
            self.fixture(home, oversized + good)
            estimate = estimator()
            estimate.__globals__["MAX_RECORD_BYTES"] = 128
            result = estimate(str(home))
            self.assertFalse(result["readable_text_estimate_complete"])
            self.assertEqual(result["unreadable_or_oversized_records"], 2)
            self.assertEqual(result["unreadable_or_oversized_bytes"], 2 * len(oversized))
            self.assertEqual(result["readable_record_source_bytes"], 2 * len(good))

    def test_recent_active_transcript_is_reported_as_omitted(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            body = b'{"payload":{"text":"valuable"}}\n'
            active, archived = self.fixture(home, body)
            os.utime(archived, (1, 1))
            result = estimator()(str(home), exclude_recent_seconds=600)
            self.assertEqual(result["transcripts"], 1)
            self.assertEqual(result["skipped_recent_transcripts"], 1)
            self.assertEqual(result["skipped_recent_bytes"], active.stat().st_size)
            self.assertFalse(result["estimate_complete"])
            self.assertFalse(result["readable_text_estimate_complete"])

    def test_cli_prints_aggregates_but_no_content_or_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            self.fixture(home, b'{"payload":{"text":"PRIVATE-FIXTURE-TEXT"}}\n')
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--source-home", str(home)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                check=True,
            )
            self.assertEqual(json.loads(result.stdout)["transcripts"], 2)
            self.assertNotIn("PRIVATE-FIXTURE-TEXT", result.stdout + result.stderr)
            self.assertNotIn(str(home), result.stdout + result.stderr)

            storage_result = subprocess.run(
                [sys.executable, str(SCRIPT), "--source-home", str(home),
                 "--storage-only"], stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, check=True,
            )
            self.assertTrue(json.loads(storage_result.stdout)["storage_only"])
            self.assertNotIn("PRIVATE-FIXTURE-TEXT",
                             storage_result.stdout + storage_result.stderr)

            self.extra_sources(home)
            full_scope = subprocess.run(
                [sys.executable, str(SCRIPT), "--source-home", str(home),
                 "--storage-only", "--include-extra-sources"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                env={key: value for key, value in os.environ.items()
                     if key != "PYTHONPATH"},
                check=True,
            )
            self.assertEqual(json.loads(full_scope.stdout)["paginated_threads"], 1)
            self.assertNotIn("PRIVATE", full_scope.stdout + full_scope.stderr)

            linked_home = Path(temporary) / "linked-home"
            linked_home.mkdir()
            (linked_home / ".codex").symlink_to(home / ".codex")
            refused = subprocess.run(
                [sys.executable, str(SCRIPT), "--source-home", str(linked_home)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            self.assertNotEqual(refused.returncode, 0)
            self.assertNotIn(str(linked_home), refused.stdout + refused.stderr)

    def test_compressed_object_bytes_match_packaged_helper(self):
        helper = os.environ.get("CODEX_MIGRATE_TEST_VAULT_HELPER")
        if not helper:
            self.skipTest("set CODEX_MIGRATE_TEST_VAULT_HELPER for packaged helper proof")
        from codex_migrate.vault_backup import backup

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            vault = root / "vault"
            body = (json.dumps({"payload": {"message": {"content": "work " * 900000}}})
                    + "\n").encode()
            self.fixture(home, body)
            self.extra_sources(home)
            estimate = estimator()(str(home), storage_only=True,
                                   include_extra_sources=True)
            try:
                backup(str(home), str(vault), crypto_helper=helper)
                observed = sum(path.stat().st_size for path in
                               (vault / "objects").rglob("*.cvchunk"))
                self.assertEqual(estimate["empty_vault_object_bytes"], observed)
            finally:
                metadata = vault / "vault.json"
                if metadata.exists():
                    key_id = json.loads(metadata.read_text())["key_id"]
                    subprocess.run([helper, "delete-key", "--key-id", key_id],
                                   check=True, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)


if __name__ == "__main__":
    unittest.main()
