import copy
import json
from pathlib import Path
import unittest
import resume_build4_acceptance as resume
from codex_migrate.backup_sockets import CODEX_BACKUP_RUNNER


class ResumeTests(unittest.TestCase):
    def fixture(self):
        return {'config': {'source_home': str(resume.SOURCE), 'target_home': str(resume.TARGET),
            'target': 'target@fixture', 'staging_name': 'Codex-Migrate-Authentic-Staging-20260906',
            'workspace_roots': [str(resume.SOURCE / 'Authentic-Migration-Test')]},
            'status': 'failed', 'phase': 'installing', 'migration_id': 'a' * 32,
            'pending_backup': str(resume.TARGET / ('Codex-Migrate-Backup-20260907T000000Z-' + 'b' * 16))}

    def test_reviewed_failed_state_only(self):
        self.assertTrue(resume.safe_failure(self.fixture(), 'target@fixture'))
        for key, value in [('status', 'running'), ('phase', 'restoring'),
                           ('receipt', {'installed': True}), ('migration_id', 'bad'),
                           ('pending_backup', '/private/other'),
                           ('recovery', {'status': 'checking'})]:
            state = self.fixture()
            state[key] = value
            self.assertFalse(resume.safe_failure(state, 'target@fixture'))

    def test_scope_changes_are_not_authorized(self):
        for key in self.fixture()['config']:
            state = copy.deepcopy(self.fixture())
            state['config'][key] = 'unrelated'
            self.assertFalse(resume.safe_failure(state, 'target@fixture'))

    def test_pinned_verifier_is_exact_build4_program(self):
        data = Path(__file__).with_name('build4-backup-verifier.json').read_bytes()
        self.assertEqual(resume.verifier(data), CODEX_BACKUP_RUNNER)
        with self.assertRaises(RuntimeError):
            resume.verifier(data + b' ')
        self.assertEqual(json.loads(data)['source'], '8d14dbf1877d1fc71a509d6eab86b18ec4014b52')
