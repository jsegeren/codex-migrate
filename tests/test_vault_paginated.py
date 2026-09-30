import json
from contextlib import closing
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from codex_migrate.errors import MigrationError
from codex_migrate.vault import markdown_chunks, read_thread_page, search
from codex_migrate.vault_paginated import (
    PaginatedItem, _canonical_macos_path, _sandbox_profile,
    encoded_item, open_paginated_source, restored_items,
    source_fingerprint, source_footprint,
)


THREAD_ID = "44444444-4444-4444-8444-444444444444"


def fixture(root: Path) -> Path:
    codex = root / ".codex"
    codex.mkdir()
    database = codex / "thread_history_1.sqlite"
    with closing(sqlite3.connect(database)) as connection:
        with connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("CREATE TABLE thread_items ("
                               "thread_id TEXT, turn_id TEXT, item_id TEXT, "
                               "rollout_ordinal INTEGER, created_at_ms INTEGER, "
                               "item_json TEXT, item_type TEXT, updated_at_ordinal INTEGER)")
            connection.execute("CREATE TABLE thread_history_projection_state ("
                               "thread_id TEXT, next_rollout_byte_offset INTEGER, "
                               "next_rollout_ordinal INTEGER)")
            connection.execute("INSERT INTO thread_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                               (THREAD_ID, "turn-1", "item-1", 1, 100,
                                json.dumps({"id": "item-1", "type": "userMessage",
                                            "content": [{"type": "text", "text": "synthetic private"}]}),
                                "userMessage", 1))
    return database


