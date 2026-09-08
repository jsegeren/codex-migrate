"""CLI state ownership tests; no SSH, user homes or live dashboard operations."""
import contextlib
from dataclasses import replace
import io
import os
from pathlib import Path
import tempfile
import select
import signal
import subprocess
import sys
import unittest
from unittest.mock import patch

from codex_migrate import cli
from codex_migrate.state import StateStore, public_state


class CLIBindingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        self.state_dir = self.home / 'migration-state'
        self.arguments = ['serve', '--target', 'new@new.local',
                          '--target-home', '/Users/new', '--source-home', str(self.home),
                          '--state-dir', str(self.state_dir), '--no-open']

    def test_existing_unbound_migration_is_not_assigned_a_new_destination(self):
        store = StateStore(str(self.state_dir))
        store.update(status='ready_to_finalize', migration_id='a' * 32, staging_complete=True)
        before = store.path.read_bytes()
        with patch.object(cli, 'MigrationEngine') as engine, patch.object(cli, 'Dashboard') as dashboard, \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(self.arguments), 2)
        engine.assert_not_called()
        dashboard.assert_not_called()
        self.assertEqual(store.path.read_bytes(), before)

    def config(self):
        return cli._config(cli.parser().parse_args(self.arguments))

    def test_fresh_state_resumes_with_same_binding_and_preserves_progress(self):
        config = self.config()
        with cli._bound_state(config) as store:
            store.update(status='ready_to_finalize', migration_id='a' * 32, staging_complete=True)
        before = store.path.read_bytes()
        with cli._bound_state(replace(config, apply=True, compress=False)) as resumed:
            self.assertTrue(resumed.read()['staging_complete'])
        self.assertEqual(store.path.read_bytes(), before)

    def test_changed_scope_and_destination_rejected_without_writes(self):
        config = self.config()
        with cli._bound_state(config) as store:
            store.update(status='complete', receipt={'verified': True})
        before = store.path.read_bytes()
        for change in ({'source_home': str(self.home / 'other')},
                       {'target': 'someone@other.local'}, {'target_home': '/Users/other'},
                       {'workspace_roots': [str(self.home / 'project')]},
                       {'staging_name': 'Another-Stage'}, {'backup_prefix': 'Another-Backup'}):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                with cli._bound_state(replace(config, **change)):
                    self.fail('mismatched configuration was accepted')
            self.assertEqual(store.path.read_bytes(), before)
        with self.assertRaises(RuntimeError):
            with cli._bound_state(config, ['personal-skills']):
                self.fail('mode change was accepted')
        self.assertEqual(store.path.read_bytes(), before)

    def test_components_are_order_independent_but_cannot_change(self):
        config = self.config()
        with cli._bound_state(config, ['workspace-skills', 'personal-skills']):
            pass
        with cli._bound_state(config, ['personal-skills', 'workspace-skills', 'personal-skills']):
            pass
        with self.assertRaises(RuntimeError):
            with cli._bound_state(config, ['personal-skills']):
                self.fail('component removal was accepted')

    def test_existing_process_lock_prevents_binding(self):
        config = self.config()
        other = StateStore(config.state_dir)
        other.acquire_process_lock()
        try:
            before = other.path.read_bytes()
            with self.assertRaises(RuntimeError):
                with cli._bound_state(config):
                    self.fail('second process acquired state')
            self.assertEqual(other.path.read_bytes(), before)
        finally:
            other.release_process_lock()

    def test_constructor_failure_releases_lock_and_does_not_start_dashboard(self):
        with patch.object(cli, 'MigrationEngine', side_effect=RuntimeError('fixture failure')), \
                patch.object(cli, 'Dashboard') as dashboard, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(self.arguments), 2)
        dashboard.assert_not_called()
        with cli._bound_state(self.config()):
            pass

    def test_mismatch_blocks_engine_and_dashboard_before_startup(self):
        with cli._bound_state(self.config()):
            pass
        with patch.object(cli, 'MigrationEngine') as engine, patch.object(cli, 'Dashboard') as dashboard, \
                contextlib.redirect_stderr(io.StringIO()) as output:
            self.assertEqual(cli.main(self.arguments + ['--staging-name', 'Other-Stage']), 2)
        engine.assert_not_called()
        dashboard.assert_not_called()
        self.assertNotIn(str(self.home), output.getvalue())
        self.assertNotIn('Other-Stage', output.getvalue())

    def test_binding_excludes_credentials_and_public_state(self):
        config = self.config()
        private_path = str(self.home / 'private-key-placeholder')
        config = replace(config, ssh=replace(config.ssh, identity_file=private_path))
        with cli._bound_state(config) as store:
            saved = store.read()
            self.assertNotIn(private_path, store.path.read_text())
            self.assertNotIn('configuration_binding', public_state(saved))
            self.assertIn('configuration_binding', saved)

    def test_binding_write_failure_releases_lock_without_partial_adoption(self):
        config = self.config()
        original = StateStore(config.state_dir).path.read_bytes()
        with patch.object(StateStore, 'write', side_effect=OSError('fixture write failure')):
            with self.assertRaises(OSError):
                with cli._bound_state(config):
                    self.fail('write failure ignored')
        self.assertEqual(StateStore(config.state_dir).path.read_bytes(), original)
        with cli._bound_state(config):
            pass

    def test_binding_requires_lock_and_rejects_malformed_saved_evidence(self):
        store = StateStore(str(self.state_dir))
        with self.assertRaises(RuntimeError):
            store.bind_configuration({'version': 1})
        store.update(configuration_binding=None)
        before = store.path.read_bytes()
        with self.assertRaises(RuntimeError):
            with cli._bound_state(self.config()):
                self.fail('malformed binding accepted')
        self.assertEqual(store.path.read_bytes(), before)

    def test_real_cli_starts_reopens_and_rejects_changed_destination(self):
        environment = {**os.environ, 'PYTHONPATH': str(Path(cli.__file__).resolve().parents[1])}
        command = [sys.executable, '-m', 'codex_migrate', *self.arguments, '--port', '0']
        for _ in range(2):
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       env=environment)
            try:
                ready, _, _ = select.select([process.stdout], [], [], 10)
                self.assertTrue(ready, 'CLI did not become ready')
                # This line carries a local control token; never print it in assertions.
                self.assertTrue(process.stdout.readline().startswith(b'Codex Migrate dashboard: http://127.0.0.1:'))
                process.send_signal(signal.SIGINT)
                process.communicate(timeout=10)
                self.assertEqual(process.returncode, 130)
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=10)
        before = (self.state_dir / 'state.json').read_bytes()
        result = subprocess.run(command + ['--target', 'other@elsewhere.local'],
                                capture_output=True, env=environment, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b'')
        self.assertEqual((self.state_dir / 'state.json').read_bytes(), before)
