"""Real Git in a deny-write/network/fork sandbox, using disposable data only."""

import json
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest
from unittest.mock import patch

from codex_migrate.errors import MigrationError
from codex_migrate.git_inventory import inspect_git
from codex_migrate.git_probe import probe_local, parse_report, RUNNER
from codex_migrate.workspaces import freeze_tree


class GitProbeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name).resolve()
        self.repo = self.home / "Git/main repo"
        self.git("init", "-q", str(self.repo))
        (self.repo / "work.txt").write_text("committed fixture\n")
        self.git("-C", str(self.repo), "add", "work.txt")
        self.git("-C", str(self.repo), "commit", "-qm", "fixture")

    def git(self, *args):
        env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(self.home),
               "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
               "GIT_OPTIONAL_LOCKS": "0"}
        return subprocess.run(["/usr/bin/git", "-c", "user.name=Fixture", "-c",
                               "user.email=fixture@example.invalid", *args], env=env,
                               capture_output=True, check=True, timeout=15)

    def probe(self, roots=None):
        roots = roots or [str(self.repo)]
        inventory = inspect_git(str(self.home), roots, lambda: None)
        self.assertEqual(inventory.issues, [])
        self.assertEqual(inventory.missing_paths, [])
        return probe_local(str(self.home), roots, inventory.repositories)

    def test_ordinary_repo_and_dirty_state_are_checked_without_writes(self):
        before = freeze_tree(str(self.repo))
        clean = self.probe()["repositories"][0]
        self.assertEqual(clean["status"], "checked", clean)
        self.assertEqual(before, freeze_tree(str(self.repo)))
        (self.repo / "work.txt").write_text("staged fixture\n")
        self.git("-C", str(self.repo), "add", "work.txt")
        (self.repo / "work.txt").write_text("unstaged fixture\n")
        (self.repo / "untracked.txt").write_text("untracked fixture\n")
        before = freeze_tree(str(self.repo))
        dirty = self.probe()["repositories"][0]
        self.assertEqual(dirty["status"], "checked", dirty)
        self.assertNotEqual(clean["checks"]["index"], dirty["checks"]["index"])
        self.assertNotEqual(clean["checks"]["status"], dirty["checks"]["status"])
        self.assertEqual(clean["checks"]["refs"], dirty["checks"]["refs"])
        self.assertEqual(before, freeze_tree(str(self.repo)))

    def test_optional_and_required_filters_cannot_run_or_false_pass(self):
        marker = self.home / "MUST_NOT_BE_CREATED"
        for required in ("false", "true"):
            with self.subTest(required=required):
                self.git("-C", str(self.repo), "config", "filter.fixture.clean", "touch '%s'; cat" % marker)
                self.git("-C", str(self.repo), "config", "filter.fixture.required", required)
                (self.repo / ".gitattributes").write_text("work.txt filter=fixture\n")
                # Same byte length forces Git beyond its size-only shortcut.
                (self.repo / "work.txt").write_text("different fixture\n")
                report = self.probe()
                self.assertEqual(report["repositories"][0]["status"], "needs_review")
                self.assertFalse(marker.exists())
                self.assertNotIn("touch", json.dumps(report))
                self.assertNotIn("MUST_NOT_BE_CREATED", json.dumps(report))

    def test_included_config_cannot_read_outside_selected_roots(self):
        private = self.home / "unselected-config"
        private.write_text("[alias]\n    private = PRIVATE_FIXTURE\n")
        self.git("-C", str(self.repo), "config", "include.path", str(private))
        report = self.probe()
        self.assertEqual(report["repositories"][0]["status"], "needs_review")
        self.assertNotIn("PRIVATE_FIXTURE", json.dumps(report))
        self.assertEqual(private.read_text(), "[alias]\n    private = PRIVATE_FIXTURE\n")

    def test_conditional_config_cannot_read_outside_selected_roots(self):
        private = self.home / "unselected-config"
        private.write_text("[alias]\n    private = PRIVATE_FIXTURE\n")
        self.git("-C", str(self.repo), "config", "includeIf.gitdir:%s/.git.path" % self.repo, str(private))
        report = self.probe()
        self.assertEqual(report["repositories"][0]["status"], "needs_review")
        self.assertNotIn("PRIVATE_FIXTURE", json.dumps(report))

    def test_process_filter_cannot_run(self):
        marker = self.home / "MUST_NOT_BE_CREATED"
        self.git("-C", str(self.repo), "config", "filter.fixture.process", "touch '%s'; cat" % marker)
        (self.repo / ".gitattributes").write_text("work.txt filter=fixture\n")
        (self.repo / "work.txt").write_text("different fixture\n")
        report = self.probe()
        self.assertEqual(report["repositories"][0]["status"], "needs_review")
        self.assertFalse(marker.exists())
        self.assertNotIn("touch", json.dumps(report))

    def test_fsmonitor_configuration_is_disabled_without_running_it(self):
        marker = self.home / "MUST_NOT_BE_CREATED"
        self.git("-C", str(self.repo), "config", "core.fsmonitor", "touch '%s'" % marker)
        report = self.probe()
        self.assertEqual(report["repositories"][0]["status"], "checked", report)
        self.assertFalse(marker.exists())

    def test_object_corruption_cannot_pass(self):
        object_path = next(path for path in (self.repo / ".git/objects").rglob("*") if path.is_file())
        object_path.chmod(0o600)
        object_path.write_bytes(b"corrupt fixture")
        report = self.probe()
        self.assertEqual(report["repositories"][0]["status"], "needs_review")
        self.assertEqual(report["repositories"][0]["checks"], {})

    def test_inherited_environment_cannot_redirect_or_write_traces(self):
        trace = self.home / "must-not-write-trace"
        with patch.dict(os.environ, {"GIT_TRACE": str(trace), "GIT_DIR": "/not-the-repo",
                                     "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.worktree",
                                     "GIT_CONFIG_VALUE_0": str(self.home)}):
            report = self.probe()
        self.assertEqual(report["repositories"][0]["status"], "checked", report)
        self.assertFalse(trace.exists())

    def test_promisor_and_custom_fsck_policy_require_review(self):
        for key, value in (("remote.fixture.promisor", "true"), ("fsck.missingEmail", "ignore")):
            with self.subTest(key=key):
                self.git("-C", str(self.repo), "config", key, value)
                report = self.probe()["repositories"][0]
                self.assertEqual(report["status"], "needs_review")
                self.assertEqual(report["reason"], "custom_object_policy")
                self.git("-C", str(self.repo), "config", "--unset", key)

    def test_known_identity_hardlink_is_rejected_before_git(self):
        codex = self.home / ".codex"
        codex.mkdir()
        identity = codex / "auth.json"
        identity.write_bytes(b"PRIVATE_IDENTITY_FIXTURE")
        os.link(identity, self.repo / "alias")
        with self.assertRaises(MigrationError) as error:
            self.probe()
        self.assertNotIn("PRIVATE", str(error.exception))

    def test_case_and_relocated_ssh_roots_cannot_be_granted_read_access(self):
        keys = self.home / ".ssh"
        keys.mkdir()
        (keys / "fixture-config").write_text("[core]\nfileMode = false\n")
        self.git("-C", str(self.repo), "config", "include.path", str(keys / "fixture-config"))
        plan = inspect_git(str(self.home), [str(self.repo)], lambda: None).repositories
        for spelling in (".ssh", ".SSH"):
            with self.subTest(spelling=spelling):
                with self.assertRaises(MigrationError):
                    probe_local(str(self.home), [str(self.repo), str(self.home / spelling)], plan)
        moved = self.home / "relocated-keys"
        keys.rename(moved)
        keys.symlink_to(moved)
        with self.assertRaises(MigrationError):
            probe_local(str(self.home), [str(self.repo), str(moved)], plan)

    def test_bad_report_is_not_a_verification_receipt(self):
        with self.assertRaises(MigrationError):
            parse_report('{"format":1,"git_version":"2.50.1","repositories":[{"status":"checked","reason":"none","checks":{}}]}', 1)

    def test_report_rejects_extra_private_data_duplicates_and_inconsistent_success(self):
        valid = {"format": 1, "git_version": "2.50.1", "repositories": [
            {"status": "checked", "reason": "none", "bare": True, "history_scope": "local",
             "checks": {"head": "a" * 64, "refs": "b" * 64}}]}
        parse_report(json.dumps(valid), 1)
        for scope in (valid, valid["repositories"][0]):
            scope["raw_output"] = "PRIVATE"
            with self.assertRaises(MigrationError):
                parse_report(json.dumps(valid), 1)
            del scope["raw_output"]
        row = valid["repositories"][0]
        row["reason"] = "check_failed"
        with self.assertRaises(MigrationError):
            parse_report(json.dumps(valid), 1)
        with self.assertRaises(MigrationError):
            parse_report('{"format":1,"format":1,"git_version":"2.50.1","repositories":[]}', 0)

    def test_unicode_and_shell_syntax_paths_are_literal(self):
        destination = self.home / "Git/café '$() repo"
        self.repo.rename(destination)
        self.repo = destination
        report = self.probe()
        self.assertEqual(report["repositories"][0]["status"], "checked", report)

    def test_prelaunch_cancellation_does_not_start_process(self):
        def cancel():
            raise InterruptedError("fixture stop")
        with patch("codex_migrate.git_probe.subprocess.Popen", side_effect=AssertionError("no launch")):
            with self.assertRaises(InterruptedError):
                probe_local(str(self.home), [str(self.repo)], [], cancel)

    def test_unserializable_or_oversized_plan_never_launches(self):
        for plan in ([object()], [{"path": "x" * (129 * 1024)}]):
            with patch("codex_migrate.git_probe.subprocess.Popen", side_effect=AssertionError("no launch")):
                with self.assertRaises(MigrationError):
                    probe_local(str(self.home), [str(self.repo)], plan)

    def test_initial_process_has_no_inherited_loader_or_shell_environment(self):
        launched = []
        original = subprocess.Popen
        def record(*args, **kwargs):
            launched.append((args, kwargs))
            return original(*args, **kwargs)
        with patch.dict(os.environ, {"DYLD_INSERT_LIBRARIES": "/invalid/fixture.dylib", "ZDOTDIR": "/invalid/fixture"}):
            with patch("codex_migrate.git_probe.subprocess.Popen", side_effect=record):
                self.assertEqual(self.probe()["repositories"][0]["status"], "checked")
        self.assertEqual(len(launched), 1)
        self.assertEqual(launched[0][0][0][0], "/usr/bin/env")
        self.assertEqual(launched[0][1]["env"], {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C"})

    def test_bare_packed_repo_and_detached_head_are_checked(self):
        bare = self.home / "Git/storage.git"
        self.git("clone", "-q", "--bare", str(self.repo), str(bare))
        self.git("-C", str(bare), "repack", "-adq")
        self.git("-C", str(self.repo), "checkout", "--detach", "-q")
        report = self.probe([str(self.repo), str(bare)])
        self.assertTrue(all(row["status"] == "checked" for row in report["repositories"]), report)
        self.assertEqual(sum(row["bare"] for row in report["repositories"]), 1)

    def test_external_worktree_redirect_is_not_read(self):
        external = self.home / "unselected"
        external.mkdir()
        self.git("-C", str(self.repo), "config", "core.worktree", str(external))
        report = self.probe()["repositories"][0]
        self.assertEqual(report["status"], "needs_review")

    def test_linked_worktrees_use_restored_data_after_old_home_disappears(self):
        linked = self.home / ".codex/worktrees/linked task"
        self.git("-C", str(self.repo), "branch", "fixture-local")
        self.git("-C", str(self.repo), "worktree", "add", "-q", str(linked), "fixture-local")
        (linked / "work.txt").write_text("linked unstaged fixture\n")
        (self.repo / "new.txt").write_text("staged fixture\n")
        self.git("-C", str(self.repo), "add", "new.txt")
        self.git("-C", str(self.repo), "stash", "push", "-qm", "fixture stash")
        (self.repo / "untracked.txt").write_text("unfinished fixture\n")
        roots = [str(self.repo), str(self.home / ".codex/worktrees")]
        plan = inspect_git(str(self.home), roots, lambda: None)
        self.assertEqual(plan.issues, [])
        self.assertEqual(plan.missing_paths, [])
        source = probe_local(str(self.home), roots, plan.repositories)
        self.assertTrue(all(row["status"] == "checked" for row in source["repositories"]), source)
        source_bytes = freeze_tree(str(self.home))
        with tempfile.TemporaryDirectory() as target_temp:
            target = Path(target_temp).resolve()
            shutil.copytree(self.home, target, dirs_exist_ok=True, symlinks=True)
            def mapped(path):
                return str(target / Path(path).relative_to(self.home))
            target_roots = [mapped(root) for root in roots]
            target_plan = [{"path": mapped(row["path"]), "git_dir": mapped(row["git_dir"]),
                            "kind": row["kind"]} for row in plan.repositories]
            offline = self.home.with_name(self.home.name + "-offline")
            self.home.rename(offline)
            try:
                missing_alias = probe_local(str(target), target_roots, target_plan)
                self.assertTrue(any(row["status"] == "needs_review" for row in missing_alias["repositories"]))
                self.home.symlink_to(target)
                restored = probe_local(str(target), target_roots, target_plan)
                self.assertEqual(restored, source)
                self.assertEqual(freeze_tree(str(offline)), source_bytes)
                self.assertEqual(freeze_tree(str(target)), source_bytes)
            finally:
                if self.home.is_symlink():
                    self.home.unlink()
                offline.rename(self.home)

    def test_stalled_probe_cancellation_reaps_the_process_group(self):
        import time
        from codex_migrate import git_probe
        launched = []
        original = subprocess.Popen
        def record(*args, **kwargs):
            child = original(*args, **kwargs)
            launched.append(child)
            return child
        started = time.monotonic()
        def cancel():
            if launched and time.monotonic() - started > 0.25:
                raise InterruptedError("fixture cancelled")
        with patch("codex_migrate.git_probe.RUNNER", "sleep 30;" + RUNNER):
            with patch("codex_migrate.git_probe.subprocess.Popen", side_effect=record):
                with self.assertRaises(InterruptedError):
                    probe_local(str(self.home), [str(self.repo)], [], cancel)
        self.assertEqual(len(launched), 1)
        self.assertIsNotNone(launched[0].poll())

    def test_closed_pipes_do_not_bypass_child_deadline(self):
        import time
        prefix = RUNNER.split("my $result;", 1)[0].replace("time() + 300", "time() + 0.1")
        program = prefix + """
            my $ok = eval { execute('/usr/bin/perl', '-e', 'close STDOUT; close STDERR; sleep 30;'); 1; };
            exit($ok ? 0 : 79);
        """
        start = time.monotonic()
        result = subprocess.run(["/usr/bin/env", "-i", "/usr/bin/perl", "-e", program],
                                capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 79)
        self.assertLess(time.monotonic() - start, 3)
        self.assertEqual(result.stdout + result.stderr, b"")


if __name__ == "__main__":
    unittest.main()
