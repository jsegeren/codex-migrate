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
    def test_fast_background_exit_is_not_reported_as_start_failure_or_success(self):
        for code in (0, 1, -15):
            with self.subTest(code=code):
                worker = Mock()
                worker.poll.return_value = code
                with patch('sys.argv', ['harness', '--background']), \
                        patch.object(handoff, 'account'), \
                        patch.object(handoff.subprocess, 'Popen', return_value=worker), \
                        patch.object(handoff.time, 'sleep'), patch('builtins.print') as output:
                    handoff.main()
                messages = ' '.join(call.args[0] for call in output.call_args_list)
                self.assertIn('already stopped', messages)
                self.assertIn('Do not repeat setup', messages)
                self.assertNotIn('could not start', messages)
                self.assertNotIn('continues automatically', messages)

    def test_live_background_worker_is_reported_as_running(self):
        worker = Mock()
        worker.poll.return_value = None
        with patch('sys.argv', ['harness', '--background']), \
                patch.object(handoff, 'account'), \
                patch.object(handoff.subprocess, 'Popen', return_value=worker), \
                patch.object(handoff.time, 'sleep'), patch('builtins.print') as output:
            handoff.main()
        messages = ' '.join(call.args[0] for call in output.call_args_list)
        self.assertIn('running in the background', messages)
        self.assertNotIn('already stopped', messages)

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

    def test_failed_turn_exposes_only_allowlisted_category(self):
        app = self.protocol()
        app.events.put({'id': 1, 'result': {'turn': {'id': 'turn1'}}})
        app.events.put({'method': 'turn/completed', 'params': {
            'threadId': 'fixture', 'turn': {'id': 'turn1', 'status': 'failed',
            'error': {'codexErrorInfo': 'usageLimitExceeded',
                      'message': 'private provider data', 'additionalDetails': 'private detail'}}}})
        with self.assertRaisesRegex(handoff.SafeError, '^Codex turn failed: usageLimitExceeded$'):
            app.turn('fixture', 'fixture prompt')

    def test_all_known_turn_categories_are_fixed_diagnostics(self):
        for code in handoff.TURN_ERROR_CODES:
            with self.subTest(code=code):
                self.assertEqual(handoff.turn_failure({'error': {'codexErrorInfo': code}}),
                                 'Codex turn failed: ' + code)

    def test_turn_http_status_is_bounded_and_never_raw_text(self):
        for name in handoff.TURN_HTTP_ERRORS:
            for status in (401, 429, 503, None, True, 'private', -1, 600, 429.0):
                with self.subTest(name=name, status=status):
                    result = handoff.turn_failure({'error': {'message': 'private',
                        'codexErrorInfo': {name: {'httpStatusCode': status, 'private': 'secret'}}}})
                    suffix = ' (HTTP ' + str(status) + ')' if type(status) is int and 100 <= status <= 599 else ''
                    self.assertEqual(result, 'Codex turn failed: ' + name + suffix)

    def test_unknown_or_malformed_turn_errors_never_leak(self):
        for code in ('private', {'private': {'httpStatusCode': 401}},
                     {'httpConnectionFailed': 'private'},
                     {'httpConnectionFailed': {}, 'private': 'secret'}, ['private'], None):
            with self.subTest(kind=type(code).__name__):
                self.assertEqual(handoff.turn_failure({'error': {'codexErrorInfo': code,
                    'message': 'secret', 'additionalDetails': 'secret'}}),
                    'Codex turn failed; error category unavailable')
        for turn in (None, [], {}, {'error': 'private'}):
            self.assertEqual(handoff.turn_failure(turn), 'Codex turn failed; error category unavailable')

    def test_interrupted_turn_is_not_described_as_success(self):
        self.assertEqual(handoff.turn_failure({'status': 'interrupted'}),
                         'Codex test turn was interrupted')

    def partial_fixture(self):
        root = handoff.root_for(self.home)
        record = {'id': 'fixture', 'kind': 'project',
                  'marker': 'migration-fixture-' + 'a' * 32, 'complete': False}
        handoff.save(root / 'threads.json', [record])
        (self.home / handoff.WORKSPACE_NAME).mkdir(mode=0o700)
        return root / 'threads.json'

    def test_partial_thread_diagnosis_does_not_retry_or_change_receipt(self):
        manifest = self.partial_fixture()
        original = manifest.read_bytes()
        fake = Mock()
        fake.call.return_value = {'thread': {'id': 'fixture', 'turns': [
            {'status': 'failed', 'error': {'codexErrorInfo': 'badRequest', 'message': 'secret'}}]}}
        with patch.object(handoff, 'server', return_value=contextlib.nullcontext(fake)):
            with self.assertRaisesRegex(handoff.SafeError, '^Codex turn failed: badRequest$'):
                handoff.fixture_threads(self.home)
        fake.call.assert_called_once_with('thread/read', {'threadId': 'fixture', 'includeTurns': True})
        fake.turn.assert_not_called()
        self.assertEqual(manifest.read_bytes(), original)

    def test_partial_thread_completed_or_active_still_requires_review(self):
        self.partial_fixture()
        for status in ('completed', 'inProgress', 'private'):
            fake = Mock()
            fake.call.return_value = {'thread': {'id': 'fixture', 'turns': [{'status': status}]}}
            with patch.object(handoff, 'server', return_value=contextlib.nullcontext(fake)):
                with self.assertRaisesRegex(handoff.SafeError, 'no automatic model retry'):
                    handoff.fixture_threads(self.home)
            fake.turn.assert_not_called()

    def test_partial_thread_response_identity_must_match(self):
        self.partial_fixture()
        fake = Mock()
        fake.call.return_value = {'thread': {'id': 'different-thread', 'turns': []}}
        with patch.object(handoff, 'server', return_value=contextlib.nullcontext(fake)):
            with self.assertRaisesRegex(handoff.SafeError, 'response needs review'):
                handoff.fixture_threads(self.home)
        fake.turn.assert_not_called()

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

    def test_remote_app_close_reason_is_visible_without_raw_output(self):
        message = 'Quit Codex in the disposable target account first'
        result = Mock(returncode=1, stdout=json.dumps({'error': message}).encode(),
                      stderr=b'private remote details')
        with patch.object(handoff.subprocess, 'run', return_value=result):
            with self.assertRaises(handoff.SafeError) as error:
                handoff.remote([], 'fixture.invalid', 'prepare')
        self.assertEqual(str(error.exception), message)

    def test_unexpected_remote_errors_and_ssh_details_are_not_disclosed(self):
        for status, output in ((1, b'{"error":"private remote details"}'),
                               (1, b'private malformed output'),
                               (255, b'private SSH details')):
            with self.subTest(status=status, output_kind=type(output).__name__):
                with patch.object(handoff.subprocess, 'run', return_value=Mock(
                        returncode=status, stdout=output, stderr=b'private stderr')):
                    with self.assertRaises(handoff.SafeError) as error:
                        handoff.remote([], 'fixture.invalid', 'prepare')
                self.assertNotIn('private remote', str(error.exception))
                self.assertNotIn('private malformed', str(error.exception))
                self.assertNotIn('private SSH', str(error.exception))

    def test_remote_success_requires_zero_exit_and_object(self):
        for status, output in ((1, b'{"ready":true}'), (0, b'[]')):
            with patch.object(handoff.subprocess, 'run', return_value=Mock(
                    returncode=status, stdout=output, stderr=b'')):
                with self.assertRaises(handoff.SafeError):
                    handoff.remote([], 'fixture.invalid', 'ready')

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
