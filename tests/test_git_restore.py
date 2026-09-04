"""Git acceptance after real local install; only disposable homes are used."""
from dataclasses import replace
import os
from pathlib import Path
import platform
import subprocess
import unittest

import test_full_skills as fixtures
from codex_migrate.migration import MigrationEngine
from codex_migrate.workspaces import freeze_tree


@unittest.skipUnless(platform.system() == "Darwin", "APFS installation fixture")
class GitRestoreTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.FullSkillTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.home = self.fixture.source
        self.git_root = self.home / "Git"
        self.repo = self.git_root / "main repo"
        self.git("init", "-q", str(self.repo))
        (self.repo / "tracked.txt").write_text("committed fixture\n")
        self.git("-C", str(self.repo), "add", "tracked.txt")
        self.git("-C", str(self.repo), "commit", "-qm", "local-only fixture")
        self.git("-C", str(self.repo), "branch", "-M", "main")
        self.git("-C", str(self.repo), "branch", "codex/unfinished")
        self.git("-C", str(self.repo), "tag", "fixture-tag")
        self.fixture.config = replace(self.fixture.config,
                                      workspace_roots=[str(self.git_root)]).validate()
        self.fixture.engine = MigrationEngine(self.fixture.config, self.fixture.state)

    def git(self, *args, check=True):
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                   GIT_OPTIONAL_LOCKS="0")
        return subprocess.run(["/usr/bin/git", "-c", "user.name=Fixture", "-c",
                               "user.email=fixture@example.invalid", "-c",
                               "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null",
                               *args], env=env, capture_output=True, check=check, timeout=15)

    def snapshot(self, repo):
        commands = [("show-ref",), ("status", "--porcelain=v1", "-z", "--untracked-files=all"),
                    ("stash", "list", "--format=%H"), ("rev-parse", "HEAD"),
                    ("ls-files", "--stage", "-z"),
                    ("diff", "--no-ext-diff", "--no-textconv", "--binary"),
                    ("diff", "--cached", "--no-ext-diff", "--no-textconv", "--binary")]
        return [self.git("-C", str(repo), *args).stdout for args in commands]

    def install(self):
        self.fixture.prepare()
        self.assertEqual(self.fixture.state.read()["inventory"]["git_missing_paths"], [])
        self.assertEqual(self.fixture.state.read()["inventory"]["git_issues"], [])
        receipt = self.fixture.engine._install_and_verify()
        self.assertTrue(receipt["workspace_content_verified"])
        # Only the disposable fixture is relocated. Keeping the original path
        # available would mask broken absolute Git pointers in a same-Mac test.
        self.home.rename(self.fixture.root / "unavailable old home")

    def compatibility_alias(self):
        self.home.symlink_to(self.fixture.target, target_is_directory=True)

    def test_branches_stash_index_dirty_files_and_managed_worktree_after_alias(self):
        tracked = self.repo / "tracked.txt"
        tracked.write_text("stashed fixture\n")
        self.git("-C", str(self.repo), "stash", "push", "-qm", "preserve me")
        tracked.write_text("staged fixture\n")
        self.git("-C", str(self.repo), "add", "tracked.txt")
        tracked.write_text("unstaged fixture\n")
        (self.repo / "untracked.txt").write_text("unfinished file")
        worktree = self.home / ".codex/worktrees/example/task"
        self.git("-C", str(self.repo), "worktree", "add", str(worktree), "codex/unfinished")
        (worktree / "tracked.txt").write_text("unfinished worktree edit\n")
        (worktree / "untracked.txt").write_text("worktree untracked file")
        expected = {str(path.relative_to(self.home)): self.snapshot(path)
                    for path in (self.repo, worktree)}
        source_digest = freeze_tree(str(self.git_root))
        self.install()
        restored_worktree = self.fixture.target / worktree.relative_to(self.home)
        self.assertNotEqual(self.git("-C", str(restored_worktree), "status", "--porcelain",
                                     check=False).returncode, 0)
        self.assertIsNotNone(self.fixture.engine.completion_warning())
        self.compatibility_alias()
        for relative, snapshot in expected.items():
            restored = self.fixture.target / relative
            self.assertEqual(self.snapshot(restored), snapshot)
            self.git("-C", str(restored), "fsck", "--full", "--strict")
        self.assertEqual(freeze_tree(str(self.fixture.target / "Git")), source_digest)

    def test_absolute_alternate_object_store_after_alias(self):
        pool = self.git_root / "object pool.git"
        borrower = self.git_root / "borrower"
        self.git("clone", "-q", "--bare", str(self.repo), str(pool))
        self.git("clone", "-q", "--shared", str(pool), str(borrower))
        expected = {str(path.relative_to(self.home)): self.snapshot(path)
                    for path in (self.repo, borrower)}
        self.install()
        self.compatibility_alias()
        for relative, snapshot in expected.items():
            restored = self.fixture.target / relative
            self.assertEqual(self.snapshot(restored), snapshot)
            self.git("-C", str(restored), "fsck", "--full", "--strict")
        self.git("--git-dir", str(self.fixture.target / pool.relative_to(self.home)),
                 "fsck", "--full", "--strict")

    def test_linked_refs_commands_and_source_fsck_result_are_preserved(self):
        refs = self.repo / ".git/refs"
        external = self.git_root / "external refs"
        refs.rename(external)
        refs.symlink_to(external, target_is_directory=True)
        expected = self.snapshot(self.repo)
        # Some Git versions reject this symlink layout under strict fsck.
        # Preserve the observed source result rather than requiring a specific
        # Git version's rejection or misattributing a source failure to migration.
        before = self.git("-C", str(self.repo), "fsck", "--full", "--strict", check=False)
        self.install()
        self.compatibility_alias()
        restored = self.fixture.target / self.repo.relative_to(self.home)
        self.assertEqual(self.snapshot(restored), expected)
        after = self.git("-C", str(restored), "fsck", "--full", "--strict", check=False)
        self.assertEqual(after.returncode, before.returncode)
        self.assertEqual(after.stderr, before.stderr)


if __name__ == "__main__":
    unittest.main()
