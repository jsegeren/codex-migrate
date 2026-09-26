import json
import os
from pathlib import Path
import random
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from codex_migrate.errors import MigrationError
from codex_migrate.vault import _transcripts, search
from codex_migrate.vault_search_index import (
    IndexCancelled, _path, build, candidates, remove, supported,
)


def write_thread(path: Path, *texts: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps({"payload": {"message": {"content": text}}}) + "\n"
                            for text in texts), encoding="utf-8")


class SearchIndexTests(unittest.TestCase):
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
