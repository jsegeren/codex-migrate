import unittest

from codex_migrate.cli import _config, parser


class CLIStagingTests(unittest.TestCase):
    def arguments(self, *extra):
        return parser().parse_args(['serve', '--target', 'new@new.local',
                                    '--target-home', '/Users/new',
                                    '--source-home', '/Users/source',
                                    '--state-dir', '/Users/source/.migration-fixture', *extra])

    def test_default_is_unchanged_and_read_only(self):
        config = _config(self.arguments())
        self.assertEqual(config.staging_name, 'Codex-Migrate-Staging')
        self.assertFalse(config.apply)

    def test_isolated_staging_is_bound_to_destination(self):
        config = _config(self.arguments('--staging-name', 'Codex-Migrate-Authentic-Staging-20260906'))
        self.assertEqual(config.target_staging,
                         '/Users/new/Codex-Migrate-Authentic-Staging-20260906')

    def test_unsafe_and_protected_names_are_rejected(self):
        for name in ('../elsewhere', '/tmp/staging', '.codex', '.SSH', 'bad;command'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                _config(self.arguments('--staging-name', name))
