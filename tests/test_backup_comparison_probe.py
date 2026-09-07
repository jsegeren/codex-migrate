import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import backup_comparison_probe as probe


class ProbeTests(unittest.TestCase):
    def test_backup_reference_rejects_other_paths(self):
        name = 'Codex-Migrate-Backup-20260906T120000Z-' + 'a' * 16
        self.assertEqual(probe.backup_name(str(probe.TARGET / name)), name)
        for value in (None, '/tmp/' + name, str(probe.TARGET / '../' / name),
                      str(probe.TARGET / 'auth.json'), str(probe.TARGET / (name + '/.codex'))):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                probe.backup_name(value)

    def test_metadata_report_does_not_include_names(self):
        result = probe.differences({'PRIVATE_SENTINEL': 'socket', 'same': 'fifo'},
                                   {'same': 'file', 'EXTRA_SENTINEL': 'link'})
        self.assertEqual(result['missing_by_type'], {'socket': 1})
        self.assertEqual(result['extra_by_type'], {'link': 1})
        self.assertEqual(result['changed_type_count'], 1)
        self.assertNotIn('SENTINEL', json.dumps(result))

    def test_directory_link_is_not_traversed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'external').symlink_to('/Users')
            self.assertEqual(probe.tree(root), {'external': 'link'})
            with self.assertRaises(RuntimeError):
                probe.tree(root / 'external')

    def test_probe_is_dry_run_and_does_not_export_unknown_output(self):
        def run(command, **kwargs):
            self.assertIn('-rlnc', command)
            self.assertIn('--delete', command)
            kwargs['stdout'].write(b'>fc........\nskipping PRIVATE_SENTINEL\n')
            return subprocess.CompletedProcess(command, 0)
        with patch.object(probe.subprocess, 'run', side_effect=run):
            result = probe.compare(Path('/original'), Path('/backup'), True)
        self.assertEqual(result['itemized_codes'], {'>fc........': 1})
        self.assertEqual(result['other_output_lines'], 1)
        self.assertFalse(result['clean'])
        self.assertNotIn('SENTINEL', json.dumps(result))

    def test_failed_command_cannot_claim_clean(self):
        with patch.object(probe.subprocess, 'run', return_value=subprocess.CompletedProcess([], 23)):
            self.assertFalse(probe.compare(Path('/a'), Path('/b'), True)['clean'])

    @unittest.skipUnless(os.path.exists('/usr/bin/rsync'), 'system rsync required')
    def test_real_checksum_mismatch_preserves_both_trees(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original, backup = root / 'original', root / 'backup'
            original.mkdir(); backup.mkdir()
            (original / 'private-name').write_text('same-size-a')
            (backup / 'private-name').write_text('same-size-b')
            result = probe.compare(original, backup, True)
            self.assertTrue(result['completed'])
            self.assertFalse(result['clean'])
            self.assertNotIn('private-name', json.dumps(result))
            self.assertEqual((original / 'private-name').read_text(), 'same-size-a')
            self.assertEqual((backup / 'private-name').read_text(), 'same-size-b')

    @unittest.skipUnless(os.uname().sysname == 'Darwin', 'macOS clone behavior')
    def test_real_fifo_and_socket_are_distinguished(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original, backup = root / 'original', root / 'backup'
            original.mkdir()
            os.mkfifo(original / 'pipe')
            with socket.socket(socket.AF_UNIX) as endpoint:
                endpoint.bind(str(original / 'socket'))
                subprocess.run(['/bin/cp', '-c', '-Rp', str(original), str(backup)], check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                result = probe.differences(probe.tree(original), probe.tree(backup))
                self.assertEqual(result['missing_by_type'], {'socket': 1})
                self.assertFalse(probe.compare(original, backup, True)['clean'])
            (original / 'socket').unlink()
            self.assertFalse(probe.compare(original, backup, False)['clean'])
            self.assertTrue(probe.compare(original, backup, True)['clean'])


if __name__ == '__main__':
    unittest.main()
