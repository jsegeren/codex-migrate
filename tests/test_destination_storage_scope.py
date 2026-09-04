"""Run destination guards against disposable local data, never a remote account."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from codex_migrate.errors import MigrationError
from codex_migrate.storage_scope import RUNNER, retained_ancestor_storage_script


class DestinationStorageScopeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve() / "new person's home"
        (self.home / ".codex").mkdir(parents=True)
        self.parent = self.home / "Git"
        self.repo = self.parent / "selected"
        self.repo.mkdir(parents=True)

    def config(self, root, text='sqlite_home = "PRIVATE_FIXTURE"'):
        path = root / ".codex/config.toml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def run_guard(self, roots=None):
        script = retained_ancestor_storage_script(str(self.home), roots or [str(self.repo)])
        result = subprocess.run(["/bin/zsh", "-f", "-s"], input=script,
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.stdout, "")
        self.assertNotIn("PRIVATE_FIXTURE", result.stderr)
        self.assertNotIn(str(self.home), result.stderr)
        return result.returncode

    def test_retained_parent_override_is_rejected_without_mutation(self):
        path = self.config(self.parent)
        before = path.read_bytes()
        self.assertEqual(self.run_guard(), 66)
        self.assertEqual(path.read_bytes(), before)

    def test_normal_and_missing_parents_are_supported(self):
        self.config(self.parent, '# sqlite_home = "example"\nmodel = "example"\n')
        self.assertEqual(self.run_guard(), 0)
        self.assertEqual(self.run_guard([str(self.home / "not-created/deeper/repo")]), 0)

    def test_replaced_root_and_unselected_siblings_are_not_read(self):
        self.config(self.repo)
        self.config(self.parent / "unselected")
        self.assertEqual(self.run_guard(), 0)

    def test_all_retained_parent_layers_and_profiles_are_checked(self):
        deeper = self.repo / "deeper"
        deeper.mkdir()
        path = self.config(self.repo)
        path.rename(path.with_name("custom.CONFIG.TOML"))
        self.assertEqual(self.run_guard([str(deeper)]), 66)

    def test_parent_and_config_links_are_rejected_before_reader_open(self):
        external = self.home / "external"
        self.config(external)
        alias = self.home / "alias"
        alias.symlink_to(external, target_is_directory=True)
        injected = RUNNER.replace('sysopen(my $fh, $path,', 'exit 97; sysopen(my $fh, $path,')
        with patch("codex_migrate.storage_scope.RUNNER", injected):
            self.assertEqual(self.run_guard([str(alias / "repo")]), 67)
            (self.parent / ".codex").symlink_to(external / ".codex")
            self.assertEqual(self.run_guard(), 67)

    def test_identity_hardlink_is_rejected_before_reader_open(self):
        identity = self.home / ".codex/auth.json"
        identity.write_text("PRIVATE_FIXTURE")
        config = self.config(self.parent, "# fixture")
        config.unlink()
        os.link(identity, config)
        injected = RUNNER.replace('sysopen(my $fh, $path,', 'exit 97; sysopen(my $fh, $path,')
        with patch("codex_migrate.storage_scope.RUNNER", injected):
            self.assertEqual(self.run_guard(), 67)
        self.assertEqual(identity.read_text(), "PRIVATE_FIXTURE")

    def test_non_directory_parent_and_external_roots_fail_closed(self):
        regular = self.home / "regular"
        regular.write_text("fixture")
        self.assertEqual(self.run_guard([str(regular / "repo")]), 67)
        for root in (self.home, self.home.parent / "outside", self.home / "../outside"):
            with self.assertRaises(MigrationError):
                retained_ancestor_storage_script(str(self.home), [str(root)])

    def test_duplicate_ancestors_share_one_check_and_count_is_bounded(self):
        script = retained_ancestor_storage_script(str(self.home), [str(self.repo), str(self.parent / "other")])
        self.assertEqual(script.count("cm_check_retained_config "), 1)
        roots = [str(self.home / str(index) / "repo") for index in range(1025)]
        with self.assertRaises(MigrationError):
            retained_ancestor_storage_script(str(self.home), roots)

    def test_user_override_cannot_be_masked_by_successful_parent_check(self):
        import test_full_skills as fixtures
        fixture = fixtures.FullSkillTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        source_repo = fixture.source / "Git/repo"
        source_repo.mkdir(parents=True)
        object.__setattr__(fixture.config, "workspace_roots", [str(source_repo)])
        self.config(fixture.target)
        script = fixture.engine._destination_storage_script()
        result = subprocess.run(["/bin/zsh", "-f", "-s"], input=script,
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 66)
        self.assertEqual(result.stdout, "")

    def test_preflight_runs_parent_guard_before_staging_or_backup(self):
        import test_full_skills as fixtures
        fixture = fixtures.FullSkillTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        source_repo = fixture.source / "Git/repo"
        source_repo.mkdir(parents=True)
        object.__setattr__(fixture.config, "workspace_roots", [str(source_repo)])
        self.config(fixture.target / "Git")
        transport = fixture.engine.transport = Mock()
        transport.check.return_value = ("USER=newperson\nHOME=" + str(fixture.target)
                                        + "\nFILESYSTEM=apfs\n")
        def check(script, timeout, cancelled):
            self.assertFalse(cancelled())
            result = subprocess.run(["/bin/zsh", "-f", "-s"], input=script,
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 66)
            raise MigrationError("Fixture storage guard stopped inspection")
        transport.run_remote_cancellable.side_effect = check
        with patch("codex_migrate.migration.check_compatibility", return_value={"status": "mapped"}):
            with self.assertRaisesRegex(MigrationError, "Fixture storage guard"):
                fixture.engine.preflight()
        transport.run_remote_cancellable.assert_called_once()
        transport.rsync_process.assert_not_called()
        self.assertFalse(Path(fixture.config.target_staging).exists())
        self.assertEqual(list(fixture.target.glob("Codex-Migrate-Backup-*")), [])
        fixture.assert_destination_original()

    def test_parent_changed_after_staging_blocks_before_backup_or_replacement(self):
        import test_full_skills as fixtures
        fixture = fixtures.FullSkillTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        source_repo = fixture.source / "Git/repo"
        source_repo.mkdir(parents=True)
        (source_repo / "new.txt").write_text("new fixture")
        object.__setattr__(fixture.config, "workspace_roots", [str(source_repo)])
        destination_repo = fixture.target / "Git/repo"
        destination_repo.mkdir(parents=True)
        (destination_repo / "old.txt").write_text("old fixture")
        fixture.prepare()
        self.config(destination_repo.parent)
        with self.assertRaisesRegex(RuntimeError, "sqlite_home configuration"):
            fixture.engine._install_and_verify()
        fixture.assert_destination_original()
        self.assertEqual((destination_repo / "old.txt").read_text(), "old fixture")
        self.assertFalse((destination_repo / "new.txt").exists())
        self.assertEqual(list(fixture.target.glob("Codex-Migrate-Backup-*")), [])
        self.assertTrue((Path(fixture.config.target_staging) / "home-relative/Git/repo/new.txt").is_file())

    def test_staged_config_cannot_open_destination_identity_hardlink(self):
        import test_full_skills as fixtures
        fixture = fixtures.FullSkillTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.prepare()
        staged = Path(fixture.config.target_staging) / ".codex/config.toml"
        os.link(fixture.target / ".codex/auth.json", staged)
        with self.assertRaisesRegex(RuntimeError, "could not be safely checked"):
            fixture.engine._install_and_verify()
        fixture.assert_destination_original()
        self.assertEqual(list(fixture.target.glob("Codex-Migrate-Backup-*")), [])
