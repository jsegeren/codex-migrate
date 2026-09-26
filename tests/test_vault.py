import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest

from codex_migrate.errors import MigrationError
from codex_migrate.vault import inspect, markdown, markdown_chunks, read_thread, read_thread_page, search
from codex_migrate.vault_identity import scan_transcript


class VaultTests(unittest.TestCase):
    def fixture(self, root: Path) -> None:
        active = root / ".codex/sessions/2026/09/17/active.jsonl"
        archived = root / ".codex/archived_sessions/archived.jsonl"
        active.parent.mkdir(parents=True)
        archived.parent.mkdir(parents=True)
        active.write_text(
            json.dumps({
                "timestamp": "2026-09-17T10:00:00Z",
                "payload": {"message": {"content": "Design the launch checklist."}},
            }) + "\n" +
            json.dumps({"payload": {"cwd": "/private/customer/path", "id": "secret-id"}}) + "\n",
            encoding="utf-8",
        )
        archived.write_text(
            json.dumps({"payload": {"text": "Archived launch retrospective."}}) + "\n",
            encoding="utf-8",
        )

    def test_inspect_counts_only_transcript_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            (root / ".codex/sessions/ignore.txt").write_text("launch", encoding="utf-8")
            result = inspect(str(root))
            self.assertEqual(result.active_transcripts, 1)
            self.assertEqual(result.archived_transcripts, 1)
            self.assertGreater(result.transcript_bytes, 0)

    def test_search_finds_message_text_without_searching_paths_or_ids(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            results = search(str(root), "launch", limit=10)
            self.assertEqual(len(results), 2)
            active = next(result for result in results if result.collection == "active")
            self.assertEqual(active.timestamp, "2026-09-17T10:00:00Z")
            self.assertIn("launch checklist", active.snippet)
            self.assertEqual(search(str(root), "private/customer", limit=10), [])
            self.assertEqual(search(str(root), "secret-id", limit=10), [])

    def test_common_word_returns_recent_distinct_threads_not_old_message_hits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / ".codex/sessions"
            folder.mkdir(parents=True)
            for index in range(60):
                thread = folder / ("thread-%02d.jsonl" % index)
                thread.write_text(
                    (json.dumps({"payload": {"message": {"content": "Clerk setup %d" % index}}})
                     + "\n") * 3,
                    encoding="utf-8",
                )
                timestamp = 1_000_000_000 + index
                os.utime(thread, (timestamp, timestamp))
            current = folder / "current.jsonl"
            current.write_text(json.dumps({"payload": {"message": {
                "content": "Current Clerk authentication work"}}}) + "\n", encoding="utf-8")
            os.utime(current, (2_000_000_000, 2_000_000_000))
            matches = search(str(root), "clerk", limit=50)
            self.assertEqual(len(matches), 50)
            self.assertEqual(matches[0].transcript, "current.jsonl")
            self.assertEqual(len({match.transcript for match in matches}), 50)
            self.assertTrue(all(match.collection == "active" for match in matches))
            older = search(str(root), "clerk", limit=50, offset=50)
            self.assertEqual(len(older), 11)
            self.assertFalse({match.transcript for match in matches}
                             & {match.transcript for match in older})

    @unittest.skipUnless(
        os.environ.get("CODEX_MIGRATE_LARGE_HISTORY_PROBE") == "1",
        "opt-in physical large-history probe",
    )
    def test_large_history_search_finds_old_and_new_message_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / ".codex/sessions/2026/09/24"
            folder.mkdir(parents=True)
            for index in range(2048):
                text = f"Synthetic conversation {index:04d}"
                if index == 7:
                    text += " buried-unification-foundation"
                if index == 2047:
                    text += " recent-unification-foundation"
                transcript = folder / f"thread-{index:04d}.jsonl"
                transcript.write_text(
                    json.dumps({"payload": {"message": {"content": text}}}) + "\n",
                    encoding="utf-8",
                )
                timestamp = 1_000_000_000 + index
                os.utime(transcript, (timestamp, timestamp))

            started = time.monotonic()
            matches = search(str(root), "unification-foundation", limit=25)
            elapsed = time.monotonic() - started
            self.assertEqual(
                [match.transcript for match in matches],
                ["2026/09/24/thread-2047.jsonl", "2026/09/24/thread-0007.jsonl"],
            )
            self.assertTrue(all(match.line == 1 for match in matches))
            self.assertLess(elapsed, 10, f"2,048-thread synthetic search took {elapsed:.2f}s")

    def test_search_result_includes_current_title_when_indexed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex = root / ".codex"
            folder = codex / "sessions"
            folder.mkdir(parents=True)
            thread_id = "11111111-1111-4111-8111-111111111111"
            (folder / ("rollout-" + thread_id + ".jsonl")).write_text(
                json.dumps({"payload": {"message": {"content": "Clerk setup"}}}) + "\n",
                encoding="utf-8",
            )
            (codex / "session_index.jsonl").write_text(
                json.dumps({"id": thread_id, "thread_name": "Old sign-in title"}) + "\n"
                + json.dumps({"id": thread_id, "thread_name": "Current sign-in title"}) + "\n",
                encoding="utf-8",
            )
            result = search(str(root), "clerk", limit=10)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0].title, "Current sign-in title")
            old_name = search(str(root), "Old sign-in", limit=10, titles_only=True)
            self.assertEqual(len(old_name), 1)
            self.assertEqual(old_name[0].title, "Current sign-in title")
            self.assertEqual(search(str(root), "clerk", limit=10, titles_only=True), [])

    def test_search_finds_text_appended_to_an_active_thread(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / ".codex/sessions"
            folder.mkdir(parents=True)
            thread = folder / "active.jsonl"
            thread.write_text(
                json.dumps({"payload": {"message": {"content": "Earlier work"}}}) + "\n"
                + json.dumps({"payload": {"message": {"content": "Set up Clerk now"}}}) + "\n",
                encoding="utf-8",
            )
            result = search(str(root), "clerk", limit=10)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0].collection, "active")
            self.assertEqual(result[0].line, 2)
            self.assertIn("Clerk", result[0].snippet)
            self.assertGreater(result[0].cursor, 0)
            page, _ = read_thread_page(
                str(root), "active", "active.jsonl", result[0].cursor,
                expected_query="clerk")
            self.assertEqual([entry.text for entry in page.entries], ["Set up Clerk now"])
            with self.assertRaisesRegex(MigrationError, "changed since the search"):
                read_thread_page(str(root), "active", "active.jsonl", result[0].cursor,
                                 expected_query="missing")

    def test_search_can_open_an_excerpt_when_matching_message_is_too_large(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transcript = root / ".codex/sessions/large.jsonl"
            transcript.parent.mkdir(parents=True)
            body = "A" * (1024 * 1024) + "Clerk marker" + "B" * (1024 * 1024)
            transcript.write_text(
                json.dumps({"payload": {"message": {"content": "Earlier work"}}}) + "\n"
                + json.dumps({"payload": {"message": {"content": body}}}) + "\n",
                encoding="utf-8",
            )
            match = search(str(root), "clerk", limit=1)[0]
            page, next_cursor = read_thread_page(
                str(root), "active", "large.jsonl", match.cursor,
                expected_query="clerk")
            self.assertIsNone(next_cursor)
            self.assertEqual(len(page.entries), 1)
            self.assertTrue(page.entries[0].excerpted)
            self.assertIn("Clerk marker", page.entries[0].text)
            self.assertLess(len(page.entries[0].text), 2000)
            with self.assertRaisesRegex(MigrationError, "too large to preview"):
                read_thread_page(str(root), "active", "large.jsonl", match.cursor)
            transcript.write_text(json.dumps({"payload": {"message": {"content": body}}}) + "\n",
                                  encoding="utf-8")
            first_match = search(str(root), "clerk", limit=1)[0]
            self.assertEqual(first_match.cursor, 0)
            first_page, _ = read_thread_page(
                str(root), "active", "large.jsonl", first_match.cursor,
                expected_query="clerk")
            self.assertTrue(first_page.entries[0].excerpted)
            self.assertIn("Clerk marker", first_page.entries[0].text)

    def test_search_rejects_linked_transcript(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sessions = root / ".codex/sessions"
            sessions.mkdir(parents=True)
            target = root / "outside.jsonl"
            target.write_text(json.dumps({"text": "launch"}) + "\n", encoding="utf-8")
            (sessions / "linked.jsonl").symlink_to(target)
            with self.assertRaisesRegex(MigrationError, "not a regular file"):
                search(str(root), "launch")

    def test_search_stops_on_invalid_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transcript = root / ".codex/sessions/broken.jsonl"
            transcript.parent.mkdir(parents=True)
            transcript.write_text("not-json\n", encoding="utf-8")
            with self.assertRaisesRegex(MigrationError, "unreadable JSON"):
                search(str(root), "anything")

    def test_search_validates_query_and_limit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            with self.assertRaisesRegex(ValueError, "must not be empty"):
                search(str(root), " ")
            with self.assertRaisesRegex(ValueError, "between 1 and 500"):
                search(str(root), "launch", limit=0)
            with self.assertRaisesRegex(ValueError, "offset must be"):
                search(str(root), "launch", offset=-1)

    def test_reads_exact_discovered_thread_and_exports_markdown(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            thread = read_thread(
                str(root), "active", "2026/09/17/active.jsonl")
            self.assertEqual(thread.collection, "active")
            self.assertEqual(len(thread.entries), 1)
            self.assertEqual(thread.entries[0].text, "Design the launch checklist.")
            document = markdown(thread)
            self.assertIn("# Codex conversation", document)
            self.assertIn("Design the launch checklist.", document)
            self.assertNotIn("/private/customer/path", document)
            self.assertNotIn("secret-id", document)

    def test_search_and_export_survive_missing_codex_thread_store_table(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            database = root / ".codex/state_5.sqlite"
            with sqlite3.connect(str(database)) as connection:
                connection.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
            original = database.read_bytes()

            match = search(str(root), "launch checklist", limit=1)[0]
            thread = read_thread(str(root), match.collection, match.transcript)
            self.assertIn("Design the launch checklist.", markdown(thread))
            self.assertEqual(database.read_bytes(), original)

    def test_thread_identifier_cannot_escape_discovered_transcripts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            with self.assertRaisesRegex(ValueError, "not found"):
                read_thread(str(root), "active", "../auth.json")
            with self.assertRaisesRegex(ValueError, "unknown"):
                read_thread(str(root), "other", "active.jsonl")

    def test_browser_export_has_a_bounded_text_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transcript = root / ".codex/sessions/large.jsonl"
            transcript.parent.mkdir(parents=True)
            transcript.write_text(json.dumps({"text": "1234567890"}) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(MigrationError, "too large"):
                read_thread(str(root), "active", "large.jsonl", max_text_bytes=5)

    def test_backup_identity_scan_accepts_ordinary_large_compaction_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            thread_id = "11111111-1111-4111-8111-111111111111"
            relative = "rollout-" + thread_id + ".jsonl"
            transcript = root / ".codex/sessions" / relative
            transcript.parent.mkdir(parents=True)
            transcript.write_text(
                json.dumps({"type": "session_meta", "payload": {"id": thread_id}})
                + "\n" + json.dumps({"type": "compacted", "payload": {
                    "replacement_history": "x" * (33 * 1024 * 1024)}}) + "\n"
                + json.dumps({"payload": {"text": "After large compaction"}}) + "\n",
                encoding="utf-8")
            signals = scan_transcript(transcript, relative, {})
            self.assertEqual(signals.identity_state, "verified")
            self.assertEqual(signals.records, 3)
            self.assertEqual(len(search(str(root), "After large compaction")), 1)

    def test_saved_thread_markdown_can_stream_beyond_browser_preview_limit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transcript = root / ".codex/sessions/large.jsonl"
            transcript.parent.mkdir(parents=True)
            body = "Z" * (25 * 1024 * 1024 + 1)
            transcript.write_text(json.dumps({"payload": {"role": "assistant", "text": body}}) + "\n")
            with self.assertRaisesRegex(MigrationError, "too large"):
                read_thread(str(root), "active", "large.jsonl")
            chunks = markdown_chunks(str(root), "active", "large.jsonl")
            self.assertIn(b"Codex conversation", next(chunks))
            self.assertEqual(sum(len(chunk) for chunk in chunks), len(body) + len("## Assistant\n\n\n\n"))

    def test_saved_thread_preview_pages_without_losing_entries(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transcript = root / ".codex/sessions/paged.jsonl"
            transcript.parent.mkdir(parents=True)
            transcript.write_text("".join(
                json.dumps({"payload": {"role": "assistant", "text": "entry-%d" % index}}) + "\n"
                for index in range(5)), encoding="utf-8")
            cursor = 0
            found = []
            while True:
                page, next_cursor = read_thread_page(
                    str(root), "active", "paged.jsonl", cursor, max_entries=2)
                found.extend(entry.text for entry in page.entries)
                if next_cursor is None:
                    break
                self.assertGreater(next_cursor, cursor)
                cursor = next_cursor
            self.assertEqual(found, ["entry-%d" % index for index in range(5)])

    def test_paginated_fork_finds_and_exports_only_inherited_prefix(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            active = root / ".codex/sessions"
            archived = root / ".codex/archived_sessions"
            active.mkdir(parents=True)
            archived.mkdir(parents=True)
            parent_id = "11111111-1111-4111-8111-111111111111"
            child_id = "22222222-2222-4222-8222-222222222222"
            parent = archived / ("rollout-" + parent_id + ".jsonl")
            child = active / ("rollout-" + child_id + ".jsonl")
            def meta(ident, ordinal, **extra):
                return json.dumps({"type": "session_meta", "ordinal": ordinal, "payload": {
                    "id": ident, **extra}}) + "\n"
            def message(value, ordinal):
                return json.dumps({"type": "response_item", "ordinal": ordinal, "payload": {
                    "type": "message", "role": "user", "content": value}}) + "\n"
            inherited = meta(parent_id, 0) + message("Inherited Clerk plan", 1)
            parent.write_text(inherited + message("Parent-only later plan", 2), encoding="utf-8")
            child.write_text(meta(child_id, 2, history_base={
                "thread_id": parent_id,
                "end_ordinal_exclusive": 2,
                "end_byte_offset": len(inherited.encode("utf-8")),
            }) + message("Child-local implementation", 3), encoding="utf-8")

            matches = search(str(root), "Inherited Clerk")
            self.assertEqual({(match.collection, match.transcript) for match in matches},
                             {("active", child.name), ("archived", parent.name)})
            self.assertEqual(len(search(str(root), "Parent-only later")), 1)
            child_match = next(match for match in matches if match.collection == "active")
            page, _ = read_thread_page(str(root), "active", child.name,
                                       child_match.cursor, expected_query="Clerk")
            self.assertEqual(page.entries[0].text, "Inherited Clerk plan")
            thread = read_thread(str(root), "active", child.name)
            self.assertEqual([entry.text for entry in thread.entries],
                             ["Inherited Clerk plan", "Child-local implementation"])
            exported = b"".join(markdown_chunks(str(root), "active", child.name)).decode()
            self.assertIn("Inherited Clerk plan", exported)
            self.assertIn("Child-local implementation", exported)
            self.assertNotIn("Parent-only later plan", exported)

    def test_paginated_fork_refuses_missing_or_torn_parent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            active = root / ".codex/sessions"
            active.mkdir(parents=True)
            parent_id = "11111111-1111-4111-8111-111111111111"
            child_id = "22222222-2222-4222-8222-222222222222"
            child = active / ("rollout-" + child_id + ".jsonl")
            child.write_text(json.dumps({"type": "session_meta", "payload": {
                "id": child_id, "history_base": {"thread_id": parent_id,
                    "end_ordinal_exclusive": 1, "end_byte_offset": 3}}}) + "\n")
            with self.assertRaisesRegex(MigrationError, "parent is missing"):
                read_thread(str(root), "active", child.name)
            with self.assertRaisesRegex(MigrationError, "parent is missing"):
                next(markdown_chunks(str(root), "active", child.name))
            parent = active / ("rollout-" + parent_id + ".jsonl")
            parent.write_text(json.dumps({"type": "session_meta", "payload": {
                "id": parent_id}}) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(MigrationError, "cuts through"):
                read_thread(str(root), "active", child.name)
            child.write_text(json.dumps({"type": "session_meta", "payload": {
                "id": child_id, "history_base": {"thread_id": parent_id,
                    "end_ordinal_exclusive": 9,
                    "end_byte_offset": parent.stat().st_size}}}) + "\n")
            with self.assertRaisesRegex(MigrationError, "mismatched parent boundary"):
                read_thread(str(root), "active", child.name)
            archived = root / ".codex/archived_sessions"
            archived.mkdir()
            (archived / parent.name).write_bytes(parent.read_bytes())
            with self.assertRaisesRegex(MigrationError, "ambiguous"):
                read_thread(str(root), "active", child.name)

    def test_nested_paginated_fork_uses_each_ancestor_cutoff(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / ".codex/sessions"
            folder.mkdir(parents=True)
            ids = ["11111111-1111-4111-8111-111111111111",
                   "22222222-2222-4222-8222-222222222222",
                   "33333333-3333-4333-8333-333333333333"]
            paths = [folder / ("rollout-" + ident + ".jsonl") for ident in ids]
            def item(ordinal, kind, payload):
                return json.dumps({"ordinal": ordinal, "type": kind,
                                   "payload": payload}) + "\n"
            parent_prefix = (item(0, "session_meta", {"id": ids[0]})
                             + item(1, "response_item", {"text": "First plan"}))
            paths[0].write_text(parent_prefix
                                + item(2, "response_item", {"text": "Excluded parent update"}))
            child_prefix = (item(2, "session_meta", {"id": ids[1], "history_base": {
                "thread_id": ids[0], "end_ordinal_exclusive": 2,
                "end_byte_offset": len(parent_prefix.encode())}})
                            + item(3, "response_item", {"text": "Middle plan"}))
            paths[1].write_text(child_prefix
                                + item(4, "response_item", {"text": "Excluded child update"}))
            paths[2].write_text(item(4, "session_meta", {"id": ids[2], "history_base": {
                "thread_id": ids[1], "end_ordinal_exclusive": 4,
                "end_byte_offset": len(child_prefix.encode())}})
                                + item(5, "response_item", {"text": "Final plan"}))
            thread = read_thread(str(root), "active", paths[2].name)
            self.assertEqual([entry.text for entry in thread.entries],
                             ["First plan", "Middle plan", "Final plan"])
            self.assertEqual(len(search(str(root), "First plan")), 3)
            self.assertEqual(len(search(str(root), "Excluded parent update")), 1)
            cursor = 0
            pages = []
            while True:
                page, next_cursor = read_thread_page(
                    str(root), "active", paths[2].name, cursor, max_entries=1)
                pages.extend(entry.text for entry in page.entries)
                if next_cursor is None:
                    break
                self.assertGreater(next_cursor, cursor)
                cursor = next_cursor
            self.assertEqual(pages, ["First plan", "Middle plan", "Final plan"])

    def test_fork_reference_uses_rollout_id_after_parent_revert(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / ".codex/sessions"
            folder.mkdir(parents=True)
            stable_id = "11111111-1111-4111-8111-111111111111"
            rollout_id = "44444444-4444-4444-8444-444444444444"
            child_id = "22222222-2222-4222-8222-222222222222"
            parent = folder / ("rollout-" + stable_id + "_" + rollout_id + ".jsonl")
            parent.write_text(
                json.dumps({"ordinal": 0, "type": "session_meta", "payload": {
                    "id": stable_id}}) + "\n"
                + json.dumps({"ordinal": 1, "type": "response_item", "payload": {
                    "text": "Before the revert"}}) + "\n")
            child = folder / ("rollout-" + child_id + ".jsonl")
            child.write_text(json.dumps({"ordinal": 2, "type": "session_meta", "payload": {
                "id": child_id, "history_base": {"thread_id": rollout_id,
                    "end_ordinal_exclusive": 2,
                    "end_byte_offset": parent.stat().st_size}}}) + "\n")
            self.assertEqual([entry.text for entry in read_thread(
                str(root), "active", child.name).entries], ["Before the revert"])

    def test_cyclic_fork_reference_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / ".codex/sessions"
            folder.mkdir(parents=True)
            first_id = "11111111-1111-4111-8111-111111111111"
            second_id = "22222222-2222-4222-8222-222222222222"
            first = folder / ("rollout-" + first_id + ".jsonl")
            second = folder / ("rollout-" + second_id + ".jsonl")
            def record(ident, parent, boundary):
                return json.dumps({"ordinal": 0, "type": "session_meta", "payload": {
                    "id": ident, "history_base": {"thread_id": parent,
                        "end_ordinal_exclusive": 1,
                        "end_byte_offset": boundary}}}) + "\n"
            # Stabilize the reciprocal byte offsets before testing the cycle.
            first.write_text(record(first_id, second_id, 0))
            second.write_text(record(second_id, first_id, 0))
            for _ in range(4):
                first.write_text(record(first_id, second_id, second.stat().st_size))
                second.write_text(record(second_id, first_id, first.stat().st_size))
            with self.assertRaisesRegex(MigrationError, "cyclic"):
                read_thread(str(root), "active", first.name)


if __name__ == "__main__":
    unittest.main()
