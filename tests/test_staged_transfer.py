"""Phase sequencing, fail-closed retry and real source-change rejection."""

from dataclasses import replace
import platform
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from codex_migrate.errors import MigrationError
from codex_migrate.migration import MigrationEngine
from codex_migrate.staging_permissions import transfer_staged
from codex_migrate.transport import rsync_phase_options

import test_full_skills as fixtures


class StagedTransferTests(unittest.TestCase):
    def run_transfer(self, *, fail=None, stop=None):
        calls = []
        active = []
        stopped = False
        guard_index = 0
        def checkpoint():
            if stopped:
                raise MigrationError('Stopped fixture')
        class Transport:
            def run_remote_cancellable(self, script, timeout, cancelled):
                nonlocal guard_index, stopped
                guard_index += 1
                name = 'guard%d' % guard_index
                calls.append(name)
                self_check.assertIn('.codex-migrate-destination.lock', script)
                self_check.assertIn('.codex-migrate-owner', script)
                self_check.assertIn('O_NOFOLLOW', script)
                self_check.assertEqual(timeout, 1800)
                self_check.assertFalse(cancelled())
                if name == fail:
                    raise RuntimeError('Injected fixture failure')
                if name == stop:
                    stopped = True

            def rsync_process(self, source, destination, excludes, copy_links, phase):
                self_check.assertEqual(source, '/source/skill')
                self_check.assertEqual(destination, '/home/staging/skill')
                self_check.assertEqual(excludes, ('/auth.json', '/installation_id'))
                self_check.assertTrue(copy_links)
                class Process:
                    def start(self, callback):
                        nonlocal stopped
                        calls.append(phase)
                        callback('fixture progress')
                        if phase == fail:
                            raise RuntimeError('Injected fixture failure')
                        if phase == stop:
                            stopped = True
                return Process()
        self_check = self
        def run():
            transfer_staged(Transport(), '/home', '/home/staging', '/home/staging/skill',
                            'a' * 32, '/source/skill', ('/auth.json', '/installation_id'),
                            copy_links=True, on_output=lambda line: None,
                            on_process=active.append, checkpoint=checkpoint,
                            cancelled=lambda: stopped)
        return run, calls, active

    def test_every_phase_uses_same_scope_and_normal_guards(self):
        run, calls, active = self.run_transfer()
        run()
        self.assertEqual(calls, ['guard1', 'data', 'guard2', 'metadata', 'modes', 'guard3'])
        self.assertEqual(len(active), 6)
        self.assertIsNone(active[-1])

    def test_failure_at_each_boundary_never_falls_back_or_continues(self):
        expected = ['guard1', 'data', 'guard2', 'metadata', 'modes', 'guard3']
        for failure in expected:
            with self.subTest(failure=failure):
                run, calls, active = self.run_transfer(fail=failure)
                with self.assertRaisesRegex(RuntimeError, 'Injected'):
                    run()
                self.assertEqual(calls, expected[:expected.index(failure) + 1])
                if active:
                    self.assertIsNone(active[-1])
                # A retry starts with validation and data, not the failed phase.
                retry, retry_calls, _ = self.run_transfer()
                retry()
                self.assertEqual(retry_calls, expected)

    def test_stop_at_each_boundary_prevents_next_phase(self):
        expected = ['guard1', 'data', 'guard2', 'metadata', 'modes', 'guard3']
        for boundary in expected:
            with self.subTest(boundary=boundary):
                run, calls, active = self.run_transfer(stop=boundary)
                with self.assertRaisesRegex(MigrationError, 'Stopped'):
                    run()
                self.assertEqual(calls, expected[:expected.index(boundary) + 1])
                if active:
                    self.assertIsNone(active[-1])

    def test_cancel_after_process_registration_prevents_spawn(self):
        started = []
        cancelled = False
        class Transport:
            def run_remote_cancellable(self, script, timeout, cancel):
                pass
            def rsync_process(self, *args, **kwargs):
                class Process:
                    def start(self):
                        started.append(True)
                return Process()
        def register(process):
            nonlocal cancelled
            if process is not None:
                cancelled = True
        with self.assertRaisesRegex(MigrationError, 'Staging stopped'):
            transfer_staged(Transport(), '/home', '/home/staging', '/home/staging/skill',
                            'a' * 32, '/source/skill', on_process=register,
                            cancelled=lambda: cancelled)
        self.assertEqual(started, [])

    def test_phase_options_never_drop_metadata_or_restore_modes_early(self):
        self.assertEqual(rsync_phase_options('data'), ['-a'])
        self.assertEqual(rsync_phase_options('metadata'), ['-aE', '--no-perms'])
        self.assertEqual(rsync_phase_options('modes'), ['-a'])
        with self.assertRaises(ValueError):
            rsync_phase_options('fallback')


