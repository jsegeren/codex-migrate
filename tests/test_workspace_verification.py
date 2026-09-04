"""Disposable whole-workspace corruption checks using real rsync/APFS."""
from dataclasses import replace
import os
import errno
from pathlib import Path
import platform
import shlex
import subprocess
import socket
import tempfile
import time
import unittest
from unittest.mock import patch

import test_full_skills as fixtures
from codex_migrate.migration import MigrationEngine
from codex_migrate.errors import MigrationError
from codex_migrate.workspaces import freeze_tree, TREE_PROGRAM, tree_check, remote_tree_function


@unittest.skipUnless(platform.system() == "Darwin", "APFS installation fixture")
class WorkspaceVerificationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.FullSkillTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.repo = self.fixture.source / "Git/example"
        self.repo.mkdir(parents=True)
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_OPTIONAL_LOCKS="0")
        for args in (("init", "-q", str(self.repo)),
                     ("-C", str(self.repo), "commit", "--allow-empty", "-qm", "fixture"),
                     ("-C", str(self.repo), "branch", "-M", "main")):
            subprocess.run(["/usr/bin/git", "-c", "user.name=Fixture", "-c",
                            "user.email=fixture@example.invalid", *args], env=env,
                           check=True, capture_output=True, timeout=15)
        (self.repo / "unfinished.txt").write_text("unfinished source work")
        self.fixture.config = replace(self.fixture.config, workspace_roots=[str(self.repo)]).validate()
        self.fixture.engine = MigrationEngine(self.fixture.config, self.fixture.state)
        self.staged = Path(self.fixture.config.target_staging) / "home-relative/Git/example"
        self.installed = self.fixture.target / "Git/example"
        self.installed.mkdir(parents=True)
        (self.installed / "original.txt").write_text("destination before migration")

    def assert_original(self):
        self.fixture.assert_destination_original()
        self.assertEqual((self.installed / "original.txt").read_text(), "destination before migration")
        self.assertFalse((self.installed / ".git").exists())

    def test_corrupt_staged_git_ref_blocks_before_replacement(self):
        self.fixture.prepare()
        (self.staged / ".git/refs/heads/main").write_text("0" * 40 + "\n")
        with self.assertRaisesRegex(RuntimeError, "Workspace content verification failed"):
            self.fixture.engine._install_and_verify()
        self.assert_original()

    def test_corrupt_installed_working_file_triggers_rollback(self):
        prefix = "mv() { command mv \"$@\"; if test \"$2\" = %s; then printf corrupt > %s; fi; }\n" % (
            shlex.quote(str(self.installed)), shlex.quote(str(self.installed / "unfinished.txt")))
        self.fixture.prepare(prefix)
        with self.assertRaisesRegex(RuntimeError, "Workspace content verification failed"):
            self.fixture.engine._install_and_verify()
        self.assert_original()

    def test_corrupt_staged_git_object_bytes_are_rejected(self):
        self.fixture.prepare()
        original = next(path for path in (self.repo / ".git/objects").rglob("*") if path.is_file())
        staged = self.staged / original.relative_to(self.repo)
        mode = staged.stat().st_mode & 0o7777
        staged.chmod(0o600)
        staged.write_bytes(b"x" * len(original.read_bytes()))
        staged.chmod(mode)
        with self.assertRaisesRegex(RuntimeError, "Workspace content verification failed"):
            self.fixture.engine._install_and_verify()
        self.assert_original()

    def test_corrupt_installed_git_ref_triggers_rollback(self):
        prefix = "mv() { command mv \"$@\"; if test \"$2\" = %s; then printf corrupt > %s; fi; }\n" % (
            shlex.quote(str(self.installed)), shlex.quote(str(self.installed / ".git/refs/heads/main")))
        self.fixture.prepare(prefix)
        with self.assertRaisesRegex(RuntimeError, "Workspace content verification failed"):
            self.fixture.engine._install_and_verify()
        self.assert_original()

    def test_success_preserves_complete_working_tree_and_git_bytes(self):
        (self.repo / "empty directory").mkdir()
        script = self.repo / "run me"
        script.write_text("fixture executable")
        script.chmod(0o755)
        (self.repo / "broken link").symlink_to("not present")
        (self.repo / "literal $name\n'file").write_bytes(b"fixture\x00bytes")
        self.fixture.prepare()
        receipt = self.fixture.engine._install_and_verify()
        self.assertTrue(receipt["workspace_content_verified"])
        self.assertEqual(receipt["workspace_roots_verified"], 1)
        self.assertEqual(freeze_tree(str(self.repo)), freeze_tree(str(self.installed)))

    def test_added_deleted_renamed_permission_and_link_changes_are_rejected(self):
        changes = ("added", "deleted", "renamed", "permission", "link", "empty-directory")
        (self.repo / "empty").mkdir()
        (self.repo / "link").symlink_to("unfinished.txt")
        for change in changes:
            with self.subTest(change=change):
                self.fixture.prepare()
                file = self.staged / "unfinished.txt"
                if change == "added":
                    (self.staged / "extra").write_text("extra")
                elif change == "deleted":
                    file.unlink()
                elif change == "renamed":
                    file.rename(self.staged / "renamed")
                elif change == "permission":
                    file.chmod(0o700)
                elif change == "link":
                    (self.staged / "link").unlink()
                    (self.staged / "link").symlink_to("somewhere-else")
                else:
                    (self.staged / "empty").rmdir()
                with self.assertRaisesRegex(RuntimeError, "Workspace content verification failed"):
                    self.fixture.engine._install_and_verify()
                self.assert_original()

    def test_managed_worktrees_are_verified_without_selected_workspace(self):
        managed = self.fixture.source / ".codex/worktrees/example"
        managed.mkdir(parents=True)
        (managed / "work.txt").write_text("managed work")
        self.fixture.config = replace(self.fixture.config, workspace_roots=[]).validate()
        self.fixture.engine = MigrationEngine(self.fixture.config, self.fixture.state)
        self.fixture.prepare()
        (Path(self.fixture.config.target_staging) / ".codex/worktrees/example/work.txt").write_text("wrong")
        with self.assertRaisesRegex(RuntimeError, "Workspace content verification failed"):
            self.fixture.engine._install_and_verify()
        self.assert_original()

    def test_absent_managed_root_cannot_be_replaced_with_empty_directory(self):
        self.fixture.prepare()
        (Path(self.fixture.config.target_staging) / ".codex/worktrees").mkdir()
        with self.assertRaisesRegex(RuntimeError, "Workspace content verification failed"):
            self.fixture.engine._install_and_verify()
        self.assert_original()

    def test_installed_checks_reuse_frozen_source_expectations(self):
        self.fixture.prepare()
        frozen = self.fixture.engine._prepare_install()
        (self.repo / "unfinished.txt").write_text("source changed after snapshot")
        (self.staged / "unfinished.txt").write_text("source changed after snapshot")
        with self.assertRaisesRegex(RuntimeError, "Workspace content verification failed"):
            self.fixture.engine._install_and_verify(frozen)
        self.assert_original()

    def test_post_install_does_not_accept_matching_late_source_and_target_changes(self):
        prefix = "mv() { command mv \"$@\"; if test \"$2\" = %s; then printf late > %s; printf late > %s; fi; }\n" % (
            shlex.quote(str(self.installed)), shlex.quote(str(self.repo / "unfinished.txt")),
            shlex.quote(str(self.installed / "unfinished.txt")))
        self.fixture.prepare(prefix)
        with self.assertRaisesRegex(RuntimeError, "Workspace content verification failed"):
            self.fixture.engine._install_and_verify()
        self.assert_original()

    def assert_bad_receipt(self, old, new):
        self.fixture.prepare()
        original = self.fixture.engine.transport.run_remote
        def change_receipt(script, timeout=60):
            result = original(script, timeout)
            result.stdout = result.stdout.replace(old, new)
            return result
        self.fixture.engine.transport.run_remote = change_receipt
        with self.assertRaisesRegex(MigrationError, "Workspace content verification receipt"):
            self.fixture.engine._install_and_verify()

    def test_missing_receipt_is_not_success(self):
        self.assert_bad_receipt("WORKSPACE_CONTENT_VERIFIED=1\n", "")

    def test_count_mismatched_receipt_is_not_success(self):
        self.assert_bad_receipt("WORKSPACE_ROOTS_VERIFIED=1", "WORKSPACE_ROOTS_VERIFIED=0")

    def test_stop_during_source_verification_reaps_child_and_keeps_staging(self):
        self.fixture.prepare()
        children = []
        original = subprocess.Popen
        def record(*args, **kwargs):
            child = original(*args, **kwargs)
            # The preceding storage screen also starts a child. This test
            # specifically waits for the deliberately stalled tree hasher.
            if "sleep 30;" in args[0]:
                children.append(child)
            return child
        engine = self.fixture.engine
        with patch("codex_migrate.workspaces.TREE_PROGRAM", 'sleep 30;'), \
             patch("codex_migrate.workspaces.subprocess.Popen", side_effect=record):
            engine._start(engine._prepare_install)
            deadline = time.monotonic() + 5
            while not children and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(children)
            self.assertIsNone(children[0].poll())
            engine.cancel()
            engine._thread.join(timeout=5)
            self.assertFalse(engine._thread.is_alive())
            self.assertIsNotNone(children[0].poll())
        self.assertEqual(engine.state.read()["status"], "cancelled")
        self.assertTrue((self.staged / "unfinished.txt").is_file())
        self.assert_original()

    def test_stop_at_source_phase_transition_cannot_leave_running_without_worker(self):
        self.fixture.prepare()
        engine = self.fixture.engine
        engine.state.update(status="running", phase="final_delta")
        original = engine.state.update
        stopped = []
        def stop_before_publication(**changes):
            if changes.get("phase") == "verifying_sources" and not stopped:
                stopped.append(True)
                engine.cancel()
            return original(**changes)
        with patch.object(engine.state, "update", side_effect=stop_before_publication):
            engine._guarded(engine._prepare_install)
        self.assertEqual(engine.state.read()["status"], "cancelled")
        self.assertEqual(engine.state.read()["phase"], "staging")
        self.assert_original()


class TreeDigestTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def test_unicode_and_newline_names_are_unambiguous(self):
        for name in ("é-file".encode(), b"line\nbreak", b"spaces ' $name"):
            path = os.fsencode(self.root) + b"/" + name
            with open(path, "wb") as stream:
                stream.write(b"fixture")
        digest = freeze_tree(str(self.root))
        checks = tree_check(str(self.root), digest)
        script = "set -o pipefail\n" + remote_tree_function() + "verify() {\nlocal workspace_digest\n" + checks + "\n}\nverify\n"
        result = subprocess.run(["/bin/zsh", "-s"], input=script, text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_raw_filename_bytes_where_filesystem_supports_them(self):
        try:
            with open(os.fsencode(self.root) + b"/name\xff", "wb") as stream:
                stream.write(b"fixture")
        except OSError as error:
            if error.errno == errno.EILSEQ:
                self.skipTest("This filesystem rejects non-UTF8 filename bytes")
            raise
        self.assertEqual(len(freeze_tree(str(self.root))), 64)

    def test_file_and_directory_links_do_not_read_the_target(self):
        target = self.root / "external"
        target.mkdir()
        workspace = self.root / "workspace"
        workspace.mkdir()
        file = target / "private.txt"
        file.write_text("first value")
        (workspace / "folder").symlink_to(target, target_is_directory=True)
        (workspace / "file").symlink_to(file)
        before = freeze_tree(str(workspace))
        file.write_text("different target contents are not followed")
        self.assertEqual(before, freeze_tree(str(workspace)))

    def test_special_files_fail_without_hanging(self):
        fifo = self.root / "pipe"
        os.mkfifo(fifo)
        with self.assertRaises(MigrationError):
            freeze_tree(str(self.root))
        fifo.unlink()
        sock = socket.socket(socket.AF_UNIX)
        self.addCleanup(sock.close)
        sock.bind(str(self.root / "socket"))
        with self.assertRaises(MigrationError):
            freeze_tree(str(self.root))

    def test_changed_file_during_hashing_is_rejected(self):
        (self.root / "file").write_bytes(b"fixture bytes")
        changing = TREE_PROGRAM.replace("$content->add($buffer);", "truncate($path, 0); $content->add($buffer);")
        with patch("codex_migrate.workspaces.TREE_PROGRAM", changing):
            with self.assertRaises(MigrationError):
                freeze_tree(str(self.root))

    def test_failed_remote_hasher_cannot_match_an_empty_output(self):
        script = "workspace_tree_digest() { return 74; }\nverify() {\nlocal workspace_digest\n" + tree_check(str(self.root), "a" * 64) + "\n}\nverify\n"
        result = subprocess.run(["/bin/zsh", "-s"], input=script, text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 74)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
