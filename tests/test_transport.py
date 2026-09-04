import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from codex_migrate.config import MigrationConfig, SSHOptions
from codex_migrate.transport import SSHTransport, TransferProcess, TransportError, _signal_group


class TransportTests(unittest.TestCase):
    def test_darwin_exit_permission_race_requires_reaped_child(self):
        child = Mock(pid=12345)
        with patch("codex_migrate.transport.os.killpg", side_effect=PermissionError):
            child.poll.return_value = 0
            _signal_group(child, 15)
            child.poll.return_value = None
            with self.assertRaises(PermissionError):
                _signal_group(child, 15)

    def test_cancel_tolerates_exit_between_term_and_continue(self):
        transfer = TransferProcess(["/usr/bin/true"])
        transfer.process = Mock(pid=12345)
        transfer.process.poll.return_value = None
        with patch("codex_migrate.transport.os.killpg", side_effect=[None, ProcessLookupError]):
            transfer.cancel()
        self.assertTrue(transfer._cancel_requested)

    def test_remote_check_uses_diskutil_plist_for_filesystem_type(self):
        config = MigrationConfig(
            target="user@host.local",
            target_home="/Users/user",
        ).validate()
        transport = SSHTransport(config)
        with patch.object(
            transport,
            "run_remote",
            return_value=SimpleNamespace(stdout="REMOTE_OK=1\n"),
        ) as run_remote:
            transport.check()
        script = run_remote.call_args.args[0]
        self.assertIn("diskutil info -plist", script)
        self.assertIn("FilesystemType", script)
        self.assertNotIn("stat -f %T", script)

    def test_ssh_is_strict_and_uses_argument_boundaries(self):
        config = MigrationConfig(
            target="user@host.local",
            target_home="/Users/user",
            ssh=SSHOptions(
                identity_file="/Users/source/.ssh/migrate",
                known_hosts_file="/Users/source/.ssh/known_hosts",
                host_key_alias="host.local",
            ),
        ).validate()
        args = SSHTransport(config).ssh_base()
        joined = " ".join(args)
        self.assertIn("StrictHostKeyChecking=yes", joined)
        self.assertNotIn("StrictHostKeyChecking=no", joined)
        self.assertIn("HostKeyAlias=host.local", args)

    def test_rsync_excludes_destination_authentication(self):
        config = MigrationConfig(
            target="user@host.local",
            target_home="/Users/user",
        ).validate()
        process = SSHTransport(config).rsync_process(
            "/Users/source/.codex",
            "/Users/user/staging/.codex",
            ["auth.json", "installation_id"],
        )
        joined = " ".join(process.command)
        self.assertIn("auth.json", joined)
        self.assertIn("installation_id", joined)
        self.assertIn("--partial", process.command)
        self.assertIn("--delete-after", process.command)

    def test_cancel_before_spawn_prevents_process_start(self):
        process = TransferProcess(["/usr/bin/true"])
        process.cancel()
        with self.assertRaises(TransportError):
            process.start()

    def test_safe_links_option_is_available_for_non_dereferenced_transfers(self):
        config = MigrationConfig(
            target="user@host.local",
            target_home="/Users/user",
        ).validate()
        process = SSHTransport(config).rsync_process(
            "/Users/source/.agents/skills/example",
            "/Users/user/staging/example",
            safe_links=True,
        )
        self.assertIn("--safe-links", process.command)

    def test_validated_skill_sync_can_materialize_confined_links(self):
        config = MigrationConfig(
            target="user@host.local",
            target_home="/Users/user",
        ).validate()
        process = SSHTransport(config).rsync_process(
            "/Users/source/.agents/skills/example",
            "/Users/user/staging/example",
            copy_links=True,
        )
        self.assertIn("--copy-links", process.command)


if __name__ == "__main__":
    unittest.main()
