import json
import os
from pathlib import Path
import tempfile
import unittest

from codex_migrate.errors import MigrationError
from codex_migrate.vault import inspect, markdown, markdown_chunks, read_thread, read_thread_page, search


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


if __name__ == "__main__":
    unittest.main()