@unittest.skipUnless(platform.system() == 'Darwin', 'real Mac staging fixtures')
class StagedSourceChangeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.FullSkillTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.workspace = self.fixture.source / 'workspaces'
        self.workspace.mkdir()
        self.source_file = self.workspace / 'work.txt'
        self.source_file.write_text('source fixture')
        self.fixture.config = replace(self.fixture.config,
                                      workspace_roots=[str(self.workspace)]).validate()
        self.engine = MigrationEngine(self.fixture.config, self.fixture.state)
        self.fixture.engine = self.engine
        self.fixture.prepare()
        self.engine.state.update(staged_personal_skills=[skill.as_dict() for skill in self.engine._skill_plan()],
                                 staging_complete=True)

    def finalize(self):
        with patch.object(self.engine, 'preflight'), \
             patch.object(self.engine, '_remote_codex_state', return_value='CLOSED'), \
             patch('codex_migrate.migration.codex_running', return_value=False):
            self.engine._run_finalize()

    def inject_after_metadata(self, change):
        factory = self.engine.transport.rsync_process
        changed = False
        def transfer(source, destination, **options):
            nonlocal changed
            process = factory(source, destination, **options)
            original = process.start
            def start(*args):
                nonlocal changed
                original(*args)
                if not changed and options.get('phase') == 'metadata' and source == str(self.workspace):
                    change()
                    changed = True
            process.start = start
            return process
        self.engine.transport.rsync_process = transfer

    def test_new_file_between_metadata_and_modes_blocks_install(self):
        self.inject_after_metadata(lambda: (self.workspace / 'new file').write_text('late fixture'))
        with self.assertRaisesRegex(MigrationError, 'Source files changed during staging'):
            self.finalize()
        self.fixture.assert_destination_original()
        self.assertFalse((self.fixture.target / 'workspaces').exists())
        self.assertFalse(self.engine.state.read()['staging_complete'])
        self.assertEqual(list(self.fixture.target.glob('Codex-Migrate-Backup-*')), [])

    def test_rewrite_between_metadata_and_modes_blocks_install(self):
        self.inject_after_metadata(lambda: self.source_file.write_text('rewritten fixture'))
        with self.assertRaisesRegex(MigrationError, 'Source files changed during staging'):
            self.finalize()
        self.fixture.assert_destination_original()

    def test_deletion_between_metadata_and_modes_blocks_install(self):
        self.inject_after_metadata(self.source_file.unlink)
        with self.assertRaisesRegex(MigrationError, 'Source files changed during staging'):
            self.finalize()
        self.fixture.assert_destination_original()

    def test_source_skill_rewrite_between_phases_blocks_install(self):
        factory = self.engine.transport.rsync_process
        def transfer(source, destination, **options):
            process = factory(source, destination, **options)
            original = process.start
            def start(*args):
                original(*args)
                if options.get('phase') == 'metadata' and source == str(self.fixture.skill):
                    (self.fixture.skill / 'SKILL.md').write_text('late changed skill')
            process.start = start
            return process
        self.engine.transport.rsync_process = transfer
        with self.assertRaisesRegex(MigrationError, 'Source skills changed during staging'):
            self.finalize()
        self.fixture.assert_destination_original()

    def test_failed_metadata_keeps_staging_incomplete_and_resume_restores_modes(self):
        self.source_file.chmod(0o444)
        factory = self.engine.transport.rsync_process
        def transfer(source, destination, **options):
            process = factory(source, destination, **options)
            if options.get('phase') == 'metadata' and source == str(self.workspace):
                def start(*args):
                    raise RuntimeError('Injected metadata failure')
                process.start = start
            return process
        self.engine.transport.rsync_process = transfer
        with self.assertRaisesRegex(RuntimeError, 'metadata failure'):
            self.engine._copy_all()
        staged = Path(self.fixture.config.target_staging) / 'home-relative/workspaces/work.txt'
        self.assertEqual(staged.stat().st_mode & 0o7777, 0o644)
        self.assertFalse(self.engine.state.read()['staging_complete'])
        self.assertEqual(self.source_file.stat().st_mode & 0o7777, 0o444)
        self.fixture.assert_destination_original()
        self.engine.transport.rsync_process = factory
        self.engine._copy_all()
        self.assertEqual(staged.stat().st_mode & 0o7777, 0o444)
        self.assertEqual(staged.read_bytes(), self.source_file.read_bytes())

    def test_pause_while_helper_is_active_cancels_registered_remote_work(self):
        entered = threading.Event()
        release = threading.Event()
        original = self.engine.transport.run_remote_cancellable
        def remote(script, timeout, cancelled):
            if 'CM_STAGING_UNSAFE' in script:
                entered.set()
                if not release.wait(5):
                    raise RuntimeError('Fixture cancellation did not reach helper')
                if cancelled():
                    raise MigrationError('Fixture helper stopped')
            return original(script, timeout, cancelled)
        self.engine.transport.run_remote_cancellable = remote
        self.engine.transport.cancel_all = release.set
        self.engine.state.update(status='running', phase='staging', staging_complete=True)
        worker = threading.Thread(target=lambda: self.engine._guarded(self.engine._copy_all))
        worker.start()
        try:
            self.assertTrue(entered.wait(5))
            self.engine.pause()
            worker.join(5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(self.engine.state.read()['status'], 'paused')
            self.assertFalse(self.engine.state.read()['staging_complete'])
            self.fixture.assert_destination_original()
        finally:
            release.set()
            worker.join(5)
