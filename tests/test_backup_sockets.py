"""Real macOS socket/clone fixtures plus install/rollback safety boundaries."""

import json
import os
from pathlib import Path
import platform
import shlex
import socket
import subprocess
import tempfile
import unittest

import test_transactions as fixtures
from codex_migrate.backup import BACKUP_FUNCTIONS


def endpoint(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    # AF_UNIX has a short path limit. Only this synthetic test process changes
    # cwd, restoring it even if bind fails; no endpoint is ever connected.
    previous = os.open('.', os.O_RDONLY)
    try:
        os.chdir(path.parent)
        with socket.socket(socket.AF_UNIX) as handle:
            handle.bind(path.name)
    finally:
        os.fchdir(previous)
        os.close(previous)


@unittest.skipUnless(platform.system() == 'Darwin', 'actual macOS backup fixtures')
class CodexSocketBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.original, self.copy = self.root / 'original', self.root / 'copy'
        self.original.mkdir()
        (self.original / 'private-file').write_text('original')

    def clone(self):
        result = subprocess.run(['/bin/cp', '-c', '-Rp', str(self.original), str(self.copy)],
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0)

    def verify(self, codex=True):
        function = 'verify_codex_backup' if codex else 'verify_backup'
        result = subprocess.run(['/bin/zsh', '-f', '-s'],
            input='set -eu\n' + BACKUP_FUNCTIONS + '\n' + function + ' ' +
                  shlex.quote(str(self.original)) + ' ' + shlex.quote(str(self.copy)),
            capture_output=True, text=True, timeout=10)
        self.assertNotIn('private', result.stdout + result.stderr)
        return result.returncode

    def test_actual_clone_omits_runtime_socket_but_durable_data_matches(self):
        endpoint(self.original / 'private.sock')
        endpoint(self.original / 'ipc/nested/private-endpoint')
        self.clone()
        self.assertFalse((self.copy / 'private.sock').exists())
        self.assertEqual(self.verify(), 0)
        self.assertNotEqual(self.verify(codex=False), 0)
        self.assertTrue((self.original / 'private.sock').is_socket())

    def test_missing_or_corrupt_ordinary_data_still_blocks_with_socket(self):
        endpoint(self.original / 'private.sock')
        self.clone()
        (self.copy / 'private-file').write_text('modified')  # Same length.
        self.assertNotEqual(self.verify(), 0)
        (self.copy / 'private-file').unlink()
        self.assertNotEqual(self.verify(), 0)

    def test_socket_named_regular_files_links_and_directories_not_excluded(self):
        for name, kind in [('private.sock', 'file'), ('private.socket', 'link'),
                           ('fsmonitor--daemon.ipc', 'directory')]:
            item = self.original / name
            if kind == 'file':
                item.write_text('private-content')
            elif kind == 'link':
                item.symlink_to('private-target')
            else:
                item.mkdir()
        self.clone()
        self.assertEqual(self.verify(), 0)
        (self.copy / 'private.sock').unlink()
        self.assertNotEqual(self.verify(), 0)

    def test_worktree_and_unknown_sockets_block(self):
        for relative in ['worktrees/repo/private.sock', 'private-unknown']:
            with self.subTest(relative=relative):
                endpoint(self.original / relative)
        self.clone()
        self.assertNotEqual(self.verify(), 0)

    def test_extra_backup_entry_at_omitted_socket_path_blocks(self):
        endpoint(self.original / 'private.sock')
        self.clone()
        (self.copy / 'private.sock').write_text('unexpected')
        self.assertNotEqual(self.verify(), 0)

    def test_backup_socket_itself_is_never_excluded(self):
        endpoint(self.original / 'private.sock')
        self.clone()
        endpoint(self.copy / 'private.sock')
        self.assertNotEqual(self.verify(), 0)

    def test_runtime_directory_link_not_followed(self):
        outside = self.root / 'outside'
        endpoint(outside / 'private.sock')
        (self.original / 'ipc').symlink_to(outside, target_is_directory=True)
        self.clone()
        self.assertEqual(self.verify(), 0)
        (self.copy / 'ipc').unlink()
        (self.copy / 'ipc').symlink_to('different')
        self.assertNotEqual(self.verify(), 0)

    def test_fifo_is_not_treated_as_a_socket(self):
        os.mkfifo(self.original / 'private.sock')
        self.clone()
        self.assertNotEqual(self.verify(), 0)


@unittest.skipUnless(platform.system() == 'Darwin', 'actual APFS installer')
class SocketTransactionTests(unittest.TestCase):
    def setUp(self):
        self.transaction = fixtures.TransactionTests()
        self.transaction.setUp()
        self.addCleanup(self.transaction.doCleanups)
        self.fixture = self.transaction.fixture
        endpoint(self.fixture.target / '.codex/private.sock')

    def test_full_install_freezes_backup_without_socket_and_preserves_identity(self):
        receipt = self.transaction.engine._install_and_verify()
        backup = Path(receipt['backup'])
        self.assertFalse((backup / '.codex/private.sock').exists())
        self.assertEqual((backup / '.codex/old.txt').read_text(), 'original')
        self.assertEqual((self.fixture.target / '.codex/auth.json').read_text(), 'fixture-auth')
        self.assertFalse(self.transaction.journal.exists())
        record = json.loads((backup / 'transaction-receipt.json').read_text())
        self.assertEqual(record['phase'], 'installed')

    def test_actual_post_install_failure_restores_data_without_runtime_socket(self):
        self.transaction.inject(self.transaction.corrupt_installed)
        with self.assertRaisesRegex(RuntimeError, 'rollback was verified'):
            self.transaction.engine._install_and_verify()
        self.assertFalse(self.transaction.journal.exists())
        self.assertEqual((self.fixture.target / '.codex/old.txt').read_text(), 'original')
        self.assertEqual((self.fixture.target / '.codex/auth.json').read_text(), 'fixture-auth')
        self.assertFalse((self.fixture.target / '.codex/private.sock').exists())

    def test_workspace_socket_still_blocks_without_replacing_destination(self):
        endpoint(self.fixture.target / 'Git/private.sock')
        with self.assertRaises(RuntimeError):
            self.transaction.engine._install_and_verify()
        self.fixture.assert_originals_untouched()
        self.assertTrue((self.fixture.target / '.codex/private.sock').is_socket())
        self.assertFalse(self.transaction.journal.exists())
