import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import final_recovery_acceptance as recovery
from codex_migrate.destination_lock import LOCK_RUNNER
from codex_migrate.transaction import TRANSACTION_RUNNER


class FinalRecoveryTests(unittest.TestCase):
    def test_scope_is_only_fresh_workspace(self):
        home = Path('/Users/codexmigratetarget')
        plan = recovery.plan_for(home)
        self.assertEqual(plan['scope'], [{'original': str(home / recovery.NAME / 'workspace'),
            'backup': str(home / (recovery.NAME + '-Backup') / 'workspace')}])
        self.assertNotIn('.codex', json.dumps(plan))

    def test_default_invocation_cannot_mutate(self):
        result = subprocess.run([sys.executable, '-I', recovery.__file__], capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b'')

    @unittest.skipUnless(sys.platform == 'darwin' and os.getuid() != 0, 'real APFS transaction fixture')
    def test_real_fixture_kill_is_observed_and_cannot_be_repeated(self):
        # Local harness mechanics only. The deployed harness uses real account checks.
        with tempfile.TemporaryDirectory(prefix='codex-recovery-harness-') as value:
            home = Path(value).resolve()
            own = Path(recovery.__file__).read_text().split("\nif __name__ == '__main__':")[0]
            bootstrap = ('import types\nfrom pathlib import Path\nf=types.SimpleNamespace('
                         'TARGET=Path(' + repr(str(home)) + '),account=lambda _:None,closed=lambda:None)\n'
                         'TRANSACTION_RUNNER=' + repr(TRANSACTION_RUNNER) + '\nLOCK_RUNNER=' + repr(LOCK_RUNNER) + '\n')
            code = bootstrap + 'BOOTSTRAP=' + repr(bootstrap) + '\nSELF=' + repr(own) + '\n' + own
            code += '\nprint(json.dumps(remote_action("interrupt")))\n'
            result = subprocess.run(['/usr/bin/python3', '-I', '-'], input=code, text=True,
                                    capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, 'Fixture mechanics failed; preserve scoped evidence')
            self.assertTrue(json.loads(result.stdout)['durable_pending_transaction'])
            original_record = (home / '.codex-migrate-transaction.json').read_bytes()
            second = subprocess.run(['/usr/bin/python3', '-I', '-'], input=code, text=True,
                                    capture_output=True, timeout=30)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual((home / '.codex-migrate-transaction.json').read_bytes(), original_record)
            self.assertEqual((home / recovery.NAME / 'workspace/newer.txt').read_text(), recovery.NEW)


if __name__ == '__main__':
    unittest.main()
