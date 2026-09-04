"""System config fixtures redirect only the internal reader; never edit /etc."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from codex_migrate.errors import MigrationError
from codex_migrate.inventory import collect
from codex_migrate.storage_scope import RUNNER, require_source_storage, system_storage_script


class SystemStorageScopeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.home = self.root / "home"
        (self.home / ".codex/sessions").mkdir(parents=True)
        self.system = self.root / "system fixtures"
        self.system.mkdir()
        literal = str(self.system).replace("\\", "\\\\").replace("'", "\\'")
        self.runner = RUNNER.replace("$root = '/private/etc/codex';", "$root = '" + literal + "';")
        self.reader = patch("codex_migrate.storage_scope.RUNNER", self.runner)
        self.reader.start()
        self.addCleanup(self.reader.stop)

    def run_guard(self):
        result = subprocess.run(["/bin/zsh", "-f", "-s"],
                                input=system_storage_script(str(self.home)),
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.stdout, "")
        self.assertNotIn("PRIVATE_FIXTURE", result.stderr)
        self.assertNotIn(str(self.system), result.stderr)
        return result.returncode

    def test_system_and_managed_default_storage_keys_require_review(self):
        for name in ("config.toml", "managed_config.toml", "MANAGED_CONFIG.TOML"):
            path = self.system / name
            path.write_text('"\\u0073qlite_home" = "PRIVATE_FIXTURE"')
            self.assertEqual(self.run_guard(), 66)
            self.assertEqual(path.read_text(), '"\\u0073qlite_home" = "PRIVATE_FIXTURE"')
            path.unlink()

    def test_missing_system_directory_and_ordinary_settings_are_allowed(self):
        self.system.rmdir()
        self.assertEqual(self.run_guard(), 0)
        self.system.mkdir()
        (self.system / "config.toml").write_text('model = "example"\n')
        (self.system / "managed_config.toml").write_text('# sqlite_home = "comment"\n')
        self.assertEqual(self.run_guard(), 0)

    def test_unrelated_files_and_requirements_are_not_parsed_as_defaults(self):
        for name in ("requirements.toml", "irrelevant.config.toml", "private.txt"):
            (self.system / name).write_text('sqlite_home = "PRIVATE_FIXTURE"')
        self.assertEqual(self.run_guard(), 0)

    def test_links_special_files_and_identity_hardlinks_fail_before_content_reads(self):
        identity = self.home / ".codex/auth.json"
        identity.write_text("PRIVATE_FIXTURE")
        path = self.system / "managed_config.toml"
        injected = self.runner.replace('sysopen(my $fh, $path,', 'exit 97; sysopen(my $fh, $path,')
        with patch("codex_migrate.storage_scope.RUNNER", injected):
            path.symlink_to(identity)
            self.assertEqual(self.run_guard(), 67)
            path.unlink()
            os.link(identity, path)
            self.assertEqual(self.run_guard(), 67)
            path.unlink()
            os.mkfifo(path)
            self.assertEqual(self.run_guard(), 67)
        self.assertEqual(identity.read_text(), "PRIVATE_FIXTURE")

    def test_linked_system_directory_is_rejected(self):
        self.system.rmdir()
        self.system.symlink_to(self.home / ".codex", target_is_directory=True)
        self.assertEqual(self.run_guard(), 67)

    def test_nonstandard_etc_alias_is_rejected_before_configuration_reads(self):
        runner = self.runner.replace("my @alias = stat('/etc');", "my @alias = stat('/');")
        with patch("codex_migrate.storage_scope.RUNNER", runner):
            self.assertEqual(self.run_guard(), 67)

    def test_oversized_and_malformed_defaults_require_review(self):
        path = self.system / "config.toml"
        for content in ("x" * 1048577, 'notice = "unclosed'):
            path.write_text(content)
            self.assertEqual(self.run_guard(), 67)

    def test_source_inventory_stops_before_content_inventory(self):
        (self.system / "config.toml").write_text('sqlite_home = "PRIVATE_FIXTURE"')
        with patch("codex_migrate.inventory._tree_summary", side_effect=AssertionError("No content inventory")):
            with self.assertRaisesRegex(MigrationError, "sqlite_home setting"):
                collect(str(self.home), [])

    def test_source_system_failure_cannot_be_masked_by_safe_user_config(self):
        (self.system / "managed_config.toml").write_text('sqlite_home = "PRIVATE_FIXTURE"')
        (self.home / ".codex/config.toml").write_text('model = "example"')
        with self.assertRaisesRegex(MigrationError, "sqlite_home setting"):
            require_source_storage(str(self.home))

    def test_source_project_reader_does_not_repeat_machine_check(self):
        (self.system / "config.toml").write_text('sqlite_home = "PRIVATE_FIXTURE"')
        project = self.home / "project"
        project.mkdir()
        require_source_storage(str(project), identity_home=str(self.home))

    def test_destination_script_retains_system_failure(self):
        import test_full_skills as fixtures
        fixture = fixtures.FullSkillTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        (self.system / "managed_config.toml").write_text('sqlite_home = "PRIVATE_FIXTURE"')
        result = subprocess.run(["/bin/zsh", "-f", "-s"], input=fixture.engine._destination_storage_script(),
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 66)
        self.assertEqual(result.stdout, "")
        fixture.assert_destination_original()

    def test_late_source_system_override_stops_resume_without_copy(self):
        import test_full_skills as fixtures
        fixture = fixtures.FullSkillTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.prepare()
        (self.system / "config.toml").write_text('sqlite_home = "PRIVATE_FIXTURE"')
        with patch.object(fixture.engine.transport, "rsync_process", side_effect=AssertionError("No copy")):
            with self.assertRaisesRegex(MigrationError, "sqlite_home setting"):
                fixture.engine._copy_all()
        fixture.assert_destination_original()
        self.assertTrue(Path(fixture.config.target_staging).exists())

    def test_late_destination_default_blocks_prepared_install_before_backup(self):
        import test_full_skills as fixtures
        fixture = fixtures.FullSkillTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.prepare()
        prepared = fixture.engine._prepare_install()
        (self.system / "managed_config.toml").write_text('sqlite_home = "PRIVATE_FIXTURE"')
        with self.assertRaisesRegex(RuntimeError, "sqlite_home configuration"):
            fixture.engine._install_and_verify(prepared)
        fixture.assert_destination_original()
        self.assertEqual(list(fixture.target.glob("Codex-Migrate-Backup-*")), [])
        self.assertTrue(Path(fixture.config.target_staging).exists())
