import json
from pathlib import Path
import platform
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from codex_migrate.errors import MigrationError
from codex_migrate.vault import search
from codex_migrate.vault_backup import _paginated_history_unprotected, backup
from codex_migrate.vault_history import _group_key, _versions, search_titles, thread_timeline
from codex_migrate import vault_identity
from codex_migrate.vault_identity import (
    TranscriptChanged, loss_warnings, peek_identity, scan_transcript,
)
from codex_migrate.vault_recovery import list_snapshots, snapshot_catalog, verify_snapshot


THREAD_ID = "44444444-4444-4444-8444-444444444444"


def record(kind, payload):
    return json.dumps({"type": kind, "payload": payload}) + "\n"


class IdentityTests(unittest.TestCase):
    def test_history_remains_browsable_after_one_thousand_daily_versions(self):
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary) / "vault"
            for folder in ("refs", "manifests", "objects"):
                (vault / folder).mkdir(parents=True, exist_ok=True)
            (vault / "vault.json").write_text(json.dumps({
                "format": "codex-vault", "version": 1,
                "key_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "created_at": "2026-09-28T00:00:00+00:00",
            }))
            for index in range(1001):
                snapshot_id = f"11111111-1111-4111-8111-{index:012x}"
                reference = {"format": "codex-vault-reference", "version": 1,
                             "snapshot_id": snapshot_id,
                             "created_at": "2026-09-28T00:00:00+00:00",
                             "manifest": f"manifests/{snapshot_id}.cvmanifest"}
                (vault / "refs" / f"{snapshot_id}.json").write_text(
                    json.dumps(reference))
                (vault / "manifests" / f"{snapshot_id}.cvmanifest").touch()
            (vault / "latest.json").write_text(json.dumps(reference))
            snapshots = list_snapshots(str(vault), limit=None)
            self.assertEqual(len(snapshots), 1001)
            self.assertEqual(snapshots[0].snapshot_id, reference["snapshot_id"])
            self.assertEqual(len(list_snapshots(str(vault), limit=1)), 1)
            with patch("codex_migrate.vault_history.snapshot_catalog", return_value=[]):
                self.assertEqual(list(_versions(str(vault))), [])

    def test_paginated_history_presence_never_claims_complete_jsonl_coverage(self):
        with tempfile.TemporaryDirectory() as temporary:
            codex = Path(temporary) / ".codex"
            codex.mkdir()
            self.assertFalse(_paginated_history_unprotected(temporary))
            database = codex / "thread_history_1.sqlite"
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE thread_items (thread_id TEXT, turn_id TEXT, "
                                   "item_id TEXT, rollout_ordinal INTEGER, created_at_ms INTEGER, "
                                   "item_json TEXT, item_type TEXT, updated_at_ordinal INTEGER)")
                connection.execute("CREATE TABLE thread_history_projection_state ("
                                   "thread_id TEXT, next_rollout_byte_offset INTEGER, "
                                   "next_rollout_ordinal INTEGER)")
                connection.execute("INSERT INTO thread_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                   (THREAD_ID, "turn-1", "item-1", 1, 100,
                                    json.dumps({"id": "item-1", "type": "userMessage",
                                                "content": [{"type": "text", "text": "synthetic"}]}),
                                    "userMessage", 1))
            original = database.read_bytes()
            self.assertTrue(_paginated_history_unprotected(temporary))
            self.assertEqual(database.read_bytes(), original)

    def test_linked_paginated_history_is_rejected_without_following_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex = root / "source/.codex"
            codex.mkdir(parents=True)
            outside = root / "outside.sqlite"
            outside.write_bytes(b"private synthetic test content")
            (codex / "thread_history_1.sqlite").symlink_to(outside)
            with self.assertRaises(MigrationError):
                _paginated_history_unprotected(str(root / "source"))
            self.assertEqual(outside.read_bytes(), b"private synthetic test content")

    def test_static_malformed_record_is_not_retried_as_a_live_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "broken.jsonl"
            path.write_bytes(b'{"type":')
            with self.assertRaises(MigrationError) as raised:
                scan_transcript(path, path.name, {})
            self.assertNotIsInstance(raised.exception, TranscriptChanged)

    def test_partial_record_with_concurrent_append_is_retryable(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "active.jsonl"
            path.write_text(record("session_meta", {"id": THREAD_ID}))

            def append_then_fail(raw):
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(record("response_item", {"role": "user", "content": "later"}))
                raise json.JSONDecodeError("incomplete concurrent record", "{", 0)

            with patch.object(vault_identity.json, "loads", side_effect=append_then_fail):
                with self.assertRaises(TranscriptChanged):
                    scan_transcript(path, path.name, {})

    def test_conflicted_same_path_versions_are_not_one_thread(self):
        base = {"collection": "codex", "path": "sessions/rollout.jsonl",
                "transcript": "sessions/rollout.jsonl",
                "thread_id": None, "identity_state": "needs_review",
                "titles": ["Same title"], "records": 1,
                "assistant_messages": 0, "at_risk": True, "size": 20}
        first = {**base, "sha256": "a" * 64, "snapshot_id": "older",
                 "created_at": "2026-09-01T00:00:00Z"}
        second = {**base, "sha256": "b" * 64, "snapshot_id": "newer",
                  "created_at": "2026-09-02T00:00:00Z"}
        first["key"] = _group_key(first)
        second["key"] = _group_key(second)
        self.assertNotEqual(first["key"], second["key"])
        with patch("codex_migrate.vault_history._versions", return_value=[second, first]):
            hits = search_titles("unused", "Same title")
            self.assertEqual(len(hits), 2)
            self.assertEqual([item["version_count"] for item in hits], [1, 1])
            self.assertEqual(len(thread_timeline("unused", second["key"])), 1)

    def test_unverified_same_path_changed_bytes_are_not_one_thread(self):
        base = {"collection": "codex", "path": "sessions/unknown.jsonl",
                "transcript": "sessions/unknown.jsonl", "thread_id": None,
                "identity_state": "unverified", "titles": ["Same title"],
                "records": 1, "assistant_messages": 0, "at_risk": False,
                "size": 20}
        older = {**base, "sha256": "a" * 64, "snapshot_id": "older",
                 "created_at": "2026-09-01T00:00:00Z"}
        newer = {**base, "sha256": "b" * 64, "snapshot_id": "newer",
                 "created_at": "2026-09-02T00:00:00Z"}
        duplicate = {**older, "snapshot_id": "duplicate",
                     "created_at": "2026-09-03T00:00:00Z"}
        for version in (older, newer, duplicate):
            version["key"] = _group_key(version)
        self.assertNotEqual(older["key"], newer["key"])
        self.assertEqual(older["key"], duplicate["key"])
        with patch("codex_migrate.vault_history._versions",
                   return_value=[newer, duplicate, older]):
            hits = search_titles("unused", "Same title")
            self.assertEqual(len(hits), 2)
            self.assertEqual([hit["version_count"] for hit in hits], [1, 1])
            self.assertEqual(len(thread_timeline("unused", older["key"])), 1)

    def test_embedded_id_survives_rename_and_conflict_needs_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "renamed.jsonl"
            path.write_text(record("session_meta", {"id": THREAD_ID}))
            self.assertEqual(peek_identity(path, path.name), (THREAD_ID, "verified"))
            self.assertEqual(peek_identity(path, "rollout-" + THREAD_ID + ".jsonl"),
                             (THREAD_ID, "verified"))
            self.assertEqual(
                peek_identity(path, "rollout-11111111-1111-4111-8111-111111111111.jsonl"),
                (None, "needs_review"),
            )

    def test_lost_assistant_messages_are_flagged_without_logging_content(self):
        previous = [{"thread_id": THREAD_ID, "identity_state": "verified",
                     "size": 1000, "assistant_messages": 300}]
        current = [{"thread_id": THREAD_ID, "identity_state": "verified",
                    "size": 950, "assistant_messages": 0}]
        self.assertEqual(loss_warnings(previous, current), [THREAD_ID])

    def test_single_lost_turn_is_flagged_even_when_file_remains_large(self):
        previous = [{"thread_id": THREAD_ID, "identity_state": "verified",
                     "size": 2_000_000, "assistant_messages": 12, "user_messages": 4}]
        for counts in ({"assistant_messages": 11, "user_messages": 4},
                       {"assistant_messages": 12, "user_messages": 3}):
            current = [{**previous[0], "size": 1_900_000, **counts}]
            self.assertEqual(loss_warnings(previous, current), [THREAD_ID])

    def test_append_does_not_trigger_loss_warning(self):
        previous = [{"thread_id": THREAD_ID, "identity_state": "verified",
                     "size": 1000, "assistant_messages": 3, "user_messages": 2}]
        current = [{**previous[0], "size": 1200,
                    "assistant_messages": 4, "user_messages": 3}]
        self.assertEqual(loss_warnings(previous, current), [])

    def test_reported_851mb_to_7mb_compaction_shape_flags_previous_version(self):
        previous = [{"thread_id": THREAD_ID, "identity_state": "verified",
                     "size": 851046757, "records": 122877,
                     "assistant_messages": 3777}]
        current = [{"thread_id": THREAD_ID, "identity_state": "verified",
                    "size": 7117868, "records": 762,
                    "assistant_messages": 0}]
        self.assertEqual(loss_warnings(previous, current), [THREAD_ID])


@unittest.skipUnless(platform.system() == "Darwin", "CryptoKit helper requires macOS")
class EncryptedHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory()
        cls.helper = Path(cls.build.name) / "CodexVaultCrypto"
        subprocess.run([
            "xcrun", "swiftc", "-parse-as-library", "-O", "-D", "CODEX_VAULT_TEST_LEGACY_KEYCHAIN",
            "-target", platform.machine() + "-apple-macos13.0",
            "desktop/CodexVaultCrypto.swift", "-o", str(cls.helper),
        ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def test_state_database_titles_are_searchable_in_encrypted_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            codex = source / ".codex"
            transcript = codex / "sessions" / ("rollout-" + THREAD_ID + ".jsonl")
            transcript.parent.mkdir(parents=True)
            transcript.write_text(record("session_meta", {"id": THREAD_ID}))
            (codex / "session_index.jsonl").write_text(
                json.dumps({"id": THREAD_ID, "thread_name": "Earlier title"}) + "\n")
            with sqlite3.connect(codex / "state_5.sqlite") as connection:
                connection.execute("CREATE TABLE threads (id TEXT, title TEXT, name TEXT)")
                connection.execute("INSERT INTO threads VALUES (?, ?, ?)",
                                   (THREAD_ID, "State original title", "State current title"))
            vault = root / "vault"
            try:
                result = backup(str(source), str(vault), crypto_helper=str(self.helper))
                self.assertFalse(result.title_index_unavailable)
                catalog = snapshot_catalog(str(vault), crypto_helper=str(self.helper))
                self.assertEqual(catalog[0]["titles"], [
                    "Earlier title", "State original title", "State current title"])
                self.assertEqual(len(search_titles(str(vault), "Earlier title",
                                                   crypto_helper=str(self.helper))), 1)
                self.assertEqual(len(search_titles(str(vault), "State original",
                                                   crypto_helper=str(self.helper))), 1)
                self.assertEqual(len(search_titles(str(vault), "State current",
                                                   crypto_helper=str(self.helper))), 1)
                ciphertext = b"".join(path.read_bytes() for path in vault.rglob("*")
                                      if path.is_file())
                self.assertNotIn(b"State current title", ciphertext)
            finally:
                if (vault / "vault.json").exists():
                    key_id = json.loads((vault / "vault.json").read_text())["key_id"]
                    subprocess.run([str(self.helper), "delete-key", "--key-id", key_id],
                                   check=True, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)

    def test_paginated_history_marks_verified_jsonl_snapshot_incomplete(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            codex = source / ".codex"
            path = codex / "sessions" / ("rollout-" + THREAD_ID + ".jsonl")
            path.parent.mkdir(parents=True)
            original = record("session_meta", {"id": THREAD_ID})
            path.write_text(original)
            database = codex / "thread_history_1.sqlite"
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE thread_items (thread_id TEXT, turn_id TEXT, "
                                   "item_id TEXT, rollout_ordinal INTEGER, created_at_ms INTEGER, "
                                   "item_json TEXT, item_type TEXT, updated_at_ordinal INTEGER)")
                connection.execute("CREATE TABLE thread_history_projection_state ("
                                   "thread_id TEXT, next_rollout_byte_offset INTEGER, "
                                   "next_rollout_ordinal INTEGER)")
                connection.execute("INSERT INTO thread_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                   (THREAD_ID, "turn-1", "item-1", 1, 100,
                                    json.dumps({"id": "item-1", "type": "userMessage",
                                                "content": [{"type": "text", "text": "synthetic"}]}),
                                    "userMessage", 1))
            before = database.read_bytes()
            vault = root / "vault"
            try:
                result = backup(str(source), str(vault), crypto_helper=str(self.helper))
                self.assertTrue(result.needs_attention)
                self.assertTrue(result.paginated_history_unprotected)
                self.assertEqual(result.at_risk_threads, 0)
                verify_snapshot(str(vault), snapshot=result.snapshot_id,
                                crypto_helper=str(self.helper))
                self.assertFalse(snapshot_catalog(str(vault),
                                                 crypto_helper=str(self.helper))[0]["at_risk"])
                second = backup(str(source), str(vault), crypto_helper=str(self.helper))
                self.assertEqual(second.at_risk_threads, 0)
                self.assertEqual([item["collection"] for item in snapshot_catalog(
                    str(vault), crypto_helper=str(self.helper))], ["active", "paginated"])
                self.assertEqual(path.read_text(), original)
                self.assertEqual(database.read_bytes(), before)
            finally:
                if (vault / "vault.json").exists():
                    key_id = json.loads((vault / "vault.json").read_text())["key_id"]
                    subprocess.run([str(self.helper), "delete-key", "--key-id", key_id],
                                   check=True, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)

    def test_unreadable_optional_title_index_does_not_block_transcript_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            codex = source / ".codex"
            path = codex / "sessions" / ("rollout-" + THREAD_ID + ".jsonl")
            path.parent.mkdir(parents=True)
            original = (record("session_meta", {"id": THREAD_ID})
                        + record("response_item", {"role": "user", "content": "find this work"}))
            path.write_text(original)
            (codex / "session_index.jsonl").write_text("{broken\n")
            vault = root / "vault"
            try:
                result = backup(str(source), str(vault), crypto_helper=str(self.helper))
                self.assertFalse(result.needs_attention)
                self.assertTrue(result.title_index_unavailable)
                self.assertEqual(result.at_risk_threads, 0)
                self.assertEqual(result.transcript_files, 1)
                verify_snapshot(str(vault), snapshot=result.snapshot_id,
                                crypto_helper=str(self.helper))
                catalog = snapshot_catalog(str(vault), crypto_helper=str(self.helper))
                self.assertEqual(catalog[0]["thread_id"], THREAD_ID)
                self.assertEqual(catalog[0]["titles"], [])
                self.assertEqual(path.read_text(), original)
                self.assertEqual(len(search(str(source), "find this work")), 1)
            finally:
                if (vault / "vault.json").exists():
                    key_id = json.loads((vault / "vault.json").read_text())["key_id"]
                    subprocess.run([str(self.helper), "delete-key", "--key-id", key_id],
                                   check=True, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)

    def test_duplicate_live_thread_id_needs_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            sessions = source / ".codex/sessions"
            sessions.mkdir(parents=True)
            for name in ("first.jsonl", "second.jsonl"):
                (sessions / name).write_text(record("session_meta", {"id": THREAD_ID}))
            vault = root / "vault"
            try:
                result = backup(str(source), str(vault), crypto_helper=str(self.helper))
                self.assertTrue(result.needs_attention)
                self.assertEqual(result.at_risk_threads, 2)
                catalog = snapshot_catalog(str(vault), crypto_helper=str(self.helper))
                self.assertEqual([item["identity_state"] for item in catalog],
                                 ["needs_review", "needs_review"])
                self.assertTrue(all(item["at_risk"] for item in catalog))
            finally:
                if (vault / "vault.json").exists():
                    key_id = json.loads((vault / "vault.json").read_text())["key_id"]
                    subprocess.run([str(self.helper), "delete-key", "--key-id", key_id],
                                   check=True, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)

    def test_titles_and_versions_are_encrypted_and_rewrite_is_flagged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            codex = source / ".codex"
            path = codex / "sessions/rollout-" / ("rollout-" + THREAD_ID + ".jsonl")
            path.parent.mkdir(parents=True)
            index = codex / "session_index.jsonl"
            index.write_text(json.dumps({"id": THREAD_ID, "thread_name": "Unification Foundation"}) + "\n")
            initial = record("session_meta", {"id": THREAD_ID})
            initial += "".join(record("response_item", {"role": "assistant", "content": "PRIVATE WORK"})
                               for _ in range(12))
            path.write_text(initial)
            vault = root / "vault"
            try:
                first = backup(str(source), str(vault), crypto_helper=str(self.helper))
                self.assertFalse(first.needs_attention)
                catalog = snapshot_catalog(str(vault), crypto_helper=str(self.helper))
                self.assertEqual(catalog[0]["thread_id"], THREAD_ID)
                self.assertEqual(catalog[0]["titles"], ["Unification Foundation"])
                self.assertEqual(catalog[0]["assistant_messages"], 12)
                self.assertEqual(len(search(str(source), "Unification Foundation")), 1)
                ciphertext = b"".join(item.read_bytes() for item in vault.rglob("*")
                                      if item.is_file())
                self.assertNotIn(b"Unification Foundation", ciphertext)
                self.assertNotIn(b"PRIVATE WORK", ciphertext)

                index.write_text(index.read_text()
                                 + json.dumps({"id": THREAD_ID,
                                               "thread_name": "Release Manager"}) + "\n")
                second = backup(str(source), str(vault), crypto_helper=str(self.helper))
                self.assertFalse(second.needs_attention)
                hits = search_titles(str(vault), "Unification Foundation",
                                     crypto_helper=str(self.helper))
                self.assertEqual(len(hits), 1)
                self.assertEqual(hits[0]["thread_id"], THREAD_ID)
                timeline = thread_timeline(str(vault), "id:" + THREAD_ID,
                                           crypto_helper=str(self.helper))
                self.assertEqual(len(timeline), 2)  # Title changed, bytes did not.

                path.write_text(record("session_meta", {"id": THREAD_ID})
                                + record("response_item", {"role": "user", "content": "keep me"}))
                third = backup(str(source), str(vault), crypto_helper=str(self.helper))
                self.assertTrue(third.needs_attention)
                self.assertEqual(third.at_risk_threads, 1)
                self.assertTrue(snapshot_catalog(str(vault), crypto_helper=str(self.helper))[0]["at_risk"])
                fourth = backup(str(source), str(vault), crypto_helper=str(self.helper))
                self.assertTrue(fourth.needs_attention)  # Later identical captures cannot clear a loss.
                verify_snapshot(str(vault), snapshot=first.snapshot_id,
                                crypto_helper=str(self.helper))
                timeline = thread_timeline(str(vault), "id:" + THREAD_ID,
                                           crypto_helper=str(self.helper))
                self.assertEqual(timeline[0]["snapshot_id"], fourth.snapshot_id)
                self.assertEqual(len(timeline), 3)
            finally:
                if (vault / "vault.json").exists():
                    key_id = json.loads((vault / "vault.json").read_text())["key_id"]
                    subprocess.run([str(self.helper), "delete-key", "--key-id", key_id],
                                   check=True, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
