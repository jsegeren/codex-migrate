import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from codex_migrate.errors import MigrationError
from codex_migrate.vault_paginated import open_paginated_source


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
