import json
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import random
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from codex_migrate.errors import MigrationError
from codex_migrate.vault import _transcripts, search
from codex_migrate.vault_search_index import (
    IndexCancelled, _path, build, candidates, paginated_candidates, remove, supported,
)


def write_thread(path: Path, *texts: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps({"payload": {"message": {"content": text}}}) + "\n"
                            for text in texts), encoding="utf-8")


def write_paginated(home: Path, items) -> Path:
    database = home / ".codex/thread_history_1.sqlite"
    database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE thread_items (thread_id TEXT, turn_id TEXT, "
                           "item_id TEXT, rollout_ordinal INTEGER, created_at_ms INTEGER, "
                           "item_json TEXT, item_type TEXT, updated_at_ordinal INTEGER)")
        connection.execute("CREATE TABLE thread_history_projection_state ("
                           "thread_id TEXT, next_rollout_byte_offset INTEGER, "
                           "next_rollout_ordinal INTEGER)")
        for thread_id, ordinal, text in items:
            item_id = "item-" + str(ordinal)
            connection.execute("INSERT INTO thread_items VALUES (?,?,?,?,?,?,?,?)", (
                thread_id, "turn-1", item_id, ordinal, ordinal,
                json.dumps({"id": item_id, "type": "userMessage", "text": text}),
                "userMessage", ordinal))
    return database


