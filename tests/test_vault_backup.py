import hashlib
import json
import os
from pathlib import Path
import platform
import sqlite3
import subprocess
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from codex_migrate.errors import MigrationError
from codex_migrate import vault_backup
from codex_migrate.vault import markdown_chunks, read_thread_page, search
from codex_migrate.vault_backup import backup, plan
from codex_migrate.vault_identity import TranscriptChanged
from codex_migrate.vault_install import plan_install
from codex_migrate.vault_paginated import restored_items
from codex_migrate.vault_recovery import (
    export_recovery_key, import_recovery_key, list_snapshots, restore_snapshot,
    snapshot_catalog, vault_storage_usage, verify_snapshot,
)


@unittest.skipUnless(platform.system() == "Darwin", "CryptoKit backup helper requires macOS")
class VaultBackupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        packaged = os.environ.get("CODEX_MIGRATE_TEST_VAULT_HELPER")
        if packaged:
            cls.build = None
            cls.helper = Path(packaged)
            if not cls.helper.is_file():
                raise AssertionError("packaged Vault helper is missing")
            return
        cls.build = tempfile.TemporaryDirectory()
        cls.helper = Path(cls.build.name) / "CodexVaultCrypto"
        subprocess.run([
            "xcrun", "swiftc", "-parse-as-library", "-O", "-D", "CODEX_VAULT_TEST_LEGACY_KEYCHAIN",
            "-target", platform.machine() + "-apple-macos13.0",
            "desktop/CodexVaultCrypto.swift", "-o", str(cls.helper),
        ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    @classmethod
    def tearDownClass(cls):
        if cls.build is not None:
            cls.build.cleanup()

    def fixture(self, root: Path) -> None:
        active = root / ".codex/sessions/2026/09/17/active.jsonl"
        archived = root / ".codex/archived_sessions/archived.jsonl"
        active.parent.mkdir(parents=True)
        archived.parent.mkdir(parents=True)
        active.write_text(
            json.dumps({"payload": {"message": {"content": "PRIVATE-ACTIVE-CONTENT"}}}) + "\n",
            encoding="utf-8",
        )
        archived.write_text(
            json.dumps({"payload": {"text": "PRIVATE-ARCHIVED-CONTENT"}}) + "\n",
            encoding="utf-8",
        )
        (root / ".codex/auth.json").write_text("NEVER-COPY-AUTH", encoding="utf-8")
        (root / ".codex/installation_id").write_text("NEVER-COPY-ID", encoding="utf-8")

    def delete_key(self, vault: Path) -> None:
        metadata = vault / "vault.json"
        if not metadata.exists():
            return
        key_id = json.loads(metadata.read_text(encoding="utf-8"))["key_id"]
        subprocess.run(
            [str(self.helper), "delete-key", "--key-id", key_id],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

    def test_plan_is_read_only_and_does_not_require_crypto_helper(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "vault"
            self.fixture(source)
            result = plan(str(source), str(destination))
            self.assertFalse(result.applied)
            self.assertTrue(result.encrypted)
            self.assertEqual(result.transcript_files, 2)
            self.assertFalse(destination.exists())

    def test_backup_is_encrypted_versioned_verified_and_incremental(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "vault"
            self.fixture(source)
            try:
                first = backup(
                    str(source), str(destination), crypto_helper=str(self.helper),
                    chunk_size=64 * 1024,
                )
                self.assertIsNotNone(first.recovery_key)
                self.assertTrue(first.recovery_key.startswith("CV1-"))
                self.assertEqual(first.transcript_files, 2)
                self.assertEqual(first.chunks, 2)
                objects = sorted((destination / "objects").rglob("*.cvchunk"))
                self.assertEqual(len(objects), 2)
                first_object_names = [path.relative_to(destination).as_posix() for path in objects]

                second = backup(
                    str(source), str(destination), crypto_helper=str(self.helper),
                    chunk_size=64 * 1024,
                )
                self.assertIsNone(second.recovery_key)
                self.assertNotEqual(first.snapshot_id, second.snapshot_id)
                self.assertEqual(
                    [path.relative_to(destination).as_posix()
                     for path in sorted((destination / "objects").rglob("*.cvchunk"))],
                    first_object_names,
                )
                self.assertEqual(len(list((destination / "refs").glob("*.json"))), 2)
                latest = json.loads((destination / "latest.json").read_text(encoding="utf-8"))
                self.assertEqual(latest["snapshot_id"], second.snapshot_id)
                history = list_snapshots(str(destination))
                self.assertEqual(
                    [item.snapshot_id for item in history],
                    [second.snapshot_id, first.snapshot_id],
                )
                storage = vault_storage_usage(str(destination))
                self.assertEqual(storage["storage_bytes"], sum(
                    path.stat().st_size for path in destination.rglob("*") if path.is_file()))
                self.assertEqual(storage["storage_files"], sum(
                    path.is_file() for path in destination.rglob("*")))
                self.assertEqual([item.latest for item in history], [True, False])
                self.assertEqual(
                    [item.snapshot_id for item in list_snapshots(
                        str(destination), limit=1)],
                    [second.snapshot_id],
                )

                stored = b"".join(
                    path.read_bytes() for path in destination.rglob("*") if path.is_file())
                self.assertNotIn(b"PRIVATE-ACTIVE-CONTENT", stored)
                self.assertNotIn(b"PRIVATE-ARCHIVED-CONTENT", stored)
                self.assertNotIn(b"NEVER-COPY-AUTH", stored)
                self.assertNotIn(b"NEVER-COPY-ID", stored)
            finally:
                self.delete_key(destination)

    def test_paginated_items_are_encrypted_separately_and_recoverable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "vault"
            codex = source / ".codex"
            codex.mkdir(parents=True)
            database = codex / "thread_history_1.sqlite"
            thread_id = "44444444-4444-4444-8444-444444444444"
            item = {"id": "item-1", "type": "userMessage",
                    "content": [{"type": "text", "text": "SYNTHETIC-DATABASE-ONLY-TURN"}]}
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE thread_items (thread_id TEXT, turn_id TEXT, "
                                   "item_id TEXT, rollout_ordinal INTEGER, created_at_ms INTEGER, "
                                   "item_json TEXT, item_type TEXT, updated_at_ordinal INTEGER)")
                connection.execute("CREATE TABLE thread_history_projection_state ("
                                   "thread_id TEXT, next_rollout_byte_offset INTEGER, "
                                   "next_rollout_ordinal INTEGER)")
                connection.execute("INSERT INTO thread_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                   (thread_id, "turn-1", "item-1", 1, 100,
                                    json.dumps(item), "userMessage", 1))
            original = database.read_bytes()
            planned = plan(str(source), str(destination))
            self.assertEqual(planned.transcript_files, 0)
            self.assertEqual(planned.paginated_threads, 1)
            self.assertGreaterEqual(planned.paginated_database_bytes, len(original))
            progress_states = []
            try:
                first = backup(str(source), str(destination), crypto_helper=str(self.helper),
                               chunk_size=64 * 1024, progress=lambda *values: progress_states.append(values))
                self.assertEqual(progress_states[0], (0, 1, 0, 0))
                self.assertEqual(progress_states[-1][0:2], (1, 1))
                self.assertEqual(progress_states[-1][3], 0)
                self.assertTrue(first.paginated_history_unprotected)
                self.assertTrue(first.needs_attention)
                self.assertEqual(first.transcript_files, 1)
                self.assertEqual(database.read_bytes(), original)
                catalog = snapshot_catalog(str(destination), crypto_helper=str(self.helper))
                self.assertEqual([(file["collection"], file["thread_id"])
                                  for file in catalog], [("paginated", thread_id)])
                encrypted = b"".join(path.read_bytes() for path in
                                     destination.rglob("*") if path.is_file())
                self.assertNotIn(b"SYNTHETIC-DATABASE-ONLY-TURN", encrypted)
                (root / "browse").mkdir()
                restored = root / "browse/.codex"
                restore_snapshot(str(source), str(destination), str(restored),
                                 crypto_helper=str(self.helper))
                rows = (restored / "paginated_history" /
                        (thread_id + ".jsonl")).read_text().splitlines()
                self.assertEqual(len(rows), 1)
                self.assertEqual(json.loads(json.loads(rows[0])["item_json"]), item)
                self.assertEqual(json.loads(next(restored_items(
                    str(root / "browse"), thread_id)).item_json), item)
                found = search(str(root / "browse"), "SYNTHETIC-DATABASE-ONLY-TURN",
                               catalog=catalog)
                self.assertEqual([(match.collection, match.transcript, match.cursor)
                                  for match in found], [("paginated", thread_id + ".jsonl", 0)])
                titled_catalog = [{**catalog[0], "titles": ["An older synthetic title"]}]
                by_title = search(str(root / "browse"), "older synthetic",
                                  catalog=titled_catalog)
                self.assertEqual([(match.collection, match.line) for match in by_title],
                                 [("paginated", 0)])
                page, next_cursor = read_thread_page(
                    str(root / "browse"), "paginated", thread_id + ".jsonl",
                    expected_query="SYNTHETIC-DATABASE-ONLY-TURN")
                self.assertIsNone(next_cursor)
                self.assertEqual([(entry.role, entry.text) for entry in page.entries],
                                 [("User", "SYNTHETIC-DATABASE-ONLY-TURN")])
                exported = b"".join(markdown_chunks(
                    str(root / "browse"), "paginated", thread_id + ".jsonl"))
                self.assertIn(b"SYNTHETIC-DATABASE-ONLY-TURN", exported)
                self.assertIn(b"saved paginated source", exported)
                with self.assertRaisesRegex(MigrationError, "whole-history install is refused"):
                    plan_install(str(source), str(destination), crypto_helper=str(self.helper))
                second = backup(str(source), str(destination), crypto_helper=str(self.helper),
                                chunk_size=64 * 1024)
                self.assertTrue(second.needs_attention)
                self.assertEqual(len(list((destination / "objects").rglob("*.cvchunk"))), 1)
                with sqlite3.connect(database) as connection:
                    connection.execute("UPDATE thread_items SET item_json='not JSON'")
                with self.assertRaises(MigrationError):
                    backup(str(source), str(destination), crypto_helper=str(self.helper),
                           chunk_size=64 * 1024)
                self.assertEqual(json.loads((destination / "latest.json").read_text())
                                 ["snapshot_id"], second.snapshot_id)
            finally:
                self.delete_key(destination)

    def test_restored_fork_search_preserves_inherited_prefix(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "vault"
            parent_id = "11111111-1111-4111-8111-111111111111"
            child_id = "22222222-2222-4222-8222-222222222222"
            parent = (source / ".codex/archived_sessions" /
                      ("rollout-" + parent_id + ".jsonl"))
            child = (source / ".codex/sessions/2026/09/28" /
                     ("rollout-" + child_id + ".jsonl"))
            child_transcript = "2026/09/28/" + child.name
            parent.parent.mkdir(parents=True)
            child.parent.mkdir(parents=True)

            def record(ordinal, kind, payload):
                return json.dumps({"ordinal": ordinal, "type": kind,
                                   "payload": payload}) + "\n"

            inherited = (record(0, "session_meta", {"id": parent_id})
                         + record(1, "response_item", {"text": "Inherited Clerk plan"}))
            parent.write_text(inherited + record(
                2, "response_item", {"text": "Parent-only later plan"}), encoding="utf-8")
            child.write_text(record(2, "session_meta", {"id": child_id, "history_base": {
                "thread_id": parent_id, "end_ordinal_exclusive": 2,
                "end_byte_offset": len(inherited.encode("utf-8")),
            }}) + record(3, "response_item", {"text": "Child-local implementation"}),
                encoding="utf-8")

            try:
                result = backup(str(source), str(destination), crypto_helper=str(self.helper))
                self.assertEqual(result.transcript_files, 2)
                restored_home = root / "restored"
                restored = restored_home / ".codex"
                restored_home.mkdir()
                restore_snapshot(str(source), str(destination), str(restored),
                                 crypto_helper=str(self.helper))
                matches = search(str(restored_home), "Inherited Clerk plan")
                self.assertEqual({(match.collection, match.transcript) for match in matches},
                                 {("active", child_transcript), ("archived", parent.name)})
                later = search(str(restored_home), "Parent-only later plan")
                self.assertEqual({(match.collection, match.transcript) for match in later},
                                 {("archived", parent.name)})
                child_match = next(match for match in matches if match.collection == "active")
                page, _ = read_thread_page(str(restored_home), "active", child_transcript,
                                           child_match.cursor, expected_query="Inherited Clerk")
                self.assertEqual(page.entries[0].text, "Inherited Clerk plan")
            finally:
                self.delete_key(destination)

    def test_progress_counts_both_transcript_and_database_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            codex = source / ".codex"
            transcript = codex / "sessions/fixture.jsonl"
            transcript.parent.mkdir(parents=True)
            transcript.write_text(json.dumps({"payload": {"text": "synthetic transcript"}}) + "\n")
            database = codex / "thread_history_1.sqlite"
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE thread_items (thread_id TEXT, turn_id TEXT, "
                                   "item_id TEXT, rollout_ordinal INTEGER, created_at_ms INTEGER, "
                                   "item_json TEXT, item_type TEXT, updated_at_ordinal INTEGER)")
                connection.execute("CREATE TABLE thread_history_projection_state ("
                                   "thread_id TEXT, next_rollout_byte_offset INTEGER, "
                                   "next_rollout_ordinal INTEGER)")
                connection.execute("INSERT INTO thread_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                   ("44444444-4444-4444-8444-444444444444", "turn-1",
                                    "item-1", 1, 100,
                                    json.dumps({"id": "item-1", "type": "userMessage",
                                                "text": "synthetic database turn"}),
                                    "userMessage", 1))
            destination = root / "vault"
            updates = []
            try:
                result = backup(str(source), str(destination), crypto_helper=str(self.helper),
                                progress=lambda *values: updates.append(values))
                self.assertEqual(result.transcript_files, 2)
                self.assertEqual(updates[0], (0, 2, 0, 0))
                self.assertTrue(any(done == 1 and total == 2 for done, total, _, _ in updates))
                self.assertEqual(updates[-1][:2], (2, 2))
                self.assertEqual(updates[-1][3], 0)
            finally:
                self.delete_key(destination)

    def test_storage_usage_refuses_linked_entries(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            vault = root / "vault"
            vault.mkdir()
            (vault / "regular").write_bytes(b"fixture")
            (vault / "linked").symlink_to(root / "outside")
            with self.assertRaisesRegex(MigrationError, "unsupported storage entry"):
                vault_storage_usage(str(vault))

    @unittest.skipUnless(
        os.environ.get("CODEX_MIGRATE_LARGE_HISTORY_PROBE") == "1",
        "opt-in physical large-history probe",
    )
    def test_large_history_incremental_backup_keeps_unchanged_chunks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "vault"
            sessions = source / ".codex/sessions/2026/09/24"
            sessions.mkdir(parents=True)
            for index in range(2048):
                (sessions / f"thread-{index:04d}.jsonl").write_text(
                    json.dumps({"thread": index, "text": f"synthetic-{index:04d}"}) + "\n",
                    encoding="utf-8",
                )
            try:
                first = backup(str(source), str(destination), crypto_helper=str(self.helper))
                self.assertEqual(first.transcript_files, 2048)
                self.assertEqual(
                    verify_snapshot(str(destination), crypto_helper=str(self.helper)).transcript_files,
                    2048,
                )
                first_objects = set((destination / "objects").rglob("*.cvchunk"))
                changed = sessions / "thread-1024.jsonl"
                changed.write_text(changed.read_text(encoding="utf-8") +
                                   json.dumps({"text": "later synthetic work"}) + "\n",
                                   encoding="utf-8")
                second = backup(str(source), str(destination), crypto_helper=str(self.helper))
                self.assertEqual(second.transcript_files, 2048)
                self.assertNotEqual(second.snapshot_id, first.snapshot_id)
                second_objects = set((destination / "objects").rglob("*.cvchunk"))
                self.assertEqual(len(second_objects - first_objects), 1)
                self.assertEqual(
                    verify_snapshot(str(destination), crypto_helper=str(self.helper)).snapshot_id,
                    second.snapshot_id,
                )
            finally:
                self.delete_key(destination)

    def test_tampered_chunk_fails_closed_without_new_reference(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "vault"
            self.fixture(source)
            try:
                first = backup(
                    str(source), str(destination), crypto_helper=str(self.helper),
                    chunk_size=64 * 1024,
                )
                chunk = next((destination / "objects").rglob("*.cvchunk"))
                content = bytearray(chunk.read_bytes())
                content[len(content) // 2] ^= 1
                chunk.write_bytes(content)
                with self.assertRaisesRegex(MigrationError, "no new snapshot"):
                    backup(
                        str(source), str(destination), crypto_helper=str(self.helper),
                        chunk_size=64 * 1024,
                    )
                references = list((destination / "refs").glob("*.json"))
                self.assertEqual(len(references), 1)
                latest = json.loads((destination / "latest.json").read_text(encoding="utf-8"))
                self.assertEqual(latest["snapshot_id"], first.snapshot_id)
            finally:
                self.delete_key(destination)

    def test_compressed_transcript_is_lossless_incremental_and_authenticated(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "vault"
            restored = root / "restored"
            self.fixture(source)
            transcript = source / ".codex/sessions/2026/09/17/active.jsonl"
            content = "".join(f"{index:08x}" + "A" * 65528 for index in range(16))
            transcript.write_text(json.dumps({"payload": {"message": {"content": content}}}) + "\n")
            try:
                first = backup(str(source), str(destination), crypto_helper=str(self.helper),
                               chunk_size=64 * 1024)
                objects = sorted((destination / "objects").rglob("*.cvchunk"))
                self.assertLess(sum(path.stat().st_size for path in objects),
                                transcript.stat().st_size // 2)
                self.assertEqual(json.loads((destination / "vault.json").read_text())
                                 ["storage_codec"], "lzfse-v1")
                second = backup(str(source), str(destination), crypto_helper=str(self.helper),
                                chunk_size=64 * 1024)
                self.assertNotEqual(first.snapshot_id, second.snapshot_id)
                self.assertEqual(objects, sorted((destination / "objects").rglob("*.cvchunk")))
                restore_snapshot(str(source), str(destination), str(restored),
                                 snapshot=first.snapshot_id, crypto_helper=str(self.helper))
                self.assertEqual((restored / "sessions/2026/09/17/active.jsonl").read_bytes(),
                                 transcript.read_bytes())
                compressed = min(objects, key=lambda path: path.stat().st_size)
                damaged = bytearray(compressed.read_bytes())
                damaged[len(damaged) // 2] ^= 1
                compressed.write_bytes(damaged)
                with self.assertRaises(MigrationError):
                    verify_snapshot(str(destination), snapshot=first.snapshot_id,
                                    crypto_helper=str(self.helper))
            finally:
                self.delete_key(destination)

    def test_incompressible_chunks_keep_raw_format(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "vault"
            self.fixture(source)
            try:
                backup(str(source), str(destination), crypto_helper=str(self.helper))
                key_id = json.loads((destination / "vault.json").read_text())["key_id"]
                random_bytes = hashlib.shake_256(b"vault-incompressible-fixture").digest(64 * 1024)
                stored = subprocess.run([
                    str(self.helper), "store-chunks", "--key-id", key_id,
                    "--object-dir", str(destination / "objects"),
                    "--chunk-size", str(64 * 1024),
                ], input=random_bytes, check=True, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE)
                chunks = json.loads(stored.stdout)["chunks"]
                self.assertEqual(len(chunks), 1)
                self.assertEqual(set(chunks[0]), {"id", "size"})
                self.assertEqual(chunks[0]["size"], len(random_bytes))
            finally:
                self.delete_key(destination)

    def test_legacy_vault_upgrades_only_after_new_snapshot_verifies(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "vault"
            restored = root / "restored"
            self.fixture(source)
            try:
                first = backup(str(source), str(destination), crypto_helper=str(self.helper))
                metadata_path = destination / "vault.json"
                legacy = json.loads(metadata_path.read_text())
                legacy.pop("storage_codec")
                metadata_path.write_text(json.dumps(legacy))
                self.assertEqual(verify_snapshot(str(destination), snapshot=first.snapshot_id,
                                                 crypto_helper=str(self.helper)).snapshot_id,
                                 first.snapshot_id)
                legacy_chunk = next((destination / "objects").rglob("*.cvchunk"))
                original_ciphertext = legacy_chunk.read_bytes()
                damaged = bytearray(original_ciphertext)
                damaged[len(damaged) // 2] ^= 1
                legacy_chunk.write_bytes(damaged)
                with self.assertRaises(MigrationError):
                    backup(str(source), str(destination), crypto_helper=str(self.helper))
                self.assertNotIn("storage_codec", json.loads(metadata_path.read_text()))
                self.assertEqual(json.loads((destination / "latest.json").read_text())
                                 ["snapshot_id"], first.snapshot_id)
                legacy_chunk.write_bytes(original_ciphertext)
                transcript = source / ".codex/sessions/2026/09/17/active.jsonl"
                transcript.write_text(json.dumps({"payload": {"text": "B" * 200_000}}) + "\n")
                second = backup(str(source), str(destination), crypto_helper=str(self.helper))
                self.assertEqual(json.loads(metadata_path.read_text())["storage_codec"],
                                 "lzfse-v1")
                self.assertEqual(verify_snapshot(str(destination), snapshot=first.snapshot_id,
                                                 crypto_helper=str(self.helper)).snapshot_id,
                                 first.snapshot_id)
                restore_snapshot(str(source), str(destination), str(restored),
                                 snapshot=second.snapshot_id, crypto_helper=str(self.helper))
                self.assertEqual((restored / "sessions/2026/09/17/active.jsonl").read_bytes(),
                                 transcript.read_bytes())
            finally:
                self.delete_key(destination)

    def test_transcript_append_once_during_backup_retries_and_verifies(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "vault"
            restored = root / "restored"
            self.fixture(source)
            transcript = source / ".codex/sessions/2026/09/17/active.jsonl"
            try:
                original_run_helper = vault_backup._run_helper
                stores = 0

                def append_after_first_store(helper, arguments, **kwargs):
                    nonlocal stores
                    result = original_run_helper(helper, arguments, **kwargs)
                    input_file = kwargs.get("input_file")
                    if (arguments[0] == "store-chunks" and input_file is not None
                            and os.fstat(input_file.fileno()).st_ino == transcript.stat().st_ino):
                        stores += 1
                        if stores == 1:
                            with transcript.open("a", encoding="utf-8") as handle:
                                handle.write(json.dumps({"type": "response_item", "payload": "later"}) + "\n")
                    return result

                with patch.object(vault_backup, "_run_helper", side_effect=append_after_first_store):
                    saved = backup(str(source), str(destination), crypto_helper=str(self.helper))
                self.assertEqual(stores, 2)
                self.assertEqual(verify_snapshot(str(destination), crypto_helper=str(self.helper))
                                 .snapshot_id, saved.snapshot_id)
                restore_snapshot(str(source), str(destination), str(restored),
                                 crypto_helper=str(self.helper))
                self.assertEqual((restored / "sessions/2026/09/17/active.jsonl").read_bytes(),
                                 transcript.read_bytes())
            finally:
                self.delete_key(destination)

    def test_transcript_change_during_identity_scan_retries(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "vault"
            self.fixture(source)
            try:
                original_scan = vault_backup.scan_transcript
                scans = 0

                def changed_once(path, relative, titles):
                    nonlocal scans
                    scans += 1
                    if scans == 1:
                        raise TranscriptChanged("A conversation changed during identity inspection.")
                    return original_scan(path, relative, titles)

                with patch.object(vault_backup, "scan_transcript", side_effect=changed_once):
                    saved = backup(str(source), str(destination), crypto_helper=str(self.helper))
                self.assertEqual(scans, saved.transcript_files + 1)
                self.assertEqual(verify_snapshot(str(destination), crypto_helper=str(self.helper))
                                 .snapshot_id, saved.snapshot_id)
            finally:
                self.delete_key(destination)

    def test_transcript_rewrite_during_backup_keeps_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "vault"
            self.fixture(source)
            transcript = source / ".codex/sessions/2026/09/17/active.jsonl"
            try:
                first = backup(str(source), str(destination), crypto_helper=str(self.helper))
                original_run_helper = vault_backup._run_helper
                rewrites = 0

                def rewrite_after_chunk_store(helper, arguments, **kwargs):
                    nonlocal rewrites
                    result = original_run_helper(helper, arguments, **kwargs)
                    input_file = kwargs.get("input_file")
                    if (arguments[0] == "store-chunks" and input_file is not None
                            and os.fstat(input_file.fileno()).st_ino == transcript.stat().st_ino
                            and rewrites < vault_backup.MAX_CHANGED_TRANSCRIPT_ATTEMPTS):
                        rewrites += 1
                        transcript.write_text(
                            transcript.read_text(encoding="utf-8")
                            + json.dumps({"type": "response_item", "payload": str(rewrites)}) + "\n",
                            encoding="utf-8",
                        )
                    return result

                with patch.object(vault_backup, "_run_helper", side_effect=rewrite_after_chunk_store):
                    with self.assertRaisesRegex(MigrationError, "changed during backup"):
                        backup(str(source), str(destination), crypto_helper=str(self.helper))
                self.assertEqual(rewrites, vault_backup.MAX_CHANGED_TRANSCRIPT_ATTEMPTS)
                latest = json.loads((destination / "latest.json").read_text(encoding="utf-8"))
                self.assertEqual(latest["snapshot_id"], first.snapshot_id)
                self.assertEqual(len(list((destination / "refs").glob("*.json"))), 1)
                self.assertEqual(
                    verify_snapshot(str(destination), crypto_helper=str(self.helper)).snapshot_id,
                    first.snapshot_id,
                )
            finally:
                self.delete_key(destination)

    def test_snapshot_can_be_verified_rekeyed_and_restored_to_staging(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "vault"
            restored = root / "restored"
            self.fixture(source)
            try:
                saved = backup(
                    str(source), str(destination), crypto_helper=str(self.helper),
                    chunk_size=64 * 1024,
                )
                checked = verify_snapshot(
                    str(destination), crypto_helper=str(self.helper))
                self.assertEqual(checked.snapshot_id, saved.snapshot_id)
                self.assertEqual(checked.transcript_files, 2)
                self.assertFalse(restored.exists())

                recovery_key = export_recovery_key(
                    str(destination), crypto_helper=str(self.helper))
                self.assertEqual(recovery_key, saved.recovery_key)
                self.delete_key(destination)
                with self.assertRaisesRegex(MigrationError, "no new snapshot"):
                    verify_snapshot(str(destination), crypto_helper=str(self.helper))
                import_recovery_key(
                    str(destination), recovery_key, crypto_helper=str(self.helper))

                result = restore_snapshot(
                    str(source), str(destination), str(restored),
                    crypto_helper=str(self.helper),
                )
                self.assertEqual(result.snapshot_id, saved.snapshot_id)
                self.assertEqual(
                    (restored / "sessions/2026/09/17/active.jsonl").read_text(
                        encoding="utf-8"),
                    (source / ".codex/sessions/2026/09/17/active.jsonl").read_text(
                        encoding="utf-8"),
                )
                self.assertEqual(
                    (restored / "archived_sessions/archived.jsonl").read_text(
                        encoding="utf-8"),
                    (source / ".codex/archived_sessions/archived.jsonl").read_text(
                        encoding="utf-8"),
                )
                self.assertFalse((restored / "auth.json").exists())
                self.assertFalse((restored / "installation_id").exists())
                receipt = json.loads(
                    (restored / "restore-receipt.json").read_text(encoding="utf-8"))
                self.assertEqual(receipt["snapshot_id"], saved.snapshot_id)
                self.assertEqual(receipt["files"], 2)
            finally:
                self.delete_key(destination)

    def test_v1_snapshot_remains_verifiable_and_restorable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "vault"
            restored = root / "restored"
            self.fixture(source)
            try:
                backup(str(source), str(destination), crypto_helper=str(self.helper))
                key_id = json.loads((destination / "vault.json").read_text())["key_id"]
                transcript = source / ".codex/sessions/2026/09/17/active.jsonl"
                stored = subprocess.run([
                    str(self.helper), "store-chunks", "--key-id", key_id,
                    "--object-dir", str(destination / "objects"),
                    "--chunk-size", str(64 * 1024),
                ], input=transcript.read_bytes(), check=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                file_info = json.loads(stored.stdout)
                snapshot_id = str(uuid.uuid4())
                created_at = datetime.now(timezone.utc).isoformat()
                manifest = {
                    "format": "codex-vault-snapshot", "version": 1,
                    "snapshot_id": snapshot_id, "created_at": created_at,
                    "files": [{
                        "collection": "active", "path": "2026/09/17/active.jsonl",
                        "size": file_info["size"], "mtime_ns": transcript.stat().st_mtime_ns,
                        "sha256": file_info["sha256"], "chunks": file_info["chunks"],
                    }],
                }
                sealed = destination / "manifests" / (snapshot_id + ".cvmanifest")
                subprocess.run([
                    str(self.helper), "seal-manifest", "--key-id", key_id,
                    "--snapshot-id", snapshot_id, "--output", str(sealed),
                ], input=json.dumps(manifest).encode(), check=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                reference = {
                    "format": "codex-vault-reference", "version": 1,
                    "snapshot_id": snapshot_id, "created_at": created_at,
                    "manifest": "manifests/" + sealed.name,
                }
                (destination / "refs" / (snapshot_id + ".json")).write_text(
                    json.dumps(reference), encoding="utf-8")
                (destination / "latest.json").write_text(
                    json.dumps(reference), encoding="utf-8")
                self.assertEqual(verify_snapshot(
                    str(destination), snapshot=snapshot_id,
                    crypto_helper=str(self.helper)).snapshot_id, snapshot_id)
                restore_snapshot(str(source), str(destination), str(restored),
                                 snapshot=snapshot_id, crypto_helper=str(self.helper))
                self.assertEqual((restored / "sessions/2026/09/17/active.jsonl").read_bytes(),
                                 transcript.read_bytes())
            finally:
                self.delete_key(destination)

    def test_restore_output_cannot_overlap_live_data_or_vault(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "vault"
            self.fixture(source)
            try:
                backup(
                    str(source), str(destination), crypto_helper=str(self.helper),
                    chunk_size=64 * 1024,
                )
                with self.assertRaisesRegex(MigrationError, "separate"):
                    restore_snapshot(
                        str(source), str(destination), str(source / ".codex/staged"),
                        crypto_helper=str(self.helper),
                    )
                with self.assertRaisesRegex(MigrationError, "separate"):
                    restore_snapshot(
                        str(source), str(destination), str(destination / "restored"),
                        crypto_helper=str(self.helper),
                    )
            finally:
                self.delete_key(destination)

    def test_destination_cannot_overlap_codex_data_or_follow_a_link(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            self.fixture(source)
            with self.assertRaisesRegex(MigrationError, "outside"):
                plan(str(source), str(source / ".codex/vault"))
            linked = root / "linked"
            linked.symlink_to(root / "real")
            with self.assertRaisesRegex(MigrationError, "linked"):
                plan(str(source), str(linked))


if __name__ == "__main__":
    unittest.main()
