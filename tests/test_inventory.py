import tempfile
import unittest
from pathlib import Path

from codex_migrate.inventory import collect


class InventoryTests(unittest.TestCase):
    def test_collects_content_free_counts_and_git_repositories(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            sessions = home / ".codex/sessions/2026/01/01"
            archived = home / ".codex/archived_sessions"
            repo = home / "Git/project"
            sessions.mkdir(parents=True)
            archived.mkdir(parents=True)
            repo.mkdir(parents=True)
            (sessions / "one.jsonl").write_text("{}\n", encoding="utf-8")
            (sessions / ".DS_Store").write_text("junk", encoding="utf-8")
            (archived / "old.jsonl").write_text("{}\n", encoding="utf-8")
            (repo / ".git").mkdir()
            (repo / "README.md").write_text("hello", encoding="utf-8")
            result = collect(str(home), [str(home / "Git")])
            self.assertTrue(result.codex_present)
            self.assertEqual(result.active_sessions.files, 1)
            self.assertEqual(result.archived_sessions.files, 1)
            self.assertEqual(result.git_repositories, 1)
            self.assertGreater(result.estimated_transfer_bytes, 0)


if __name__ == "__main__":
    unittest.main()
