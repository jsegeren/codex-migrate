"""Conservative reference detection, not a TOML or role-policy resolver."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from codex_migrate.errors import MigrationError
from codex_migrate.inventory import collect
from codex_migrate.storage_scope import require_source_storage, require_project_storage


class RoleScopeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name).resolve()
        self.codex = self.home / ".codex"
        self.codex.mkdir()

    def test_literal_dotted_inline_quoted_and_escaped_reference_keys_require_review(self):
        for key in ('config_file', '"config_file"', "'config_file'", '"config\\u005ffile"'):
            for content in ('[agents.reviewer]\n%s = "PRIVATE_FIXTURE"',
                            'agents.reviewer.%s = "PRIVATE_FIXTURE"',
                            'agents = { reviewer = { %s = "PRIVATE_FIXTURE" } }'):
                for name in ('config.toml', 'work.config.toml', 'CONFIG.TOML'):
                    with self.subTest(key=key, content=content, name=name):
                        config = self.codex / name
                        config.write_text(content % key)
                        with self.assertRaisesRegex(MigrationError, 'config_file reference') as error:
                            require_source_storage(str(self.home))
                        self.assertNotIn('PRIVATE_FIXTURE', str(error.exception))
                        config.unlink()

    def test_comment_example_values_and_unrelated_keys_do_not_block(self):
        (self.codex / 'config.toml').write_text('''# config_file = "not a reference"
description = "config_file = 'example'"
developer_instructions = """config_file = 'example'"""
other_config_file = "ordinary"
[agents.reviewer]
description = "A built-in role without a separate config file"
''')
        require_source_storage(str(self.home))

    def test_reference_stops_inventory_without_reading_target_or_contents(self):
        (self.codex / 'config.toml').write_text('[agents.reviewer]\nconfig_file = "../missing/PRIVATE_FIXTURE.toml"')
        with patch('codex_migrate.inventory._tree_summary', side_effect=AssertionError('No inventory')):
            with self.assertRaisesRegex(MigrationError, 'config_file reference'):
                collect(str(self.home), [])
        self.assertFalse((self.home / 'missing').exists())

    def test_selected_project_role_reference_requires_review_even_for_an_in_scope_file(self):
        project = self.home / 'project'
        (project / '.codex').mkdir(parents=True)
        (project / '.codex/config.toml').write_text('[agents.reviewer]\nconfig_file = "reviewer.toml"')
        target = project / '.codex/reviewer.toml'
        target.write_text('model = "fixture-model"')
        with self.assertRaisesRegex(MigrationError, 'config_file reference'):
            require_project_storage(str(self.home), [str(project)])
        self.assertEqual(target.read_text(), 'model = "fixture-model"')

    def test_retained_destination_ancestor_reference_requires_review(self):
        from test_destination_storage_scope import DestinationStorageScopeTests
        fixture = DestinationStorageScopeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        config = fixture.config(fixture.parent, '[agents.reviewer]\nconfig_file = "PRIVATE_FIXTURE.toml"')
        self.assertEqual(fixture.run_guard(), 70)
        self.assertTrue(config.exists())

    def test_system_defaults_and_managed_defaults_references_require_review(self):
        from test_system_storage_scope import SystemStorageScopeTests
        fixture = SystemStorageScopeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        for name in ('config.toml', 'managed_config.toml'):
            config = fixture.system / name
            config.write_text('[agents.reviewer]\nconfig_file = "PRIVATE_FIXTURE.toml"')
            self.assertEqual(fixture.run_guard(), 70)
            config.unlink()

    def test_late_source_reference_preserves_staging_and_original_destination(self):
        import test_full_skills as fixtures
        fixture = fixtures.FullSkillTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.prepare()
        config = fixture.source / '.codex/config.toml'
        config.write_text('[agents.reviewer]\nconfig_file = "PRIVATE_FIXTURE.toml"')
        with patch.object(fixture.engine.transport, 'rsync_process', side_effect=AssertionError('No copy')):
            for action in (fixture.engine._copy_all, fixture.engine._prepare_install):
                with self.assertRaisesRegex(MigrationError, 'config_file reference'):
                    action()
        fixture.assert_destination_original()
        self.assertTrue(Path(fixture.config.target_staging).exists())

    def test_late_destination_reference_blocks_before_backup_or_replacement(self):
        import test_full_skills as fixtures
        fixture = fixtures.FullSkillTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.prepare()
        prepared = fixture.engine._prepare_install()
        config = fixture.target / '.codex/config.toml'
        config.write_text('[agents.reviewer]\nconfig_file = "PRIVATE_FIXTURE.toml"')
        with self.assertRaisesRegex(RuntimeError, 'config_file reference') as error:
            fixture.engine._install_and_verify(prepared)
        self.assertNotIn('PRIVATE_FIXTURE', str(error.exception))
        self.assertEqual(config.read_text(), '[agents.reviewer]\nconfig_file = "PRIVATE_FIXTURE.toml"')
        fixture.assert_destination_original()
        self.assertEqual(list(fixture.target.glob('Codex-Migrate-Backup-*')), [])
        self.assertTrue(Path(fixture.config.target_staging).exists())
