import os
import tempfile
import unittest
from unittest.mock import patch

from codex_migrate.state import StateStore


class StateTests(unittest.TestCase):
    def test_recovery_checkpoint_requires_durable_file_and_directory_sync(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = StateStore(temporary)
            store.update(recovery_attempt={"reference": "synthetic", "resolved": False})
            store.sync_recovery_checkpoint()
            self.assertEqual(StateStore(temporary).read()["recovery_attempt"]["reference"], "synthetic")
            with patch("codex_migrate.state.os.fsync", side_effect=OSError("synthetic sync failure")):
                with self.assertRaises(OSError):
                    store.sync_recovery_checkpoint()
            with patch("codex_migrate.state.fcntl.fcntl", side_effect=OSError("synthetic device failure")):
                with self.assertRaises(OSError):
                    store.sync_recovery_checkpoint()
    def test_state_and_token_are_owner_only_and_persistent(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = StateStore(temporary)
            store.update(status="running", percent=12.5)
            self.assertEqual(store.read()["status"], "running")
            first = store.token()
            second = StateStore(temporary).token()
            self.assertEqual(first, second)
            self.assertEqual(os.stat(store.path).st_mode & 0o777, 0o600)
            self.assertEqual(os.stat(store.token_path).st_mode & 0o777, 0o600)

    def test_process_lock_rejects_a_second_owner(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = StateStore(temporary)
            second = StateStore(temporary)
            first.acquire_process_lock()
            try:
                with self.assertRaises(RuntimeError):
                    second.acquire_process_lock()
            finally:
                first.release_process_lock()
            second.acquire_process_lock()
            second.release_process_lock()


if __name__ == "__main__":
    unittest.main()
