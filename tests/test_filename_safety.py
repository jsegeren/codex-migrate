"""Private-free synthetic names and disposable filesystem collision fixtures."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from codex_migrate.errors import MigrationError
from codex_migrate.filename_safety import check_names, check_tree_names, PERL_NAME_CHECK
from codex_migrate.inventory import collect
from codex_migrate.skills import _validated_skill
from codex_migrate.workspaces import freeze_tree, PERL_COMMAND, TREE_PROGRAM


class FilenameSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def perl_names(self, names):
        script = PERL_NAME_CHECK + "eval { validate_names(@ARGV); 1 } or exit 75;"
        return subprocess.run(PERL_COMMAND + ["-e", script, "--", *names],
                              capture_output=True, timeout=5)

    def test_python_and_perl_reject_conservative_collisions(self):
        for names in (("README", "readme"), ("é", "e\u0301"),
                      ("Straße", "STRASSE"), ("Σ", "ς"),
                      ("İ", "i\u0307"), ("K", "k"), ("ﬀ", "ff")):
            with self.subTest(names=names):
                with self.assertRaisesRegex(MigrationError, "filenames may collide"):
                    check_names(names)
                result = self.perl_names(names)
                self.assertEqual(result.returncode, 75, result.stderr)
                self.assertEqual(result.stdout, b"")
                self.assertEqual(result.stderr, b"")

    def test_distinct_names_are_not_normalized_on_disk(self):
        names = ("é", "e", "Report", "Reports", "line\nbreak", "quote '$()", "🚀")
        check_names(names)
        result = self.perl_names(names)
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in names:
            (self.root / name).write_bytes(b"fixture")
        before = sorted(os.listdir(self.root))
        check_tree_names(self.root)
        self.assertEqual(len(freeze_tree(str(self.root))), 64)
        self.assertEqual(sorted(os.listdir(self.root)), before)

    def test_invalid_utf8_rejected_without_echoing_the_name(self):
        name = b"PRIVATE_FILENAME_\xff"
        with self.assertRaises(MigrationError) as error:
            check_names([os.fsdecode(name)])
        self.assertNotIn("PRIVATE_FILENAME", str(error.exception))
        result = self.perl_names([name])
        self.assertEqual(result.returncode, 75)
        self.assertEqual(result.stdout + result.stderr, b"")

    def collision_fixture(self, root):
        root.mkdir(parents=True, exist_ok=True)
        first, second = root / "Straße", root / "STRASSE"
        first.write_bytes(b"original fixture")
        try:
            with second.open("xb") as stream:
                stream.write(b"distinct fixture")
        except FileExistsError:
            self.skipTest("This filesystem aliases the conservative collision fixture")
        return first, second

    def test_nested_collision_blocks_inventory_and_freeze_without_changes(self):
        (self.root / ".codex/sessions").mkdir(parents=True)
        repo = self.root / "Git/repo"
        files = self.collision_fixture(repo / "nested")
        for operation in (lambda: collect(str(self.root), [str(repo)]),
                          lambda: freeze_tree(str(repo)),
                          lambda: check_tree_names(repo)):
            with self.assertRaisesRegex(MigrationError, "filenames may collide"):
                operation()
            self.assertEqual([file.read_bytes() for file in files],
                             [b"original fixture", b"distinct fixture"])

    def test_managed_worktrees_are_screened_but_runtime_subtrees_are_not(self):
        codex = self.root / ".codex"
        self.collision_fixture(codex / "logs")
        check_tree_names(codex, codex=True)
        self.assertEqual(len(freeze_tree(str(codex), codex=True)), 64)
        self.collision_fixture(codex / "worktrees/repo/logs")
        with self.assertRaises(MigrationError):
            check_tree_names(codex, codex=True)
        with self.assertRaises(MigrationError):
            freeze_tree(str(codex / "worktrees"))

    def test_skills_reject_collisions_before_opening_contents(self):
        skill = self.root / ".agents/skills/example"
        self.collision_fixture(skill / "nested")
        (skill / "SKILL.md").write_text("fixture")
        with patch.object(Path, "open", side_effect=AssertionError("No content reads")):
            with self.assertRaises(MigrationError):
                _validated_skill(skill, self.root)

    def test_file_directory_collision_checked_before_hashing_children(self):
        (self.root / "nested").mkdir()
        # Inject a case-sensitive directory listing so this safety boundary is
        # exercised even on filesystems that cannot create these two entries.
        injected = TREE_PROGRAM.replace("validate_names(@names);", """
            @names = ('README', 'readme') if $relative eq 'nested';
            validate_names(@names);
        """)
        with patch("codex_migrate.workspaces.TREE_PROGRAM", injected):
            with self.assertRaisesRegex(MigrationError, "filenames may collide"):
                freeze_tree(str(self.root))

    def test_unambiguous_digest_bytes_are_unchanged(self):
        from codex_migrate.tree_digest import PERL_IMPORTS, TREE_FUNCTIONS
        script = (PERL_IMPORTS + "my $codex_mode = 0; sub excluded { 0 } "
                  "sub validate_names { return; }" + TREE_FUNCTIONS
                  + "print unpack('H*', tree($ARGV[0], '')); ")
        (self.root / "file").write_bytes(b"fixture")
        result = subprocess.run(PERL_COMMAND + ["-e", script, str(self.root)],
                                capture_output=True, text=True, timeout=5, check=True)
        self.assertEqual(result.stdout, freeze_tree(str(self.root)))

    def test_recovery_can_hash_existing_colliding_names(self):
        from codex_migrate.transaction import TRANSACTION_LIBRARY
        self.collision_fixture(self.root / "existing")
        script = TRANSACTION_LIBRARY + "tree($ARGV[0], '');"
        result = subprocess.run(PERL_COMMAND + ["-e", script, str(self.root)],
                                capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, b"")
        with self.assertRaises(MigrationError):
            freeze_tree(str(self.root))

    def test_full_install_stops_before_transaction_on_nested_source_collision(self):
        import test_full_skills as fixtures
        fixture = fixtures.FullSkillTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.prepare()
        # Staging already succeeded. Simulate a later colliding source listing
        # at source freeze, without allowing any transaction RPC to begin.
        injected = TREE_PROGRAM.replace("validate_names(@names);", """
            @names = ('README', 'readme') if $relative eq 'sessions';
            validate_names(@names);
        """)
        with patch("codex_migrate.workspaces.TREE_PROGRAM", injected):
            with patch.object(fixture.engine.transport, "run_remote", side_effect=AssertionError("No install RPC")):
                with self.assertRaisesRegex(MigrationError, "filenames may collide"):
                    fixture.engine._install_and_verify()
        fixture.assert_destination_original()
        self.assertTrue(Path(fixture.config.target_staging).is_dir())

    def test_resume_rescreens_source_before_copying(self):
        import test_full_skills as fixtures
        fixture = fixtures.FullSkillTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.prepare()
        with patch("codex_migrate.filename_safety.check_tree_names", side_effect=MigrationError("collision fixture")):
            with patch.object(fixture.engine.transport, "rsync_process", side_effect=AssertionError("No copy")):
                with self.assertRaisesRegex(MigrationError, "collision fixture"):
                    fixture.engine._copy_all()
        fixture.assert_destination_original()

    def test_directory_links_are_not_followed(self):
        external = self.root / "external"
        self.collision_fixture(external)
        selected = self.root / "selected"
        selected.mkdir()
        (selected / "link").symlink_to(external)
        check_tree_names(selected)
        self.assertEqual(len(freeze_tree(str(selected))), 64)

    def test_scan_errors_and_cancellation_fail_closed(self):
        with patch("codex_migrate.filename_safety.os.scandir", side_effect=OSError("PRIVATE")):
            with self.assertRaises(MigrationError) as error:
                check_tree_names(self.root)
            self.assertNotIn("PRIVATE", str(error.exception))
        def cancel():
            raise InterruptedError("fixture stop")
        with self.assertRaises(InterruptedError):
            check_tree_names(self.root, cancel)


if __name__ == "__main__":
    unittest.main()
