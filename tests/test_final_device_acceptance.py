import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import final_device_acceptance as final


class FinalDeviceTests(unittest.TestCase):
    def test_current_personal_account_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'wrong_account'):
            final.account(final.SOURCE)

    def test_nonempty_fixture_is_never_adopted(self):
        with tempfile.TemporaryDirectory() as value:
            home = Path(value)
            root = final.new_root(home)
            (root / 'keep').write_text('unchanged')
            with self.assertRaisesRegex(RuntimeError, 'fixture_already_exists'):
                final.new_root(home)
            self.assertEqual((root / 'keep').read_text(), 'unchanged')

    def test_linked_fixture_and_linked_home_rejected(self):
        with tempfile.TemporaryDirectory() as value:
            home = Path(value)
            (home / final.NAME).symlink_to(home, target_is_directory=True)
            with self.assertRaises(RuntimeError):
                final.new_root(home)
            with self.assertRaises(RuntimeError):
                final.safe_dir(home / final.NAME, os.getuid())

    def test_retained_comparison_does_not_open_identity_or_follow_links(self):
        with tempfile.TemporaryDirectory() as value:
            home = Path(value)
            codex = home / '.codex'
            codex.mkdir(mode=0o700)
            (codex / 'auth.json').symlink_to('/unreadable-auth-do-not-open')
            (codex / 'installation_id').symlink_to('/unreadable-id-do-not-open')
            (codex / 'config.toml').write_text('fixture')
            first = final.retained_digest(home)
            (codex / 'config.toml').write_text('changed')
            self.assertNotEqual(final.retained_digest(home), first)

    def test_process_check_failure_stops_before_use(self):
        class Result:
            returncode = 1
            stdout = ''
        with patch.object(final.subprocess, 'run', return_value=Result()):
            with self.assertRaisesRegex(RuntimeError, 'process_check_failed'):
                final.closed()

    def test_open_test_apps_stop_the_run(self):
        class Result:
            returncode = 0
            stdout = '/Applications/Codex.app/Contents/MacOS/Codex\n'
        with patch.object(final.subprocess, 'run', return_value=Result()):
            with self.assertRaisesRegex(RuntimeError, 'close_test_account_apps'):
                final.closed()


if __name__ == '__main__':
    unittest.main()
