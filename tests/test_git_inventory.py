"""Real disposable Git layouts; no user's repository or remotes are touched."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from codex_migrate.config import MigrationConfig
from codex_migrate.exclusions import CODEX_EXCLUDES, codex_path_excluded
from codex_migrate.inventory import collect
from codex_migrate.migration import MigrationEngine, MigrationError
from codex_migrate.state import StateStore


class GitInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name).resolve()
        (self.home / ".codex/sessions").mkdir(parents=True)
        self.repo = self.home / "Git/main repo"
        self.git("init", "-q", str(self.repo))
        self.git("-C", str(self.repo), "commit", "--allow-empty", "-qm", "fixture")
        self.worktree = self.home / ".codex/worktrees/example/task"
        self.git("-C", str(self.repo), "worktree", "add", "--detach", str(self.worktree))

    def git(self, *args):
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_OPTIONAL_LOCKS="0")
        return subprocess.run(["/usr/bin/git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                               *args], env=env, capture_output=True, text=True, check=True, timeout=15)

    def test_managed_worktree_reports_unselected_main_repository(self):
        report = collect(str(self.home), [])
        self.assertIn(str(self.repo), report.git_missing_paths)
        self.assertEqual(report.git_repositories, 1)

    def test_missing_dependency_blocks_before_ssh(self):
        config = MigrationConfig(target="new@fixture.invalid", target_home="/Users/new",
                                 source_home=str(self.home)).validate()
        engine = MigrationEngine(config, StateStore(config.state_dir))
        with patch.object(engine.transport, "check", side_effect=AssertionError("SSH must not run")):
            with self.assertRaisesRegex(MigrationError, "Git dependencies"):
                engine.preflight()

    def test_selecting_main_and_managed_worktree_covers_dependencies(self):
        report = collect(str(self.home), [str(self.repo)])
        self.assertEqual(report.git_missing_paths, [])
        self.assertEqual(report.git_issues, [])
        self.assertEqual(report.git_repositories, 2)

    def test_registered_worktree_outside_selection_is_required(self):
        sibling = self.home / "Documents/unfinished task"
        self.git("-C", str(self.repo), "worktree", "add", "--detach", str(sibling))
        report = collect(str(self.home), [str(self.repo)])
        self.assertEqual(report.git_missing_paths, [str(sibling)])
        covered = collect(str(self.home), [str(self.repo), str(sibling)])
        self.assertEqual(covered.git_missing_paths, [])
        self.assertEqual(covered.git_issues, [])

    def test_alternate_object_store_is_required(self):
        pool = self.home / "object pool.git"
        borrower = self.home / "borrower"
        self.git("clone", "-q", "--bare", str(self.repo), str(pool))
        self.git("clone", "-q", "--shared", str(pool), str(borrower))
        report = collect(str(self.home), [str(self.repo), str(borrower)])
        self.assertEqual(report.git_missing_paths, [str(pool / "objects")])
        covered = collect(str(self.home), [str(self.repo), str(borrower), str(pool)])
        self.assertEqual(covered.git_missing_paths, [])
        self.assertEqual(covered.git_issues, [])
        self.assertTrue(any(item["kind"] == "storage" for item in covered.git_details))

    def test_empty_alternates_file_is_valid(self):
        (self.repo / ".git/objects/info/alternates").write_text("")
        report = collect(str(self.home), [str(self.repo)])
        self.assertEqual(report.git_issues, [])

    def test_external_refs_link_requires_its_target_folder(self):
        refs = self.repo / ".git/refs"
        external = self.home / "private refs"
        refs.rename(external)
        refs.symlink_to(external, target_is_directory=True)
        self.git("-C", str(self.repo), "show-ref")
        report = collect(str(self.home), [str(self.repo)])
        self.assertIn(str(external), report.git_missing_paths)
        covered = collect(str(self.home), [str(self.repo), str(external)])
        self.assertEqual(covered.git_missing_paths, [])
        self.assertEqual(covered.git_issues, [])

    def test_codex_copy_keeps_managed_repository_branches_reflogs_and_files(self):
        checkout = self.home / ".codex/worktrees/fullcheckout"
        self.git("clone", "-q", str(self.repo), str(checkout))
        self.git("-C", str(checkout), "branch", "cache/important")
        for name in ("logs/work.txt", "cache/unfinished.txt", "packages/source.txt", "auth.json"):
            path = checkout / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture workspace data")
        codex = self.home / ".codex"
        (codex / "auth.json").write_text("fixture identity must not copy")
        (codex / "installation_id").write_text("fixture installation must not copy")
        (codex / "logs").mkdir()
        (codex / "logs/runtime.log").write_text("fixture runtime log")
        destination = self.home / "copy"
        command = ["/usr/bin/rsync", "-a"]
        for pattern in CODEX_EXCLUDES:
            command.extend(["--exclude", pattern])
        subprocess.run(command + [str(codex) + "/", str(destination) + "/"], check=True,
                       capture_output=True, timeout=15)
        copied = destination / "worktrees/fullcheckout"
        self.assertEqual(self.git("-C", str(checkout), "show-ref").stdout,
                         self.git("-C", str(copied), "show-ref").stdout)
        for original in checkout.rglob("*"):
            if original.is_file():
                self.assertEqual(original.read_bytes(), (copied / original.relative_to(checkout)).read_bytes())
                self.assertFalse(codex_path_excluded(original.relative_to(codex)))
        for name in ("auth.json", "installation_id", "logs"):
            self.assertFalse((destination / name).exists())
            self.assertTrue(codex_path_excluded(Path(name)))

    def test_nested_ref_link_requires_target_parent(self):
        self.git("-C", str(self.repo), "branch", "nested/local")
        ref = self.repo / ".git/refs/heads/nested/local"
        external = self.home / "ref storage/local"
        external.parent.mkdir()
        ref.rename(external)
        ref.symlink_to(external)
        self.git("-C", str(self.repo), "show-ref")
        report = collect(str(self.home), [str(self.repo)])
        self.assertEqual(report.git_missing_paths, [str(external.parent)])

    def test_head_link_requires_target_parent(self):
        head = self.repo / ".git/HEAD"
        external = self.home / "head storage/HEAD"
        external.parent.mkdir()
        head.rename(external)
        head.symlink_to(external)
        report = collect(str(self.home), [str(self.repo)])
        self.assertEqual(report.git_missing_paths, [str(external.parent)])

    def test_external_link_tree_is_checked_recursively(self):
        refs = self.repo / ".git/refs"
        external = self.home / "refs storage"
        refs.rename(external)
        refs.symlink_to(external, target_is_directory=True)
        heads = external / "heads"
        more = self.home / "heads storage"
        heads.rename(more)
        heads.symlink_to(more, target_is_directory=True)
        report = collect(str(self.home), [str(self.repo), str(external)])
        self.assertEqual(report.git_missing_paths, [str(more)])

    def test_intermediate_metadata_alias_must_also_be_selected(self):
        refs = self.repo / ".git/refs"
        external = self.home / "real refs"
        alias = self.home / "aliases/refs"
        alias.parent.mkdir()
        refs.rename(external)
        alias.symlink_to(external, target_is_directory=True)
        refs.symlink_to(alias, target_is_directory=True)
        self.git("-C", str(self.repo), "show-ref")
        report = collect(str(self.home), [str(self.repo), str(external)])
        self.assertEqual(report.git_missing_paths, [str(alias.parent)])
        covered = collect(str(self.home), [str(self.repo), str(external), str(alias.parent)])
        self.assertEqual(covered.git_missing_paths, [])
        self.assertEqual(covered.git_issues, [])

    def test_broken_metadata_link_blocks_inspection(self):
        (self.repo / ".git/refs/broken").symlink_to(self.home / "missing refs")
        report = collect(str(self.home), [str(self.repo)])
        self.assertTrue(any("link target is missing" in message for message in report.git_issues))

    def test_metadata_issue_blocks_before_ssh(self):
        (self.repo / ".git/refs/broken").symlink_to(self.home / "missing refs")
        config = MigrationConfig(target="new@fixture.invalid", target_home="/Users/new",
                                 source_home=str(self.home), workspace_roots=[str(self.repo)]).validate()
        engine = MigrationEngine(config, StateStore(config.state_dir))
        with patch.object(engine.transport, "check", side_effect=AssertionError("SSH must not run")):
            with self.assertRaisesRegex(MigrationError, "Git dependency inspection needs review"):
                engine.preflight()

    def test_alternate_path_ancestor_alias_must_be_selected(self):
        pool = self.home / "pool.git"
        borrower = self.home / "borrower"
        alias = self.home / "aliases/pool"
        alias.parent.mkdir()
        self.git("clone", "-q", "--bare", str(self.repo), str(pool))
        self.git("clone", "-q", "--shared", str(pool), str(borrower))
        alias.symlink_to(pool, target_is_directory=True)
        (borrower / ".git/objects/info/alternates").write_text(str(alias / "objects") + "\n")
        self.git("-C", str(borrower), "fsck", "--no-reflogs")
        report = collect(str(self.home), [str(self.repo), str(pool), str(borrower)])
        self.assertEqual(report.git_missing_paths, [str(alias.parent)])

    def test_exclusions_are_root_anchored_in_copy_and_inventory(self):
        codex = self.home / ".codex"
        candidates = ("cache/runtime", "sqlite/logs_1.sqlite", "logs_2.sqlite-wal",
                      "nested/cache/work", "nested/logs_1.sqlite", "nested/auth.json",
                      "sqlite/keep.sqlite", "worktrees/cache/refs/heads/logs/branch")
        for name in candidates:
            path = codex / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture")
        destination = self.home / "excluded-copy"
        command = ["/usr/bin/rsync", "-a"]
        for pattern in CODEX_EXCLUDES:
            command.extend(["--exclude", pattern])
        subprocess.run(command + [str(codex) + "/", str(destination) + "/"], check=True,
                       capture_output=True, timeout=15)
        for name in candidates:
            self.assertEqual(not (destination / name).exists(), codex_path_excluded(Path(name)), name)

    def test_nested_build_named_repository_is_not_skipped(self):
        nested = self.repo / "build/another repository"
        self.git("init", "-q", str(nested))
        report = collect(str(self.home), [str(self.repo)])
        self.assertIn(str(nested), [item["path"] for item in report.git_details])

    def test_separate_git_directory_is_required(self):
        checkout = self.home / "separate checkout"
        storage = self.home / "separate metadata"
        self.git("init", "-q", "--separate-git-dir", str(storage), str(checkout))
        report = collect(str(self.home), [str(self.repo), str(checkout)])
        self.assertEqual(report.git_missing_paths, [str(storage)])
        covered = collect(str(self.home), [str(self.repo), str(checkout), str(storage)])
        self.assertEqual(covered.git_missing_paths, [])
        self.assertEqual(covered.git_issues, [])

    def test_invalid_pointer_is_reported_without_printing_its_contents(self):
        (self.worktree / ".git").write_text("private invalid pointer fixture")
        report = collect(str(self.home), [str(self.repo)])
        self.assertTrue(report.git_issues)
        self.assertNotIn("private invalid pointer fixture", str(report.as_dict()))

    def test_stale_registration_is_warned_not_silently_removed(self):
        registration = next((self.repo / ".git/worktrees").iterdir())
        missing = self.home / "absent worktree/.git"
        (registration / "gitdir").write_text(str(missing) + "\n")
        report = collect(str(self.home), [str(self.repo)])
        self.assertTrue(any("already absent" in message for message in report.git_warnings))
        self.assertTrue(registration.is_dir())

    def test_inspection_keeps_local_refs_index_stash_and_dirty_files_unchanged(self):
        file = self.repo / "unfinished.txt"
        file.write_text("committed")
        self.git("-C", str(self.repo), "add", "unfinished.txt")
        self.git("-C", str(self.repo), "commit", "-qm", "tracked fixture")
        self.git("-C", str(self.repo), "branch", "local-only")
        file.write_text("stashed")
        self.git("-C", str(self.repo), "stash", "push", "-qm", "fixture stash")
        file.write_text("staged")
        self.git("-C", str(self.repo), "add", "unfinished.txt")
        file.write_text("unstaged")
        (self.repo / "untracked.txt").write_text("untracked")
        before = ((self.repo / ".git/index").read_bytes(), file.read_bytes(),
                  self.git("-C", str(self.repo), "show-ref").stdout,
                  self.git("-C", str(self.repo), "status", "--porcelain=v1").stdout)
        report = collect(str(self.home), [str(self.repo)])
        self.assertEqual(report.git_issues, [])
        after = ((self.repo / ".git/index").read_bytes(), file.read_bytes(),
                 self.git("-C", str(self.repo), "show-ref").stdout,
                 self.git("-C", str(self.repo), "status", "--porcelain=v1").stdout)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