class PaginatedSourceTests(unittest.TestCase):
    def test_source_fingerprint_detects_database_change_and_unsafe_sidecar(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            database = fixture(home)
            before = source_fingerprint(str(home))
            self.assertIsNotNone(before)
            with sqlite3.connect(database) as connection:
                connection.execute("INSERT INTO thread_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                   (THREAD_ID, "turn-2", "item-2", 2, 200,
                                    json.dumps({"id": "item-2", "type": "userMessage"}),
                                    "userMessage", 2))
            self.assertNotEqual(source_fingerprint(str(home)), before)
            sidecar = Path(str(database) + "-journal")
            sidecar.symlink_to(home / "untrusted")
            with self.assertRaises(MigrationError):
                source_fingerprint(str(home))

    def test_orphaned_wal_is_not_treated_as_empty_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            (home / ".codex").mkdir()
            self.assertIsNone(source_fingerprint(str(home)))
            (home / ".codex/thread_history_1.sqlite-wal").write_bytes(b"orphan")
            with self.assertRaisesRegex(MigrationError, "orphaned"):
                source_fingerprint(str(home))

    def test_sandbox_denies_source_writes_with_unicode_and_quotes_in_home(self):
        with tempfile.TemporaryDirectory() as temporary:
            codex = Path(temporary) / 'José "safe"' / ".codex"
            codex.mkdir(parents=True)
            target = codex / "must-not-exist"
            profile = _sandbox_profile(_canonical_macos_path(codex))
            result = subprocess.run(
                ["/usr/bin/sandbox-exec", "-p", profile, sys.executable, "-c",
                 "from pathlib import Path; import sys; Path(sys.argv[1]).write_bytes(b'x')",
                 str(target)], capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(target.exists())

    def test_search_order_uses_newest_item_not_thread_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            database = fixture(home)
            newer = "55555555-5555-4555-8555-555555555555"
            with sqlite3.connect(database) as connection:
                connection.execute("INSERT INTO thread_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                   (newer, "turn-new", "item-new", 1, 200,
                                    json.dumps({"id": "item-new", "type": "userMessage",
                                                "text": "newer synthetic work"}),
                                    "userMessage", 1))
            with open_paginated_source(str(home)) as source:
                self.assertEqual(source.thread_ids(), [THREAD_ID, newer])
                self.assertEqual(source.thread_ids_recent(), [newer, THREAD_ID])
                self.assertEqual(source.thread_ids_recent_subset([THREAD_ID, newer]),
                                 [newer, THREAD_ID])
                self.assertEqual(source.thread_ids_recent_subset([THREAD_ID]), [THREAD_ID])
                self.assertEqual(source.thread_ids_recent_subset([]), [])

    def test_large_paginated_record_excerpts_and_can_continue(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            folder = home / ".codex/paginated_history"
            folder.mkdir(parents=True)
            items = [PaginatedItem(
                THREAD_ID, "turn-1", "item-" + str(index), index, 100 + index,
                "userMessage", json.dumps({"id": "item-" + str(index),
                                            "type": "userMessage",
                                            "content": [{"type": "text", "text": body}]}))
                for index, body in ((1, "A" * 200), (2, "later"))]
            (folder / (THREAD_ID + ".jsonl")).write_bytes(
                b"".join(encoded_item(item) for item in items))
            first, cursor = read_thread_page(
                str(home), "paginated", THREAD_ID + ".jsonl", max_text_bytes=64)
            self.assertTrue(first.entries[0].excerpted)
            self.assertEqual(cursor, 1)
            second, cursor = read_thread_page(
                str(home), "paginated", THREAD_ID + ".jsonl",
                cursor=1, max_text_bytes=64, expected_query="later")
            self.assertEqual([entry.text for entry in second.entries], ["later"])
            self.assertIsNone(cursor)

    def test_restored_record_rejects_truncation_and_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            folder = home / ".codex/paginated_history"
            folder.mkdir(parents=True)
            item = PaginatedItem(
                THREAD_ID, "turn-1", "item-1", 1, 100, "userMessage",
                json.dumps({"id": "item-1", "type": "userMessage",
                            "content": [{"type": "text", "text": "synthetic private"}]}))
            path = folder / (THREAD_ID + ".jsonl")
            path.write_bytes(encoded_item(item))
            self.assertEqual(list(restored_items(str(home), THREAD_ID)), [item])
            path.write_bytes(encoded_item(item)[:-1])
            with self.assertRaises(MigrationError):
                list(restored_items(str(home), THREAD_ID))
            path.rename(folder / "outside.jsonl")
            path.symlink_to(folder / "outside.jsonl")
            with self.assertRaises(MigrationError):
                list(restored_items(str(home), THREAD_ID))

    def test_reads_known_schema_and_preserves_original_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            database = fixture(home)
            before = database.read_bytes()
            with open_paginated_source(str(home)) as source:
                self.assertEqual(source.thread_ids(), [THREAD_ID])
                items = list(source.items(THREAD_ID))
                self.assertEqual(len(items), 1)
                self.assertEqual(items[0].item_type, "userMessage")
                self.assertEqual(items[0].rollout_ordinal, 1)
                self.assertEqual(json.loads(items[0].item_json)["content"][0]["text"],
                                 "synthetic private")
            self.assertEqual(database.read_bytes(), before)
            count, size, present = source_footprint(str(home))
            self.assertTrue(present)
            self.assertEqual(count, 1)
            self.assertGreaterEqual(size, len(before))

    def test_live_wal_read_cannot_change_codex_sidecars(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            database = fixture(home)
            writer = sqlite3.connect(database)
            try:
                writer.execute("PRAGMA wal_autocheckpoint=0")
                writer.execute("INSERT INTO thread_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                               (THREAD_ID, "turn-2", "item-2", 2, 101,
                                json.dumps({"id": "item-2", "type": "agentMessage",
                                            "text": "uncheckpointed synthetic reply"}),
                                "agentMessage", 2))
                writer.commit()
                paths = [database, Path(str(database) + "-wal"),
                         Path(str(database) + "-shm")]
                self.assertTrue(all(path.is_file() for path in paths))
                before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths]
                with open_paginated_source(str(home)) as source:
                    self.assertEqual([item.item_id for item in source.items(THREAD_ID)],
                                     ["item-1", "item-2"])
                self.assertEqual(
                    [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths], before)
            finally:
                writer.close()

    def test_wal_without_shared_memory_fails_without_creating_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            database = fixture(source)
            writer = sqlite3.connect(database)
            try:
                writer.execute("PRAGMA wal_autocheckpoint=0")
                writer.execute("INSERT INTO thread_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                               (THREAD_ID, "turn-2", "item-2", 2, 101,
                                json.dumps({"id": "item-2", "type": "agentMessage",
                                            "text": "uncheckpointed synthetic reply"}),
                                "agentMessage", 2))
                writer.commit()
                target = root / "target" / ".codex"
                target.mkdir(parents=True)
                staged = target / database.name
                shutil.copyfile(database, staged)
                shutil.copyfile(Path(str(database) + "-wal"),
                                Path(str(staged) + "-wal"))
                self.assertFalse(Path(str(staged) + "-shm").exists())
                with self.assertRaises(MigrationError):
                    with open_paginated_source(str(target.parent)):
                        pass
                self.assertFalse(Path(str(staged) + "-shm").exists())
            finally:
                writer.close()

    def test_ordinal_ranges_bound_live_and_restored_items(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            database = fixture(home)
            items = [PaginatedItem(
                THREAD_ID, "turn-1", "item-1", 1, 100, "userMessage",
                json.dumps({"id": "item-1", "type": "userMessage", "text": "first"}))]
            with sqlite3.connect(database) as connection:
                for ordinal in (2, 3):
                    item = PaginatedItem(
                        THREAD_ID, "turn-1", "item-" + str(ordinal), ordinal,
                        100 + ordinal, "userMessage",
                        json.dumps({"id": "item-" + str(ordinal),
                                    "type": "userMessage", "text": str(ordinal)}))
                    items.append(item)
                    connection.execute(
                        "INSERT INTO thread_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (item.thread_id, item.turn_id, item.item_id,
                         item.rollout_ordinal, item.created_at_ms, item.item_json,
                         item.item_type, item.rollout_ordinal))
            with open_paginated_source(str(home)) as source:
                self.assertEqual([item.rollout_ordinal for item in
                                  source.items_range(THREAD_ID, 2, 3)], [2])
                self.assertEqual([item.rollout_ordinal for item in
                                  source.items_range(THREAD_ID, 3, None)], [3])
                self.assertEqual(list(source.items_range(THREAD_ID, 2, 2)), [])
                with self.assertRaises(ValueError):
                    list(source.items_range(THREAD_ID, 3, 2))

            restored = home / ".codex/paginated_history"
            restored.mkdir()
            (restored / (THREAD_ID + ".jsonl")).write_bytes(
                b"".join(encoded_item(item) for item in items))
            self.assertEqual([item.rollout_ordinal for item in
                              restored_items(str(home), THREAD_ID, 2, 3)], [2])
            self.assertEqual([item.rollout_ordinal for item in
                              restored_items(str(home), THREAD_ID, 3)], [3])
            with self.assertRaises(ValueError):
                list(restored_items(str(home), THREAD_ID, 3, 2))

    def test_paginated_fork_search_reads_only_visible_database_ranges(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            database = fixture(home)
            child_id = "55555555-5555-4555-8555-555555555555"
            grandchild_id = "66666666-6666-4666-8666-666666666666"
            archived = home / ".codex/archived_sessions"
            active = home / ".codex/sessions"
            archived.mkdir()
            active.mkdir()

            def record(ordinal, kind, payload):
                return json.dumps({"ordinal": ordinal, "type": kind,
                                   "payload": payload}) + "\n"

            parent_prefix = (record(0, "session_meta", {"id": THREAD_ID})
                             + record(1, "event_msg", {"event": "metadata"}))
            parent_path = archived / ("rollout-" + THREAD_ID + ".jsonl")
            parent_path.write_text(
                parent_prefix + record(2, "event_msg", {"event": "later metadata"}))
            child_rollout = (
                record(2, "session_meta", {"id": child_id, "history_base": {
                    "thread_id": THREAD_ID, "end_ordinal_exclusive": 2,
                    "end_byte_offset": len(parent_prefix.encode()),
                }}) + record(3, "event_msg", {"event": "child metadata"}))
            (active / ("rollout-" + child_id + ".jsonl")).write_text(child_rollout)
            (active / ("rollout-" + grandchild_id + ".jsonl")).write_text(
                record(4, "session_meta", {"id": grandchild_id, "history_base": {
                    "thread_id": child_id, "end_ordinal_exclusive": 4,
                    "end_byte_offset": len(child_rollout.encode()),
                }}) + record(5, "event_msg", {"event": "grandchild metadata"}))
            with sqlite3.connect(database) as connection:
                for thread_id, ordinal, item_id, text in (
                        (THREAD_ID, 2, "item-later", "Parent database-only later"),
                        (child_id, 3, "item-child", "Child database-only turn"),
                        (grandchild_id, 5, "item-grandchild", "Grandchild database-only turn")):
                    connection.execute(
                        "INSERT INTO thread_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (thread_id, "turn-" + item_id, item_id, ordinal, 100 + ordinal,
                         json.dumps({"id": item_id, "type": "userMessage",
                                     "text": text}), "userMessage", ordinal))
            original = database.read_bytes()

            inherited = search(str(home), "synthetic private")
            self.assertEqual({match.transcript for match in inherited
                              if match.collection == "paginated"},
                             {THREAD_ID + ".jsonl", child_id + ".jsonl",
                              grandchild_id + ".jsonl"})
            later = search(str(home), "Parent database-only later")
            self.assertEqual({match.transcript for match in later
                              if match.collection == "paginated"},
                             {THREAD_ID + ".jsonl"})
            page, _ = read_thread_page(str(home), "paginated", child_id + ".jsonl",
                                       live_paginated=True)
            self.assertEqual([entry.text for entry in page.entries],
                             ["synthetic private", "Child database-only turn"])
            grandchild_page, _ = read_thread_page(
                str(home), "paginated", grandchild_id + ".jsonl",
                live_paginated=True)
            self.assertEqual([entry.text for entry in grandchild_page.entries],
                             ["synthetic private", "Child database-only turn",
                              "Grandchild database-only turn"])
            with open_paginated_source(str(home)) as source:
                exported = b"".join(markdown_chunks(
                    str(home), "paginated", child_id + ".jsonl",
                    live_paginated_source=source))
            self.assertIn(b"synthetic private", exported)
            self.assertNotIn(b"Parent database-only later", exported)
            self.assertEqual(database.read_bytes(), original)
            parent_path.rename(archived / "unavailable.jsonl")
            with self.assertRaisesRegex(MigrationError, "parent is missing"):
                read_thread_page(str(home), "paginated", child_id + ".jsonl",
                                 live_paginated=True)

    def test_footprint_refuses_linked_wal(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            home.mkdir()
            database = fixture(home)
            outside = Path(temporary) / "outside-wal"
            outside.write_bytes(b"not a database journal")
            wal = database.parent / (database.name + "-wal")
            if wal.exists():
                wal.unlink()  # Disposable fixture only; test the linked-WAL guard.
            wal.symlink_to(outside)
            with self.assertRaises(MigrationError):
                source_footprint(str(home))

    def test_reader_refuses_linked_sqlite_sidecars(self):
        for suffix in ("-wal", "-shm", "-journal"):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as temporary:
                home = Path(temporary) / "home"
                home.mkdir()
                database = fixture(home)
                outside = Path(temporary) / "outside-sidecar"
                outside.write_bytes(b"unrelated private data")
                sidecar = Path(str(database) + suffix)
                if sidecar.exists():
                    sidecar.unlink()  # Disposable fixture only.
                sidecar.symlink_to(outside)
                with self.assertRaises(MigrationError):
                    with open_paginated_source(str(home)):
                        pass
                self.assertEqual(outside.read_bytes(), b"unrelated private data")

    def test_read_transaction_does_not_mix_later_writes_into_a_thread(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            database = fixture(home)
            with open_paginated_source(str(home)) as source:
                self.assertEqual(source.thread_ids(), [THREAD_ID])
                with sqlite3.connect(database) as writer:
                    writer.execute("INSERT INTO thread_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                   (THREAD_ID, "turn-1", "item-2", 2, 101,
                                    json.dumps({"id": "item-2", "type": "agentMessage",
                                                "text": "later synthetic reply"}),
                                    "agentMessage", 2))
                self.assertEqual([item.item_id for item in source.items(THREAD_ID)],
                                 ["item-1"])
            with open_paginated_source(str(home)) as source:
                self.assertEqual([item.item_id for item in source.items(THREAD_ID)],
                                 ["item-1", "item-2"])

    def test_unknown_schema_and_corrupt_item_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            database = fixture(home)
            with sqlite3.connect(database) as connection:
                connection.execute("UPDATE thread_items SET item_json='not JSON'")
            with open_paginated_source(str(home)) as source:
                with self.assertRaises(MigrationError):
                    list(source.items(THREAD_ID))
            with sqlite3.connect(database) as connection:
                connection.execute("DROP TABLE thread_history_projection_state")
            with self.assertRaises(MigrationError):
                with open_paginated_source(str(home)):
                    pass

    def test_source_links_are_rejected_without_reading_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            home.mkdir()
            database = fixture(home)
            outside = Path(temporary) / "outside.sqlite"
            database.rename(outside)
            database.symlink_to(outside)
            with self.assertRaises(MigrationError):
                with open_paginated_source(str(home)):
                    pass
            self.assertTrue(outside.is_file())


if __name__ == "__main__":
    unittest.main()
