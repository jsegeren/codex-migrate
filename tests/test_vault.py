import json
from pathlib import Path
import tempfile
import unittest

from codex_migrate.errors import MigrationError
from codex_migrate.vault import inspect, search


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
            self.assertEqual(results[0].collection, "active")
            self.assertEqual(results[0].timestamp, "2026-09-17T10:00:00Z")
            self.assertIn("launch checklist", results[0].snippet)
            self.assertEqual(search(str(root), "private/customer", limit=10), [])
            self.assertEqual(search(str(root), "secret-id", limit=10), [])

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


if __name__ == "__main__":
    unittest.main()
