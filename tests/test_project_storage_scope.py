"""Disposable project configuration scope fixtures; no real Codex account reads."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from codex_migrate.errors import MigrationError
from codex_migrate.inventory import collect
from codex_migrate.storage_scope import require_project_storage, RUNNER


class ProjectStorageScopeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        (self.home / ".codex/sessions").mkdir(parents=True)
        self.workspace = self.home / "Git/repo"
        self.workspace.mkdir(parents=True)

    def config(self, root, text='sqlite_home = "PRIVATE_FIXTURE"'):
        path = root / ".codex/config.toml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_selected_project_storage_override_blocks_full_inventory(self):
        config = self.config(self.workspace)
        with self.assertRaisesRegex(MigrationError, "sqlite_home setting") as error:
            collect(str(self.home), [str(self.workspace)])
        self.assertNotIn("PRIVATE_FIXTURE", str(error.exception))
        self.assertEqual(config.read_text(), 'sqlite_home = "PRIVATE_FIXTURE"')

    def test_nested_ancestor_and_managed_worktree_layers_are_screened(self):
        for root in (self.workspace / "nested", self.workspace.parent,
                     self.home / ".codex/worktrees/fixture/repo"):
            with self.subTest(root=root.name):
                config = self.config(root)
                with self.assertRaisesRegex(MigrationError, "sqlite_home setting"):
                    require_project_storage(str(self.home), [str(self.workspace)])
                config.unlink()

    def test_project_profile_and_escaped_key_cannot_hide_storage(self):
        config = self.config(self.workspace, '"\\u0073qlite_home" = "PRIVATE_FIXTURE"')
        config.rename(config.with_name("Review.CONFIG.TOML"))
        with self.assertRaisesRegex(MigrationError, "sqlite_home setting"):
            require_project_storage(str(self.home), [str(self.workspace)])

    def test_normal_settings_comments_and_profile_values_are_preserved(self):
        text = '# sqlite_home = "example"\nmodel = "example-model"\nnotice = "sqlite_home"\n'
        config = self.config(self.workspace, text)
        require_project_storage(str(self.home), [str(self.workspace)])
        self.assertEqual(config.read_text(), text)

    def test_project_config_cannot_read_account_identity_hardlink(self):
        identity = self.home / ".codex/auth.json"
        identity.write_text("PRIVATE_FIXTURE")
        config = self.config(self.workspace, "# ordinary fixture")
        config.unlink()
        os.link(identity, config)
        # Reaching sysopen would escape the expected error path with status 97.
        injected = RUNNER.replace('sysopen(my $fh, $path,', 'exit 97; sysopen(my $fh, $path,')
        with patch("codex_migrate.storage_scope.RUNNER", injected), \
             patch("codex_migrate.storage_scope.MESSAGES", {67: "identity blocked before open"}):
            with self.assertRaisesRegex(MigrationError, "identity blocked before open"):
                require_project_storage(str(self.home), [str(self.workspace)])
        self.assertEqual(identity.read_text(), "PRIVATE_FIXTURE")

    def test_project_config_directory_link_requires_review(self):
        external = self.home / "external"
        self.config(external)
        (self.workspace / ".codex").symlink_to(external / ".codex")
        with self.assertRaisesRegex(MigrationError, "could not be safely checked"):
            require_project_storage(str(self.home), [str(self.workspace)])

    def test_ordinary_directory_links_are_not_traversed(self):
        external = self.home / "external"
        self.config(external)
        (self.workspace / "preserved-link").symlink_to(external)
        require_project_storage(str(self.home), [str(self.workspace)])

    def test_layer_count_is_bounded_before_launching_more_readers(self):
        for index in range(1025):
            (self.workspace / str(index) / ".codex").mkdir(parents=True)
        with patch("codex_migrate.storage_scope.require_source_storage") as reader:
            with self.assertRaisesRegex(MigrationError, "Too many project configuration layers"):
                require_project_storage(str(self.home), [str(self.workspace)])
        self.assertEqual(reader.call_count, 1024)

    def test_external_or_linked_selection_is_rejected_before_readers(self):
        alias = self.home / "linked-selection"
        alias.symlink_to(self.workspace)
        with patch("codex_migrate.storage_scope.require_source_storage", side_effect=AssertionError("No reader")):
            for root in (alias, self.home.parent):
                with self.assertRaises(MigrationError):
                    require_project_storage(str(self.home), [str(root)])

    def test_parent_alias_is_resolved_without_skipping_project_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            alias = Path(directory) / "home-alias"
            alias.symlink_to(self.home, target_is_directory=True)
            selected = alias / "Git/repo"
            require_project_storage(str(alias), [str(selected)])
            self.config(self.workspace)
            with self.assertRaisesRegex(MigrationError, "sqlite_home setting"):
                require_project_storage(str(alias), [str(selected)])

    def test_stop_prevents_scanning_and_read_errors_do_not_skip_layers(self):
        def stop():
            raise InterruptedError("stopped")
        with patch("codex_migrate.storage_scope.walk_local", side_effect=AssertionError("No scan")):
            with self.assertRaises(InterruptedError):
                require_project_storage(str(self.home), [str(self.workspace)], stop)
        def unreadable(_root, *, onerror):
            onerror(PermissionError("PRIVATE_FIXTURE"))
        with patch("codex_migrate.storage_scope.walk_local", unreadable):
            with self.assertRaisesRegex(MigrationError, "could not be safely checked") as error:
                require_project_storage(str(self.home), [str(self.workspace)])
        self.assertNotIn("PRIVATE_FIXTURE", str(error.exception))

    def test_changed_project_scope_blocks_resume_and_install_without_destination_changes(self):
        import test_full_skills as fixtures
        fixture = fixtures.FullSkillTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.prepare()
        config = self.config(fixture.source / ".codex/worktrees/project")
        with patch.object(fixture.engine.transport, "rsync_process", side_effect=AssertionError("No copy")):
            with self.assertRaisesRegex(MigrationError, "sqlite_home setting"):
                fixture.engine._copy_all()
        with patch.object(fixture.engine.transport, "run_remote", side_effect=AssertionError("No install")):
            with self.assertRaisesRegex(MigrationError, "sqlite_home setting"):
                fixture.engine._install_and_verify()
        fixture.assert_destination_original()
        self.assertTrue(Path(fixture.config.target_staging).is_dir())
        self.assertEqual(config.read_text(), 'sqlite_home = "PRIVATE_FIXTURE"')