class SearchIndexTests(unittest.TestCase):
    @unittest.skipUnless(supported(), "requires SQLite FTS5 contentless-delete")
    def test_cli_reports_database_index_coverage(self):
        from codex_migrate.cli import main

        with tempfile.TemporaryDirectory() as temporary:
            thread_id = "11111111-1111-4111-8111-111111111111"
            write_paginated(Path(temporary), ((thread_id, 1, "Clerk history"),))
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["vault", "--source-home", temporary,
                                       "search-index", "--apply"]), 0)
            self.assertIn("Database-backed threads: 1 (indexed)", output.getvalue())

    def test_cli_discloses_partial_search_without_breaking_json_output(self):
        from codex_migrate.cli import main

        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            ambiguous = "11111111-1111-4111-8111-111111111111"
            clear = "22222222-2222-4222-8222-222222222222"
            for folder in ("sessions", "archived_sessions"):
                path = home / ".codex" / folder / ("rollout-" + ambiguous + ".jsonl")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"type": "session_meta", "payload": {
                    "id": ambiguous, "source": folder}}) + "\n", encoding="utf-8")
            write_paginated(home, ((ambiguous, 1, "Ambiguous work"),
                                   (clear, 2, "Clerk source")))
            output, errors = io.StringIO(), io.StringIO()
            with redirect_stdout(output), redirect_stderr(errors):
                self.assertEqual(main(["vault", "--source-home", temporary,
                                       "search", "Clerk", "--json"]), 0)
            self.assertEqual([item["transcript"] for item in json.loads(output.getvalue())],
                             [clear + ".jsonl"])
            self.assertIn("ambiguous history copies", errors.getvalue())
            self.assertIn("inherited text was not searched", errors.getvalue())

    @unittest.skipUnless(supported(), "requires SQLite FTS5 contentless-delete")
    def test_index_refuses_to_consume_the_last_five_gigabytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / ".codex/sessions/one.jsonl"
            write_thread(source, "Clerk history")
            with patch("codex_migrate.vault_search_index.shutil.disk_usage",
                       return_value=SimpleNamespace(free=4 * 1024**3)):
                with self.assertRaisesRegex(MigrationError, "last 5 GB"):
                    build(temporary, apply=True)
            self.assertFalse(_path(temporary).exists())
            self.assertEqual(len(search(temporary, "Clerk")), 1)

    @unittest.skipUnless(supported(), "requires SQLite FTS5 contentless-delete")
    def test_paginated_index_is_complete_only_for_unchanged_database(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            first = "11111111-1111-4111-8111-111111111111"
            second = "22222222-2222-4222-8222-222222222222"
            database = write_paginated(home, ((first, 1, "Clerk launch"),
                                              (second, 2, "Straße planning")))
            self.assertIsNone(paginated_candidates(temporary, "Clerk"))
            result = build(temporary, apply=True)
            self.assertTrue(result["paginated_indexed"])
            self.assertEqual(result["paginated_threads"], 2)
            self.assertEqual(paginated_candidates(temporary, "Clerk"), {first})
            self.assertEqual(paginated_candidates(temporary, "STRASSE"), {second})
            self.assertEqual([(item.collection, item.transcript)
                              for item in search(temporary, "Clerk")],
                             [("paginated", first + ".jsonl")])
            with patch("codex_migrate.vault_paginated.PaginatedSource.items_range",
                       side_effect=AssertionError("indexed no-hit scanned SQLite items")):
                self.assertEqual(search(temporary, "not-present"), [])
            with sqlite3.connect(database) as connection:
                connection.execute("INSERT INTO thread_items VALUES (?,?,?,?,?,?,?,?)", (
                    second, "turn-2", "item-3", 3, 3,
                    json.dumps({"id": "item-3", "type": "userMessage",
                                "text": "Clerk follow-up"}), "userMessage", 3))
            self.assertIsNone(paginated_candidates(temporary, "Clerk"))
            self.assertEqual({item.transcript for item in search(temporary, "Clerk")},
                             {first + ".jsonl", second + ".jsonl"})
            build(temporary, apply=True)
            self.assertEqual(paginated_candidates(temporary, "Clerk"), {first, second})

    @unittest.skipUnless(supported(), "requires SQLite FTS5 contentless-delete")
    def test_database_change_during_index_build_cannot_publish_stale_candidates(self):
        import codex_migrate.vault_search_index as index

        with tempfile.TemporaryDirectory() as temporary:
            thread_id = "11111111-1111-4111-8111-111111111111"
            database = write_paginated(Path(temporary), ((thread_id, 1, "Earlier work"),))
            with sqlite3.connect(database) as connection:
                connection.execute("PRAGMA journal_mode=WAL")
            original = index._add_paginated_thread
            changed = False

            def change_after_read(connection, source, current_id, cache_parent,
                                  cancelled=None):
                nonlocal changed
                blocks = original(connection, source, current_id, cache_parent, cancelled)
                if not changed:
                    changed = True
                    with sqlite3.connect(database) as writer:
                        writer.execute("INSERT INTO thread_items VALUES (?,?,?,?,?,?,?,?)", (
                            thread_id, "turn-2", "item-2", 2, 2,
                            json.dumps({"id": "item-2", "type": "userMessage",
                                        "text": "New Clerk detail"}), "userMessage", 2))
                return blocks

            with patch.object(index, "_add_paginated_thread", change_after_read):
                result = build(temporary, apply=True)
            self.assertTrue(result["paginated_skipped"])
            self.assertIsNone(paginated_candidates(temporary, "Clerk"))
            self.assertEqual([item.transcript for item in search(temporary, "Clerk")],
                             [thread_id + ".jsonl"])

    @unittest.skipUnless(supported(), "requires SQLite FTS5 contentless-delete")
    def test_new_message_before_read_view_cannot_be_hidden_by_old_index(self):
        import codex_migrate.vault_paginated as paginated

        with tempfile.TemporaryDirectory() as temporary:
            thread_id = "11111111-1111-4111-8111-111111111111"
            database = write_paginated(Path(temporary), ((thread_id, 1, "Earlier work"),))
            build(temporary, apply=True)
            self.assertEqual(paginated_candidates(temporary, "Clerk"), set())
            open_source = paginated.open_paginated_source

            @contextmanager
            def changed_before_read_view(source_home):
                with sqlite3.connect(database) as connection:
                    connection.execute("INSERT INTO thread_items VALUES (?,?,?,?,?,?,?,?)", (
                        thread_id, "turn-2", "item-2", 2, 2,
                        json.dumps({"id": "item-2", "type": "userMessage",
                                    "text": "New Clerk detail"}), "userMessage", 2))
                with open_source(source_home) as source:
                    yield source

            with patch.object(paginated, "open_paginated_source",
                              changed_before_read_view):
                self.assertEqual([item.transcript for item in search(temporary, "Clerk")],
                                 [thread_id + ".jsonl"])

    @unittest.skipUnless(supported(), "requires SQLite FTS5 contentless-delete")
    def test_paginated_fork_search_uses_parent_rollout_candidates(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            parent_id = "11111111-1111-4111-8111-111111111111"
            child_id = "22222222-2222-4222-8222-222222222222"
            parent = home / ".codex/archived_sessions" / ("rollout-" + parent_id + ".jsonl")
            child = home / ".codex/sessions" / ("rollout-" + child_id + ".jsonl")
            parent.parent.mkdir(parents=True)
            child.parent.mkdir(parents=True)
            prefix = (json.dumps({"type": "session_meta", "ordinal": 0,
                                  "payload": {"id": parent_id}}) + "\n"
                      + json.dumps({"type": "event_msg", "ordinal": 1,
                                    "payload": {"type": "note"}}) + "\n")
            parent.write_text(prefix, encoding="utf-8")
            child.write_text(json.dumps({"type": "session_meta", "ordinal": 2,
                                         "payload": {"id": child_id, "history_base": {
                                             "thread_id": parent_id,
                                             "end_ordinal_exclusive": 2,
                                             "end_byte_offset": len(prefix.encode())}}})
                             + "\n", encoding="utf-8")
            write_paginated(home, ((parent_id, 1, "Inherited Clerk plan"),
                                   (child_id, 3, "Child-local work")))
            build(temporary, apply=True)
            self.assertEqual(paginated_candidates(temporary, "Clerk"), {parent_id})
            self.assertEqual({item.transcript for item in search(temporary, "Clerk")
                              if item.collection == "paginated"},
                             {parent_id + ".jsonl", child_id + ".jsonl"})

    def test_plan_does_not_create_a_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            write_thread(home / ".codex/sessions/one.jsonl", "Find the launch note")
            plan = build(temporary)
            self.assertFalse(plan["applied"])
            self.assertFalse(_path(temporary).exists())
            self.assertEqual(len(search(temporary, "launch")), 1)

    def test_unsupported_sqlite_refuses_only_the_optional_index(self):
        with tempfile.TemporaryDirectory() as temporary:
            write_thread(Path(temporary) / ".codex/sessions/one.jsonl", "Clerk history")
            with patch("codex_migrate.vault_search_index.supported", return_value=False):
                with self.assertRaisesRegex(MigrationError, "unavailable"):
                    build(temporary, apply=True)
            self.assertFalse(_path(temporary).exists())
            self.assertEqual(len(search(temporary, "Clerk")), 1)

    def test_unreadable_cache_folder_falls_back_to_source_search(self):
        with tempfile.TemporaryDirectory() as temporary:
            write_thread(Path(temporary) / ".codex/sessions/one.jsonl", "Clerk history")
            with patch("codex_migrate.vault_search_index._safe_parent",
                       side_effect=PermissionError("cache folder unavailable")):
                self.assertEqual(len(search(temporary, "Clerk")), 1)

    def test_unreadable_codex_title_index_does_not_block_full_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            write_thread(home / ".codex/sessions/one.jsonl", "Clerk history survives")
            (home / ".codex/session_index.jsonl").write_bytes(b"not-json\n")
            results = search(temporary, "Clerk")
            self.assertEqual([item.transcript for item in results], ["one.jsonl"])
            with self.assertRaisesRegex(MigrationError, "title index is unreadable"):
                search(temporary, "Clerk", titles_only=True)

    @unittest.skipUnless(supported(), "requires SQLite FTS5 contentless-delete")
    def test_clear_requires_apply_and_keeps_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            thread = Path(temporary) / ".codex/sessions/one.jsonl"
            write_thread(thread, "Clerk history")
            build(temporary, apply=True)
            sidecar = Path(str(_path(temporary)) + "-journal")
            sidecar.write_bytes(b"synthetic interrupted transaction")
            sidecar.chmod(0o600)
            self.assertTrue(remove(temporary)["present"])
            self.assertTrue(_path(temporary).exists())
            self.assertTrue(remove(temporary, apply=True)["applied"])
            self.assertFalse(_path(temporary).exists())
            self.assertFalse(sidecar.exists())
            self.assertEqual(len(search(temporary, "Clerk")), 1)
            self.assertTrue(thread.exists())

    @unittest.skipUnless(supported(), "requires SQLite FTS5 contentless-delete")
    def test_opt_in_index_preserves_exact_results_and_is_owner_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            write_thread(home / ".codex/sessions/one.jsonl", "Clerk configuration", "Revisit launch")
            write_thread(home / ".codex/archived_sessions/two.jsonl", "A clerkly retrospective")
            baseline = [(item.collection, item.transcript, item.line)
                        for item in search(temporary, "clerk")]
            result = build(temporary, apply=True)
            self.assertTrue(result["applied"])
            self.assertEqual(result["indexed"], 2)
            self.assertEqual(_path(temporary).stat().st_mode & 0o077, 0)
            self.assertEqual(_path(temporary).parent.stat().st_mode & 0o077, 0)
            self.assertEqual([(item.collection, item.transcript, item.line)
                              for item in search(temporary, "clerk")], baseline)
            self.assertEqual(len(search(temporary, "lerk")), 2)
            self.assertEqual(search(temporary, "not-present"), [])
            self.assertEqual(len(candidates(temporary, "clerk", list(_transcripts(temporary)))), 2)
            self.assertEqual(candidates(temporary, "not-present", list(_transcripts(temporary))),
                             set())
            connection = sqlite3.connect(str(_path(temporary)))
            try:
                # FTS is contentless: original message bodies are not retrievable from the cache.
                self.assertEqual(connection.execute("SELECT body FROM text_terms LIMIT 1").fetchone(),
                                 (None,))
            finally:
                connection.close()

    @unittest.skipUnless(supported(), "requires SQLite FTS5 contentless-delete")
    def test_changed_and_new_files_are_scanned_until_explicit_refresh(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            first = home / ".codex/sessions/one.jsonl"
            second = home / ".codex/sessions/two.jsonl"
            write_thread(first, "Earlier work")
            build(temporary, apply=True)
            self.assertEqual(search(temporary, "Clerk"), [])
            with first.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"payload": {"message": {"content": "Clerk appended"}}})
                             + "\n")
            write_thread(second, "Clerk new thread")
            self.assertEqual({item.transcript for item in search(temporary, "Clerk")},
                             {"one.jsonl", "two.jsonl"})
            refreshed = build(temporary, apply=True)
            self.assertEqual(refreshed["indexed"], 2)
            self.assertEqual({item.transcript for item in search(temporary, "Clerk")},
                             {"one.jsonl", "two.jsonl"})
            first.unlink()
            self.assertEqual([item.transcript for item in search(temporary, "Clerk")],
                             ["two.jsonl"])

    @unittest.skipUnless(supported(), "requires SQLite FTS5 contentless-delete")
    def test_live_append_skips_only_changing_file_and_searches_it_directly(self):
        import codex_migrate.vault as vault

        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            first = home / ".codex/sessions/a.jsonl"
            second = home / ".codex/sessions/b.jsonl"
            write_thread(first, "Clerk first")
            write_thread(second, "Clerk second")
            first = list(_transcripts(temporary))[0][1]
            original_strings = vault._strings
            changed = False

            def append_while_reading(record, *args):
                nonlocal changed
                yield from original_strings(record, *args)
                if not changed:
                    changed = True
                    with first.open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps({"message": {"content": "Clerk appended"}})
                                     + "\n")

            with patch("codex_migrate.vault._strings", append_while_reading):
                result = build(temporary, apply=True)
            self.assertEqual(result["skipped"], 1)
            self.assertEqual(result["indexed"], 1)
            self.assertEqual({item.transcript for item in search(temporary, "Clerk")},
                             {"a.jsonl", "b.jsonl"})
            self.assertEqual(build(temporary, apply=True)["skipped"], 0)

    @unittest.skipUnless(supported(), "requires SQLite FTS5 contentless-delete")
    def test_unicode_casefold_and_long_string_boundary(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            thread = home / ".codex/sessions/long.jsonl"
            phrase = "Unification Foundation"
            write_thread(thread, "A" * (128 * 1024 - 10) + phrase + "B" * 700,
                         "Straße and its history")
            build(temporary, apply=True)
            self.assertEqual(len(search(temporary, phrase)), 1)
            self.assertEqual(len(search(temporary, "STRASSE")), 1)
            self.assertEqual(len(search(temporary, "AI")), 0)  # Short queries use full scan.

    @unittest.skipUnless(supported(), "requires SQLite FTS5 contentless-delete")
    def test_text_after_nul_remains_searchable(self):
        with tempfile.TemporaryDirectory() as temporary:
            thread = Path(temporary) / ".codex/sessions/nul.jsonl"
            write_thread(thread, "Before\x00Clerk after NUL")
            build(temporary, apply=True)
            self.assertEqual(len(search(temporary, "Clerk")), 1)
            self.assertEqual(len(search(temporary, "\x00Clerk")), 1)

    @unittest.skipUnless(supported(), "requires SQLite FTS5 contentless-delete")
    def test_index_candidates_never_drop_synthetic_unicode_substrings(self):
        generator = random.Random(92226)
        alphabet = 'abCde  .,#"\\\n\t\x00\x01éßK移行🧠🚀'
        texts = ["".join(generator.choice(alphabet) for _ in range(150))
                 for _ in range(12)]
        with tempfile.TemporaryDirectory() as temporary:
            thread = Path(temporary) / ".codex/sessions/varied.jsonl"
            write_thread(thread, *texts)
            build(temporary, apply=True)
            discovered = list(_transcripts(temporary))
            for text in texts:
                folded = text.casefold()
                for _ in range(30):
                    start = generator.randrange(len(folded) - 3)
                    query = folded[start:start + generator.randrange(3, 9)]
                    if len(query) < 3 or "\x00" in query:
                        continue
                    self.assertIn(thread, candidates(temporary, query, discovered))

    @unittest.skipUnless(supported(), "requires SQLite FTS5 contentless-delete")
    def test_unsafe_or_corrupt_cache_never_hides_source_results(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            write_thread(home / ".codex/sessions/one.jsonl", "Clerk source text")
            build(temporary, apply=True)
            os.chmod(_path(temporary), 0o644)
            self.assertEqual(len(search(temporary, "Clerk")), 1)
            with self.assertRaisesRegex(MigrationError, "unsafe"):
                build(temporary, apply=True)
            os.chmod(_path(temporary), 0o600)
            _path(temporary).write_bytes(b"not a sqlite database")
            self.assertEqual(len(search(temporary, "Clerk")), 1)

    @unittest.skipUnless(supported(), "requires SQLite FTS5 contentless-delete")
    def test_failed_refresh_keeps_last_committed_index_and_full_search_detects_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            thread = home / ".codex/sessions/one.jsonl"
            write_thread(thread, "Clerk original")
            build(temporary, apply=True)
            with thread.open("a", encoding="utf-8") as handle:
                handle.write("not-json\n")
            with self.assertRaisesRegex(MigrationError, "unreadable JSON"):
                build(temporary, apply=True)
            with self.assertRaisesRegex(MigrationError, "unreadable JSON"):
                search(temporary, "missing")

    @unittest.skipUnless(supported(), "requires SQLite FTS5 contentless-delete")
    def test_stopping_after_one_file_keeps_search_complete(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            write_thread(home / ".codex/sessions/a.jsonl", "Clerk first")
            write_thread(home / ".codex/sessions/b.jsonl", "Clerk second")
            stop = threading.Event()

            def progress(completed, total):
                self.assertEqual(total, 2)
                if completed == 1:
                    stop.set()

            with self.assertRaises(IndexCancelled):
                build(temporary, apply=True, progress=progress, cancelled=stop)
            self.assertEqual({item.transcript for item in search(temporary, "Clerk")},
                             {"a.jsonl", "b.jsonl"})
            self.assertEqual(build(temporary, apply=True)["indexed"], 1)

    @unittest.skipUnless(supported(), "requires SQLite FTS5 contentless-delete")
    def test_parent_match_remains_visible_in_a_paginated_child(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            active = home / ".codex/sessions"
            archived = home / ".codex/archived_sessions"
            active.mkdir(parents=True)
            archived.mkdir(parents=True)
            parent_id = "11111111-1111-4111-8111-111111111111"
            child_id = "22222222-2222-4222-8222-222222222222"
            parent = archived / ("rollout-" + parent_id + ".jsonl")
            child = active / ("rollout-" + child_id + ".jsonl")

            def line(kind, ordinal, payload):
                return json.dumps({"type": kind, "ordinal": ordinal,
                                   "payload": payload}) + "\n"

            prefix = (line("session_meta", 0, {"id": parent_id})
                      + line("response_item", 1, {"type": "message", "role": "user",
                                                  "content": "Inherited Clerk plan"}))
            parent.write_text(prefix + line("response_item", 2, {
                "type": "message", "role": "assistant", "content": "Later parent text"}),
                encoding="utf-8")
            child.write_text(line("session_meta", 2, {"id": child_id, "history_base": {
                "thread_id": parent_id, "end_ordinal_exclusive": 2,
                "end_byte_offset": len(prefix.encode("utf-8"))}})
                + line("response_item", 3, {"type": "message", "role": "user",
                                             "content": "Child-local work"}), encoding="utf-8")
            build(temporary, apply=True)
            matches = search(temporary, "Inherited Clerk")
            self.assertEqual({(item.collection, item.transcript) for item in matches},
                             {("active", child.name), ("archived", parent.name)})


if __name__ == "__main__":
    unittest.main()
