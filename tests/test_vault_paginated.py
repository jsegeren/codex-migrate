import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from codex_migrate.errors import MigrationError
from codex_migrate.vault import read_thread_page
from codex_migrate.vault_paginated import (
    PaginatedItem, encoded_item, open_paginated_source, restored_items,
    source_footprint,
)


THREAD_ID = "44444444-4444-4444-8444-444444444444"


def fixture(root: Path) -> Path:
    codex = root / ".codex"
    codex.mkdir()
    database = codex / "thread_history_1.sqlite"
    with sqlite3.connect(database) as connection:
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
