import unittest
from final_connection_loss_acceptance import transfer_ssh


class TransferSelectionTests(unittest.TestCase):
    ROWS = '''100 1 502 /fixture/codex-migrate-engine
101 100 502 /usr/bin/rsync
102 101 502 /usr/bin/ssh
200 1 501 /usr/bin/rsync
201 200 501 /usr/bin/ssh
202 100 502 /usr/bin/ssh
'''

    def test_only_owned_rsync_transport_selected(self):
        self.assertEqual(transfer_ssh(self.ROWS, 100, 502), 102)

    def test_wrong_uid_or_missing_engine_rejected(self):
        self.assertIsNone(transfer_ssh(self.ROWS, 100, 501))
        self.assertIsNone(transfer_ssh(self.ROWS, 999, 502))

    def test_ambiguous_transfer_rejected(self):
        self.assertIsNone(transfer_ssh(self.ROWS + '103 101 502 /usr/bin/ssh\n', 100, 502))

    def test_non_rsync_ssh_not_selected(self):
        self.assertIsNone(transfer_ssh(self.ROWS.replace('/usr/bin/rsync', '/bin/zsh'), 100, 502))


if __name__ == '__main__':
    unittest.main()
