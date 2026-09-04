import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from codex_migrate.errors import MigrationError
from codex_migrate.storage_scope import RUNNER, require_source_storage, storage_scope_script


class StorageScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve() / "home with space"
        self.codex = self.home / ".codex"
        self.codex.mkdir(parents=True)

    def run_guard(self, env=None, home=None):
        clean = dict(os.environ)
        clean.pop("CODEX_HOME", None)
        clean.update(env or {})
        result = subprocess.run(["/bin/zsh", "-f", "-s"],
                                input=storage_scope_script(str(home or self.home)),
                                capture_output=True, text=True, env=clean, timeout=5)
        self.assertEqual(result.stdout, "")
        self.assertNotIn("PRIVATE_FIXTURE", result.stderr)
        return result.returncode

    def test_default_and_equivalent_visible_home_are_allowed(self):
        self.assertEqual(self.run_guard(), 0)
        self.assertEqual(self.run_guard({"CODEX_HOME": str(self.codex)}), 0)
        self.assertEqual(self.run_guard({"CODEX_HOME": ""}), 0)
        alias = self.home / "alias"
        alias.symlink_to(self.codex)
        self.assertEqual(self.run_guard({"CODEX_HOME": str(alias)}), 0)

    def test_custom_home_blocks_even_with_default_state_present(self):
        other = self.home / "PRIVATE_FIXTURE"
        other.mkdir()
        self.assertEqual(self.run_guard({"CODEX_HOME": str(other)}), 65)
        self.assertEqual(self.run_guard({"CODEX_HOME": str(other / "absent")}), 65)

    def test_sqlite_keys_in_base_legacy_and_current_profiles_are_blocked(self):
        cases = [
            'sqlite_home = "PRIVATE_FIXTURE"',
            '"sqlite_home" = "PRIVATE_FIXTURE"',
            "'sqlite_home' = 'PRIVATE_FIXTURE'",
            '"\\u0073qlite_home" = "PRIVATE_FIXTURE"',
            '"sqlite\\U0000005fhome" = "PRIVATE_FIXTURE"',
            '[profiles.work]\nsqlite_home = "PRIVATE_FIXTURE"',
            'profiles.work.sqlite_home = "PRIVATE_FIXTURE"',
            'profiles = { work = { "sqlite_home" = "PRIVATE_FIXTURE" } }',
        ]
        for name in ("config.toml", "work.config.toml", "CONFIG.TOML", "WORK.CONFIG.TOML"):
            for value in cases:
                with self.subTest(name=name, value=value):
                    path = self.codex / name
                    path.write_text(value)
                    self.assertEqual(self.run_guard(), 66)
                    path.unlink()

    def test_comments_and_values_are_not_mistaken_for_storage_keys(self):
        (self.codex / "config.toml").write_text('''# sqlite_home = "not a setting"
model = "example"
notice = "sqlite_home = 'PRIVATE_FIXTURE'"
literal = 'sqlite_home = "PRIVATE_FIXTURE"'
multi = """example:
sqlite_home = 'PRIVATE_FIXTURE'
"""
other = ''' + "'''sqlite_home = 'PRIVATE_FIXTURE' '''\n")
        (self.codex / "work.config.toml").write_text('model = "another-example"\n')
        self.assertEqual(self.run_guard(), 0)

    def test_symlink_fifo_identity_hardlink_and_oversized_config_fail_closed(self):
        config = self.codex / "config.toml"
        fixture = self.codex / "auth.json"
        fixture.write_text("PRIVATE_FIXTURE")
        config.symlink_to(fixture)
        self.assertEqual(self.run_guard(), 67)
        config.unlink()
        os.link(fixture, config)
        self.assertEqual(self.run_guard(), 67)
        config.unlink()
        os.mkfifo(config)
        self.assertEqual(self.run_guard(), 67)
        config.unlink()
        config.write_bytes(b"a" * (1048576 + 1))
        self.assertEqual(self.run_guard(), 67)

    def test_unclosed_strings_invalid_unicode_and_excess_profile_count_block(self):
        config = self.codex / "config.toml"
        for text in ('value = "PRIVATE_FIXTURE', '"\\Uffffffff" = "PRIVATE_FIXTURE"'):
            config.write_text(text)
            self.assertEqual(self.run_guard(), 67)
        config.unlink()
        for index in range(65):
            (self.codex / (str(index) + ".config.toml")).write_text("# fixture")
        self.assertEqual(self.run_guard(), 67)

    def test_source_environment_is_not_attributed_to_a_different_account_home(self):
        with patch.dict(os.environ, {"CODEX_HOME": "/PRIVATE_FIXTURE"}):
            require_source_storage(str(self.home))
            with patch("codex_migrate.storage_scope.pwd.getpwuid") as account:
                account.return_value.pw_dir = str(self.home)
                with self.assertRaisesRegex(MigrationError, "custom CODEX_HOME"):
                    require_source_storage(str(self.home))

    def test_same_account_home_alias_does_not_skip_visible_environment(self):
        alias = self.home.parent / "account-home-alias"
        alias.symlink_to(self.home)
        with patch.dict(os.environ, {"CODEX_HOME": "/PRIVATE_FIXTURE"}), \
             patch("codex_migrate.storage_scope.pwd.getpwuid") as account:
            account.return_value.pw_dir = str(self.home)
            with self.assertRaisesRegex(MigrationError, "custom CODEX_HOME"):
                require_source_storage(str(alias))
            case_alias = self.home.parent / self.home.name.upper()
            if case_alias.exists() and case_alias.samefile(self.home):
                with self.assertRaisesRegex(MigrationError, "custom CODEX_HOME"):
                    require_source_storage(str(case_alias))

    def test_equivalent_visible_codex_case_alias_is_default_storage(self):
        alias = self.home / ".CODEX"
        if not alias.exists() or not alias.samefile(self.codex):
            self.skipTest("case-sensitive fixture volume")
        self.assertEqual(self.run_guard({"CODEX_HOME": str(alias)}), 0)

    def test_normalized_home_alias_keeps_environment_check(self):
        home = self.home.parent / "Café-home"
        (home / ".codex").mkdir(parents=True)
        alias = home.with_name("Cafe\u0301-home")
        if not alias.exists() or not alias.samefile(home):
            self.skipTest("normalization-sensitive fixture volume")
        with patch.dict(os.environ, {"CODEX_HOME": "/PRIVATE_FIXTURE"}), \
             patch("codex_migrate.storage_scope.pwd.getpwuid") as account:
            account.return_value.pw_dir = str(home)
            with self.assertRaisesRegex(MigrationError, "custom CODEX_HOME"):
                require_source_storage(str(alias))

    def test_directory_read_errors_are_not_successful_end_of_scan(self):
        (self.codex / "config.toml").write_text('sqlite_home = "PRIVATE_FIXTURE"')
        (self.codex / "safe.config.toml").write_text('# harmless fixture')
        for replacement in ("my $name; $! = 5;",
                            "my $name = $entries == 0 ? 'safe.config.toml' : undef; $! = 5 if !defined($name);"):
            with self.subTest(replacement=replacement), \
                 patch("codex_migrate.storage_scope.RUNNER", RUNNER.replace("my $name = readdir($dh);", replacement)):
                self.assertEqual(self.run_guard(), 67)

    def test_inventory_blocks_before_scanning_transcripts_or_workspace_contents(self):
        from codex_migrate.inventory import collect
        (self.codex / "config.toml").write_text('sqlite_home = "PRIVATE_FIXTURE"')
        with patch("codex_migrate.inventory._tree_summary", side_effect=AssertionError("scanned contents")):
            with self.assertRaisesRegex(MigrationError, "sqlite_home setting"):
                collect(str(self.home), [])

    def test_source_check_can_be_cancelled(self):
        def stop():
            raise MigrationError("Stopped fixture")
        with patch("codex_migrate.storage_scope.subprocess.Popen", side_effect=AssertionError("launched")):
            with self.assertRaisesRegex(MigrationError, "Stopped fixture"):
                require_source_storage(str(self.home), stop)

    def test_cancellation_reaps_a_real_running_check(self):
        original = subprocess.Popen
        children = []
        calls = 0
        def launch(*args, **kwargs):
            child = original(*args, **kwargs)
            children.append(child)
            return child
        def checkpoint():
            nonlocal calls
            calls += 1
            if calls >= 3:
                raise MigrationError("Stopped running fixture")
        with patch("codex_migrate.storage_scope.storage_scope_script", return_value="exec /bin/sleep 30\n"), \
             patch("codex_migrate.storage_scope.subprocess.Popen", side_effect=launch):
            with self.assertRaisesRegex(MigrationError, "Stopped running fixture"):
                require_source_storage(str(self.home), checkpoint)
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())
