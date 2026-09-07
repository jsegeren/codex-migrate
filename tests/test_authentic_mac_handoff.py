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
    def test_open_dashboard_only_reads_known_helper_and_opens_token_fragment(self):
        root = handoff.root_for(self.home)
        state = root / handoff.MIGRATION_STATE
        state.mkdir(mode=0o700)
        token = state / 'control-token'
        token.write_text('a' * 64)
        token.chmod(0o600)
        handoff.save(root / handoff.RUNTIME_RECORD, {'pid': 123})
        with patch.object(handoff, 'account', return_value=self.home), \
                patch.object(handoff, 'processes', return_value=[(123, str(handoff.ENGINE))]), \
                patch.object(handoff, 'listener', return_value=54321), \
                patch.object(handoff, 'api', return_value={'status': 'failed'}) as api, \
                patch.object(handoff.subprocess, 'run') as launch:
            handoff.open_test_dashboard()
            api.assert_called_once_with(54321, 'a' * 64, '/api/status')
            self.assertEqual(launch.call_args.args[0],
                             ['/usr/bin/open', 'http://127.0.0.1:54321/#token=' + 'a' * 64])
            token.write_text('invalid token')
            api.reset_mock()
            launch.reset_mock()
            with self.assertRaisesRegex(handoff.SafeError, 'Invalid test control token'):
                handoff.open_test_dashboard()
            api.assert_not_called()
            launch.assert_not_called()

    def test_open_dashboard_never_restarts_missing_or_different_helper(self):
        root = handoff.root_for(self.home)
        (root / handoff.MIGRATION_STATE).mkdir(mode=0o700)
        handoff.save(root / handoff.RUNTIME_RECORD, {'pid': 123})
        for running in ([], [(123, '/other/app')], [(124, str(handoff.ENGINE))]):
            with self.subTest(running=running), \
                    patch.object(handoff, 'account', return_value=self.home), \
                    patch.object(handoff, 'processes', return_value=running), \
                    patch.object(handoff, 'api') as api, \
                    patch.object(handoff.subprocess, 'run') as launch:
                with self.assertRaisesRegex(handoff.SafeError, 'no restart performed'):
                    handoff.open_test_dashboard()
                api.assert_not_called()
                launch.assert_not_called()

    def test_shared_package_rejects_private_wrapper_and_nested_files_before_signing(self):
        shared = self.home / 'shared'
        app = shared / 'isolated-candidate/Codex Migrate.app'
        engine = app / 'Contents/engine'
        engine.parent.mkdir(parents=True)
        engine.write_text('disposable fixture')
        for directory in (shared, app.parent, app, engine.parent):
            directory.chmod(0o755)
        engine.chmod(0o755)
        with patch.object(handoff, 'SHARED', shared), patch.object(handoff, 'ENGINE', engine), \
                patch.object(handoff, 'run') as run:
            handoff.verify_shared_candidate()
            run.assert_called_once_with(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)])
            for path, bad_mode, good_mode in ((app.parent, 0o700, 0o755),
                                               (engine.parent, 0o700, 0o755),
                                               (engine, 0o700, 0o755),
                                               (engine, 0o644, 0o755)):
                with self.subTest(path=path, mode=bad_mode):
                    run.reset_mock()
                    path.chmod(bad_mode)
                    with self.assertRaisesRegex(handoff.SafeError, 'permissions need repair'):
                        handoff.verify_shared_candidate()
                    run.assert_not_called()
                    self.assertEqual(path.stat().st_mode & 0o777, bad_mode)
                    path.chmod(good_mode)
            engine.unlink()
            run.reset_mock()
            with self.assertRaisesRegex(handoff.SafeError, 'permissions need repair'):
                handoff.verify_shared_candidate()
            run.assert_not_called()

    def test_staging_diagnostic_missing_matching_and_foreign_preserve_files(self):
        expected = 'a' * 32
        self.assertEqual(handoff.staging_diagnostic(self.home, expected)['staging'], 'missing')
        staging = self.home / 'Codex-Migrate-Staging'
        staging.mkdir(mode=0o700)
        marker = staging / '.codex-migrate-owner'
        self.assertEqual(handoff.staging_diagnostic(self.home, expected)['staging'], 'missing_owner_marker')
        for owner, outcome in ((expected, 'matching_owner'), ('b' * 32, 'different_owner'),
                               ('invalid', 'invalid_owner_marker')):
            marker.write_text(owner + '\n')
            marker.chmod(0o600)
            self.assertEqual(handoff.staging_diagnostic(self.home, expected)['staging'], outcome)
            self.assertEqual(marker.read_text(), owner + '\n')

    def test_staging_diagnostic_rejects_links_and_never_reads_target(self):
        staging = self.home / 'Codex-Migrate-Staging'
        staging.mkdir(mode=0o700)
        (staging / '.codex-migrate-owner').symlink_to(self.home / '.codex/auth.json')
        self.assertEqual(handoff.staging_diagnostic(self.home, 'a' * 32)['staging'], 'unsafe_or_unreadable')
        (staging / '.codex-migrate-owner').unlink()
        staging.rmdir()
        staging.symlink_to(self.home / '.codex', target_is_directory=True)
        self.assertEqual(handoff.staging_diagnostic(self.home, 'a' * 32)['staging'], 'unsafe_or_unreadable')

    def test_staging_diagnostic_pending_record_is_presence_only(self):
        (self.home / '.codex-migrate-transaction.json').symlink_to(self.home / 'absent')
        with patch.object(Path, 'read_text', side_effect=AssertionError('must not read')):
            self.assertTrue(handoff.staging_diagnostic(self.home, 'a' * 32)['pending_recovery'])
        for value in (None, {}, 'secret', '../bad', 'a' * 33):
            with self.assertRaises(handoff.SafeError):
                handoff.staging_diagnostic(self.home, value)

    def test_diagnose_exports_only_allowlisted_fields_without_actions(self):
        root = handoff.root_for(self.home)
        migration = root / 'migration'
        migration.mkdir(mode=0o700)
        handoff.save(migration / 'state.json', {'migration_id': 'a' * 32,
                     'status': 'failed', 'phase': 'preflight_complete',
                     'error': 'PRIVATE arbitrary details', 'control_token': 'PRIVATE'})
        public = self.home / 'public'
        public.mkdir(mode=0o755)
        reply = {'staging': 'different_owner', 'pending_recovery': False, 'extra': 'PRIVATE'}
        with patch.object(handoff, 'account', return_value=self.home), \
                patch.object(handoff, 'connection', return_value=({'target': 'fixture'}, [], None, None)), \
                patch.object(handoff, 'remote', return_value=reply) as remote, \
                patch.object(handoff, 'PUBLIC', public), patch.object(handoff, 'api') as api, \
                patch.object(handoff, 'driver') as driver, patch('builtins.print'):
            handoff.diagnose()
        remote.assert_called_once_with([], 'fixture', 'diagnose', 'a' * 32)
        api.assert_not_called()
        driver.assert_not_called()
        encoded = (public / 'staging-diagnostic.json').read_text()
        self.assertNotIn('PRIVATE', encoded)
        self.assertNotIn('a' * 32, encoded)
        self.assertTrue(json.loads(encoded)['failed_before_copy'])

    def test_diagnose_route_never_starts_background_driver(self):
        with patch('sys.argv', ['harness', '--diagnose']), \
                patch.object(handoff, 'diagnose') as diagnostic, \
                patch.object(handoff.subprocess, 'Popen') as spawn, \
                patch.object(handoff, 'driver') as driver:
            handoff.main()
        diagnostic.assert_called_once_with()
        spawn.assert_not_called()
        driver.assert_not_called()

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

    def catalog(self):
        return {'data': [{'model': 'gpt-test-supported', 'isDefault': True, 'hidden': False,
                          'defaultReasoningEffort': 'low',
                          'supportedReasoningEfforts': [{'reasoningEffort': 'low'}]}], 'nextCursor': None}

    def test_model_comes_from_catalog_and_pin_is_preserved(self):
        app = Mock()
        app.call.return_value = self.catalog()
        chosen = handoff.model_selection(app)
        self.assertEqual(chosen, {'model': 'gpt-test-supported', 'effort': 'low'})
        app.call.return_value['data'][0]['isDefault'] = False
        self.assertEqual(handoff.model_selection(app, chosen), chosen)

    def test_model_catalog_pagination(self):
        app = Mock()
        app.call.side_effect = [{'data': [], 'nextCursor': 'page2'}, self.catalog()]
        self.assertEqual(handoff.model_selection(app)['model'], 'gpt-test-supported')
        self.assertEqual(app.call.call_args.args[1]['cursor'], 'page2')

    def test_bad_catalogs_do_not_silently_select_another_model(self):
        for variation in ('missing', 'duplicate', 'hidden', 'legacy', 'effort', 'unknown-pin', 'endless'):
            app = Mock()
            catalog = self.catalog()
            pinned = None
            if variation == 'missing': catalog['data'] = []
            if variation == 'duplicate': catalog['data'] *= 2
            if variation == 'hidden': catalog['data'][0]['hidden'] = True
            if variation == 'legacy': catalog['data'][0]['model'] = 'gpt-5'
            if variation == 'effort': catalog['data'][0]['defaultReasoningEffort'] = 'unsupported'
            if variation == 'unknown-pin': pinned = {'model': 'gpt-absent', 'effort': 'low'}
            if variation == 'endless': catalog['nextCursor'] = 'again'
            app.call.return_value = catalog
            with self.subTest(variation=variation), self.assertRaises(handoff.SafeError):
                handoff.model_selection(app, pinned)
            self.assertLessEqual(app.call.call_count, 5)

    def legacy_turn(self, marker):
        message = "The 'gpt-5' model is not supported when using Codex with a ChatGPT account."
        return {'status': 'failed', 'error': {'codexErrorInfo': 'other', 'message': json.dumps({
            'type': 'error', 'status': 400, 'error': {'type': 'invalid_request_error', 'message': message}})},
            'items': [{'type': 'userMessage', 'content': [{'type': 'text', 'text_elements': [],
                'text': 'Remember this test marker: ' + marker + '. Reply only with that marker.'}]}]}

    def test_only_exact_rejected_fixture_is_eligible_for_model_repair(self):
        marker = 'migration-fixture-' + 'a' * 32
        self.assertTrue(handoff.unsupported_legacy_fixture(self.legacy_turn(marker), marker))
        for variation in ('completed', 'quota', 'message', 'assistant', 'different-marker'):
            turn = self.legacy_turn(marker)
            if variation == 'completed': turn['status'] = 'completed'
            if variation == 'quota': turn['error']['codexErrorInfo'] = 'usageLimitExceeded'
            if variation == 'message': turn['error']['message'] = 'private unknown error'
            if variation == 'assistant': turn['items'].append({'type': 'agentMessage', 'text': 'already answered'})
            with self.subTest(variation=variation):
                self.assertFalse(handoff.unsupported_legacy_fixture(turn,
                    'migration-fixture-' + 'b' * 32 if variation == 'different-marker' else marker))

    def test_repair_resumes_same_thread_and_pins_new_fixture_models(self):
        manifest = self.partial_fixture()
        app = Mock()
        starts = []
        def call(method, params):
            if method == 'thread/read':
                return {'thread': {'id': 'fixture', 'turns': [self.legacy_turn('migration-fixture-' + 'a' * 32)]}}
            if method == 'model/list': return self.catalog()
            if method == 'thread/start':
                starts.append(params)
                return {'thread': {'id': 'new-' + str(len(starts))}, 'model': 'gpt-test-supported'}
            if method == 'thread/resume': return {'model': 'gpt-test-supported'}
            return {}
        app.call.side_effect = call
        with patch.object(handoff, 'server', return_value=contextlib.nullcontext(app)):
            records = handoff.fixture_threads(self.home)
        self.assertEqual(records[0]['id'], 'fixture')
        self.assertEqual(len(starts), 2)
        self.assertTrue(all(item['complete'] for item in records))
        self.assertTrue(records[0]['model_repair_attempted'])
        self.assertEqual(app.turn.call_count, 3)
        self.assertTrue(all(params['model'] == 'gpt-test-supported' for params in starts))
        self.assertTrue(all(call.args[2] == records[0]['model'] for call in app.turn.call_args_list))
        self.assertEqual(json.loads(manifest.read_text()), records)

    def test_failed_model_repair_is_not_retried_on_next_launch(self):
        manifest = self.partial_fixture()
        app = Mock()
        def call(method, params):
            if method == 'thread/read':
                return {'thread': {'id': 'fixture', 'turns': [self.legacy_turn('migration-fixture-' + 'a' * 32)]}}
            if method == 'model/list': return self.catalog()
            if method == 'thread/resume': return {'model': 'gpt-test-supported'}
            return {}
        app.call.side_effect = call
        app.turn.side_effect = handoff.SafeError('fixture forced failure')
        for _ in range(2):
            with patch.object(handoff, 'server', return_value=contextlib.nullcontext(app)):
                with self.assertRaises(handoff.SafeError):
                    handoff.fixture_threads(self.home)
        self.assertEqual(app.turn.call_count, 1)
        record = json.loads(manifest.read_text())[0]
        self.assertTrue(record['model_repair_attempted'])
        self.assertFalse(record['complete'])

    def test_turn_explicitly_sends_pinned_model_and_effort(self):
        app = self.protocol()
        app.events.put({'id': 1, 'result': {'turn': {'id': 'turn1'}}})
        app.events.put({'method': 'turn/completed', 'params': {
            'threadId': 'fixture', 'turn': {'id': 'turn1', 'status': 'completed'}}})
        app.turn('fixture', 'fixture prompt', {'model': 'gpt-test-supported', 'effort': 'low'})
        params = app.send.call_args.args[0]['params']
        self.assertEqual(params['model'], 'gpt-test-supported')
        self.assertEqual(params['effort'], 'low')

    def test_model_repair_stops_if_server_ignores_pin(self):
        self.partial_fixture()
        app = Mock()
        def call(method, params):
            if method == 'thread/read':
                return {'thread': {'id': 'fixture', 'turns': [self.legacy_turn('migration-fixture-' + 'a' * 32)]}}
            if method == 'model/list': return self.catalog()
            if method == 'thread/resume': return {'model': 'gpt-5'}
            return {}
        app.call.side_effect = call
        with patch.object(handoff, 'server', return_value=contextlib.nullcontext(app)):
            with self.assertRaisesRegex(handoff.SafeError, 'did not honor the test model pin'):
                handoff.fixture_threads(self.home)
        app.turn.assert_not_called()

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
        (root / handoff.MIGRATION_STATE).mkdir(mode=0o700)
        token = root / handoff.MIGRATION_STATE / 'control-token'
        token.write_text('disposable-test-token')
        token.chmod(0o600)
        handoff.save(root / handoff.RUNTIME_RECORD, {'pid': 321})
        with patch.object(handoff, 'SOURCE', self.home), \
                patch.object(handoff, 'processes', return_value=[(321, str(handoff.ENGINE))]), \
                patch.object(handoff, 'listener', return_value=12345), \
                patch.object(handoff, 'api', return_value={'status': 'running', 'phase': 'installing'}), \
                patch.object(handoff.os, 'kill') as kill:
            with self.assertRaises(handoff.SafeError):
                handoff.stop_old_helper()
            kill.assert_not_called()

    def legacy_helper(self):
        root = handoff.root_for(self.home)
        state = root / 'migration'
        state.mkdir(mode=0o700)
        token = state / 'control-token'
        token.write_text('disposable-test-token')
        token.chmod(0o600)
        handoff.save(root / 'runtime.json', {'pid': 321})
        return {'status': 'failed', 'phase': 'preflight_complete',
                'staging_complete': False, 'migration_id': 'a' * 32,
                'config': {'source_home': str(self.home), 'target_home': str(handoff.TARGET),
                           'target': 'fixture', 'staging_name': 'Codex-Migrate-Staging'}}

    def retirement_context(self, statuses, process_result=None, diagnostic=None, stack=None):
        if stack is None:
            stack = contextlib.ExitStack()
            self.addCleanup(stack.close)
        stack.enter_context(patch.object(handoff, 'SOURCE', self.home))
        process = [(321, str(handoff.LEGACY_ENGINE))]
        stack.enter_context(patch.object(handoff, 'processes',
                                        side_effect=process_result or [process, process, []]))
        stack.enter_context(patch.object(handoff, 'listener', return_value=12345))
        stack.enter_context(patch.object(handoff, 'api', side_effect=statuses))
        remote = stack.enter_context(patch.object(handoff, 'remote', return_value=(
            diagnostic if diagnostic is not None else
            {'staging': 'different_owner', 'pending_recovery': False})))
        kill = stack.enter_context(patch.object(handoff.os, 'kill'))
        stack.enter_context(patch.object(handoff.time, 'sleep'))
        return remote, kill

    def test_retire_only_diagnosed_legacy_helper_preserves_state(self):
        status = self.legacy_helper()
        root = handoff.root_for(self.home)
        before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
        remote, kill = self.retirement_context([status, status])
        handoff.retire_failed_staging_helper([], 'fixture')
        remote.assert_called_once_with([], 'fixture', 'diagnose', 'a' * 32)
        kill.assert_called_once_with(321, handoff.signal.SIGTERM)
        after = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        self.assertFalse((root / handoff.MIGRATION_STATE).exists())

    def test_retire_rejects_active_or_installed_states(self):
        status = self.legacy_helper()
        changes = [{'status': 'running'}, {'phase': 'installing'}, {'receipt': {'verified': True}},
                   {'pending_backup': '/fixture/backup'}, {'staging_complete': True},
                   {'recovery': {'status': 'checking'}}, {'recovery': None},
                   {'config': {}}, {'config': {**status['config'], 'target': 'another'}}]
        for changed in changes:
            with self.subTest(changed=changed), self.retirement_context_scope(
                    [{**status, **changed}]) as (remote, kill):
                with self.assertRaises(handoff.SafeError):
                    handoff.retire_failed_staging_helper([], 'fixture')
                remote.assert_not_called()
                kill.assert_not_called()

    @contextlib.contextmanager
    def retirement_context_scope(self, statuses, **kwargs):
        with contextlib.ExitStack() as stack:
            yield self.retirement_context(statuses, stack=stack, **kwargs)

    def test_retire_rejects_changed_staging_or_pending_recovery(self):
        status = self.legacy_helper()
        for diagnostic in ({'staging': 'matching_owner', 'pending_recovery': False},
                           {'staging': 'different_owner', 'pending_recovery': True}):
            with self.retirement_context_scope([status], diagnostic=diagnostic) as (_, kill):
                with self.assertRaises(handoff.SafeError):
                    handoff.retire_failed_staging_helper([], 'fixture')
                kill.assert_not_called()

    def test_retire_rechecks_state_before_signal(self):
        status = self.legacy_helper()
        _, kill = self.retirement_context([status, {**status, 'status': 'running'}])
        with self.assertRaises(handoff.SafeError):
            handoff.retire_failed_staging_helper([], 'fixture')
        kill.assert_not_called()

    def test_retire_unknown_pid_and_multiple_helpers_are_not_signalled(self):
        self.legacy_helper()
        for processes in ([(999, str(handoff.LEGACY_ENGINE))],
                          [(321, str(handoff.LEGACY_ENGINE)), (999, str(handoff.LEGACY_ENGINE))]):
            with self.retirement_context_scope([], process_result=[processes]) as (remote, kill):
                with self.assertRaises(handoff.SafeError):
                    handoff.retire_failed_staging_helper([], 'fixture')
                remote.assert_not_called()
                kill.assert_not_called()

    def test_retire_absent_helper_does_nothing(self):
        remote, kill = self.retirement_context([], process_result=[[]])
        handoff.retire_failed_staging_helper([], 'fixture')
        remote.assert_not_called()
        kill.assert_not_called()

    def test_retire_timeout_never_escalates_to_kill(self):
        status = self.legacy_helper()
        process = [(321, str(handoff.LEGACY_ENGINE))]
        _, kill = self.retirement_context([status, status], process_result=[process] * 102)
        with self.assertRaises(handoff.SafeError):
            handoff.retire_failed_staging_helper([], 'fixture')
        kill.assert_called_once_with(321, handoff.signal.SIGTERM)


if __name__ == '__main__':
    unittest.main()
