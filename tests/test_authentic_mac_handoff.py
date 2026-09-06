"""Deterministic harness checks; none contacts a Mac or model provider."""
import contextlib
import json
import os
from pathlib import Path
import queue
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import authentic_mac_handoff as handoff


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.home.chmod(0o700)
        (self.home / '.codex').mkdir(mode=0o700)
        (self.home / '.codex/sentinel').write_text('old disposable data')
        (self.home / '.codex-migrate-acceptance-fixture.json').write_text('{"synthetic":true}')

    def prepare(self):
        with patch.object(handoff, 'codex_closed', return_value=True):
            handoff.prepare(self.home, 'source')

    def test_personal_and_root_accounts_rejected(self):
        user = Mock(pw_name='jsegeren', pw_dir='/Users/jsegeren')
        with patch.object(handoff.pwd, 'getpwuid', return_value=user):
            with self.assertRaises(handoff.SafeError):
                handoff.account('source')
        user.pw_name, user.pw_dir = 'codexmigratesource', str(handoff.SOURCE)
        with patch.object(handoff.pwd, 'getpwuid', return_value=user), \
                patch.object(handoff.os, 'getuid', return_value=0), \
                patch.object(handoff.os, 'geteuid', return_value=0):
            with self.assertRaises(handoff.SafeError):
                handoff.account('source')

    def test_preparation_preserves_old_data_and_is_idempotent(self):
        self.prepare()
        previous = self.home / handoff.STATE_NAME / 'previous-codex/sentinel'
        self.assertFalse(previous.exists())
        self.assertEqual((self.home / '.codex/sentinel').read_text(), 'old disposable data')
        (self.home / '.codex/new-conversation').write_text('new genuine test data')
        self.prepare()
        self.assertEqual((self.home / '.codex/new-conversation').read_text(), 'new genuine test data')
        self.assertFalse(previous.exists())

    def test_partial_rename_resumes_without_moving_new_data(self):
        root = handoff.root_for(self.home)
        (self.home / '.codex').rename(root / 'previous-codex')
        (self.home / '.codex').mkdir(mode=0o700)
        (self.home / '.codex/new').write_text('keep')
        self.prepare()
        self.assertEqual((self.home / '.codex/new').read_text(), 'keep')

    def test_credential_files_are_never_opened_during_preparation(self):
        auth = self.home / '.codex/auth.json'
        auth.write_bytes(b'dummy fixture credential')
        original_read_text, original_read_bytes = Path.read_text, Path.read_bytes
        def text(path, *args, **kwargs):
            self.assertNotIn(path.name, ('auth.json', 'installation_id'))
            return original_read_text(path, *args, **kwargs)
        def binary(path, *args, **kwargs):
            self.assertNotIn(path.name, ('auth.json', 'installation_id'))
            return original_read_bytes(path, *args, **kwargs)
        with patch.object(Path, 'read_text', text), patch.object(Path, 'read_bytes', binary):
            self.prepare()
        self.assertTrue(auth.is_file())
        self.assertFalse((self.home / handoff.STATE_NAME / 'previous-codex').exists())

    def test_existing_login_and_codex_created_permissions_are_retained(self):
        current = self.home / '.codex'
        current.chmod(0o755)
        for name in ('auth.json', 'installation_id'):
            (current / name).write_text('dummy fixture only')
        before = {path.name: path.stat().st_ino for path in current.iterdir()}
        self.prepare()
        self.assertEqual({path.name: path.stat().st_ino for path in current.iterdir()}, before)
        self.assertEqual(current.stat().st_mode & 0o777, 0o755)

    def test_writable_codex_root_requires_review_without_moving_files(self):
        (self.home / '.codex').chmod(0o777)
        with self.assertRaises(handoff.SafeError):
            self.prepare()
        self.assertTrue((self.home / '.codex/sentinel').is_file())
        self.assertFalse((self.home / handoff.STATE_NAME / 'preparation.json').exists())

    def test_live_codex_pending_recovery_and_missing_marker_block_preparation(self):
        with patch.object(handoff, 'codex_closed', return_value=False):
            with self.assertRaises(handoff.SafeError):
                handoff.prepare(self.home, 'source')
        transaction = self.home / '.codex-migrate-transaction.json'
        transaction.write_text('{}')
        with self.assertRaises(handoff.SafeError):
            self.prepare()
        transaction.unlink()
        (self.home / '.codex-migrate-acceptance-fixture.json').write_text('{"synthetic":false}')
        with self.assertRaises(handoff.SafeError):
            self.prepare()
        self.assertEqual((self.home / '.codex/sentinel').read_text(), 'old disposable data')

    def test_symlink_and_world_writable_roots_rejected(self):
        root = self.home / handoff.STATE_NAME
        root.symlink_to(self.home, target_is_directory=True)
        with self.assertRaises(handoff.SafeError):
            self.prepare()
        root.unlink()
        root.mkdir(mode=0o777)
        root.chmod(0o777)
        with self.assertRaises(handoff.SafeError):
            self.prepare()

    def test_atomic_report_failure_retains_previous_receipt(self):
        target = self.home / 'report.json'
        handoff.save(target, {'phase': 'old'})
        with patch.object(handoff.os, 'replace', side_effect=OSError):
            with self.assertRaises(OSError):
                handoff.save(target, {'phase': 'new'})
        self.assertEqual(json.loads(target.read_text()), {'phase': 'old'})
        self.assertFalse(list(self.home.glob('.receipt-*')))

    def protocol(self):
        app = object.__new__(handoff.AppServer)
        app.events, app.completed, app.serial = queue.Queue(), [], 0
        app.send = Mock()
        return app

    def test_early_turn_completion_is_not_lost(self):
        app = self.protocol()
        app.events.put({'method': 'turn/completed', 'params': {
            'threadId': 'fixture', 'turn': {'id': 'turn1', 'status': 'completed'}}})
        app.events.put({'id': 1, 'result': {'turn': {'id': 'turn1'}}})
        app.turn('fixture', 'fixture prompt')
        self.assertEqual(app.completed, [])

    def test_server_tool_requests_rejected_not_approved(self):
        app = self.protocol()
        app.events.put({'id': 9, 'method': 'item/commandExecution/requestApproval', 'params': {}})
        with self.assertRaises(handoff.SafeError):
            app.receive(time.monotonic() + 1)
        self.assertIn('error', app.send.call_args.args[0])

    def test_api_key_or_missing_account_not_accepted_as_chatgpt_login(self):
        app = self.protocol()
        for value in (None, {'type': 'apiKey'}, {'type': 'amazonBedrock'}):
            app.call = Mock(return_value={'account': value})
            self.assertFalse(app.signed_in())
        app.call = Mock(return_value={'account': {'type': 'chatgpt', 'email': 'fixture@example.invalid'}})
        self.assertTrue(app.signed_in())

    def test_incomplete_source_thread_is_not_recreated(self):
        root = handoff.root_for(self.home)
        handoff.save(root / 'threads.json', [{'id': 'fixture', 'complete': False}])
        workspace = self.home / handoff.WORKSPACE_NAME
        workspace.mkdir(parents=True, mode=0o700)
        fake = Mock()
        with patch.object(handoff, 'server', return_value=contextlib.nullcontext(fake)):
            with self.assertRaises(handoff.SafeError):
                handoff.fixture_threads(self.home)
        fake.call.assert_not_called()

    def test_subprocess_failure_does_not_expose_raw_output(self):
        with patch.object(handoff.subprocess, 'run', return_value=Mock(returncode=1,
                    stdout=b'private fixture output', stderr=b'private fixture error')):
            with self.assertRaises(handoff.SafeError) as error:
                handoff.run(['fixture'])
        self.assertNotIn('private', str(error.exception))

    def test_restart_does_not_open_codex_during_active_installation(self):
        root = handoff.root_for(self.home)
        (root / 'migration').mkdir(mode=0o700)
        (root / 'migration/control-token').write_text('disposable-test-token')
        (root / 'migration/control-token').chmod(0o600)
        handoff.save(root / 'runtime.json', {'pid': 321})
        with patch.object(handoff, 'SOURCE', self.home), \
                patch.object(handoff, 'processes', return_value=[(321, str(handoff.ENGINE))]), \
                patch.object(handoff, 'listener', return_value=12345), \
                patch.object(handoff, 'api', return_value={'status': 'running', 'phase': 'installing'}), \
                patch.object(handoff.os, 'kill') as kill:
            with self.assertRaises(handoff.SafeError):
                handoff.stop_old_helper()
            kill.assert_not_called()


if __name__ == '__main__':
    unittest.main()
