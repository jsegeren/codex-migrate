import tempfile
import unittest
from pathlib import Path

from manual_disposable_fixture import ensure_empty


class DisposableFixtureSafetyTests(unittest.TestCase):
    def test_absent_and_empty_roots_are_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "fixture"
            ensure_empty(root)
            root.mkdir()
            ensure_empty(root)

    def test_nonempty_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "fixture"
            root.mkdir()
            (root / "keep.txt").write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(SystemExit, "Refusing to overwrite non-empty"):
                ensure_empty(root)

    def test_file_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "fixture"
            root.write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(SystemExit, "Refusing non-directory"):
                ensure_empty(root)

    def test_linked_root_is_rejected_without_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            target = base / "outside"
            target.mkdir()
            root = base / "fixture"
            root.symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(SystemExit, "Refusing linked fixture root"):
                ensure_empty(root)


if __name__ == "__main__":
    unittest.main()
