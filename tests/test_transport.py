import unittest
import threading
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock, patch

from codex_migrate.config import MigrationConfig, SSHOptions
from codex_migrate.transport import (
    SSHTransport,
    TransferProcess,
    TransportError,
    _signal_group,
    _ssh_failure_message,
)


class TransportTests(unittest.TestCase):
    def test_untrusted_host_explains_that_password_was_not_attempted(self):
        message = _ssh_failure_message(
            "No ED25519 host key is known for private-host.local and you have "
            "requested strict checking.\nHost key verification failed.",
            "",
        )
        self.assertIn("Your password was not attempted", message)
        self.assertIn("fingerprints match exactly", message)
        self.assertNotIn("private-host.local", message)

    def test_changed_host_identity_stops_without_replacement_instructions(self):
        message = _ssh_failure_message(
            "WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!\n"
            "Host key verification failed.",
            "",
        )
        self.assertIn("saved SSH identity", message)
        self.assertIn("No password was attempted", message)
        self.assertNotIn("ssh-keygen -R", message)

    def test_key_authentication_distinguishes_interactive_password(self):
        message = _ssh_failure_message(
            "destination-user@private-host: Permission denied "
            "(publickey,password,keyboard-interactive).",
            "",
        )
        self.assertIn("non-interactive key authentication failed", message)
        self.assertIn("does not send or prompt for a password", message)
        self.assertNotIn("private-host", message)

    def test_common_network_failures_have_specific_safe_actions(self):
        self.assertIn(
            "could not be resolved",
            _ssh_failure_message("ssh: Could not resolve hostname private-host", ""),
        )
        self.assertIn(
            "Remote Login",
            _ssh_failure_message("ssh: connect to host private-host port 22: Connection refused", ""),
        )
        self.assertIn(
            "could not be reached",
            _ssh_failure_message("ssh: connect to host private-host port 22: Operation timed out", ""),
        )

    def test_unknown_remote_failure_remains_bounded(self):
        self.assertEqual(_ssh_failure_message("unknown failure", "ignored"), "unknown failure")
        self.assertEqual(len(_ssh_failure_message("x" * 5000, "")), 4096)

    def test_remote_command_surfaces_classified_host_key_failure(self):
        transport = SSHTransport(
            MigrationConfig(target="user@host.local", target_home="/Users/user").validate()
        )
        child = Mock(pid=12345, returncode=255)
        child.communicate.return_value = (
            "",
            "No ED25519 host key is known for private-host.local and you have "
            "requested strict checking.\nHost key verification failed.",
        )
        with patch.object(transport, "machine_guard", return_value=""), \
             patch("codex_migrate.transport.subprocess.Popen", return_value=child):
            with self.assertRaisesRegex(TransportError, "password was not attempted"):
                transport.run_remote("printf fixture", timeout=5)
        self.assertEqual(transport._active_remote, [])

    def test_remote_cancellation_during_guard_prevents_late_launch(self):
        transport = SSHTransport(MigrationConfig(target="user@host.local", target_home="/Users/user").validate())
        entered, release, cancelled = threading.Event(), threading.Event(), threading.Event()
        errors = []
        def guard():
            entered.set()
            self.assertTrue(release.wait(5))
            return ""
        def run():
            try:
                transport.run_remote_cancellable("", 5, cancelled.is_set)
            except TransportError as error:
                errors.append(error)
        with patch.object(transport, "machine_guard", guard), patch("codex_migrate.transport.subprocess.Popen") as spawn:
            thread = threading.Thread(target=run)
            thread.start()
            self.assertTrue(entered.wait(5))
            cancelled.set()
            transport.cancel_all()
            release.set()
            thread.join(5)
            self.assertFalse(thread.is_alive())
            spawn.assert_not_called()
        self.assertEqual(len(errors), 1)
        self.assertEqual(transport._active_remote, [])

    def test_remote_cancellation_waits_for_launch_registration_then_reaps_child(self):
        transport = SSHTransport(MigrationConfig(target="user@host.local", target_home="/Users/user").validate())
        spawned, release, cancelled = threading.Event(), threading.Event(), threading.Event()
        real_spawn = subprocess.Popen
        children, errors = [], []
        def spawn(*args, **kwargs):
            child = real_spawn(["/bin/sleep", "30"], **kwargs)
            children.append(child)
            spawned.set()
            self.assertTrue(release.wait(5))
            return child
        def run():
            try:
                transport.run_remote_cancellable("", 5, cancelled.is_set)
            except TransportError as error:
                errors.append(error)
        with patch.object(transport, "machine_guard", return_value=""), \
             patch("codex_migrate.transport.subprocess.Popen", spawn):
            worker = threading.Thread(target=run)
            worker.start()
            self.assertTrue(spawned.wait(5))
            cancelled.set()
            stop = threading.Thread(target=transport.cancel_all)
            stop.start()
            release.set()
            stop.join(5)
            worker.join(5)
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait(5)
                self.fail("Cancelled child was not reaped")
        self.assertFalse(worker.is_alive())
        self.assertFalse(stop.is_alive())
        self.assertEqual(transport._active_remote, [])
        self.assertEqual(len(errors), 1)

    def test_darwin_exit_permission_race_requires_reaped_child(self):
        child = Mock(pid=12345)
        with patch("codex_migrate.transport.os.killpg", side_effect=PermissionError):
            child.poll.return_value = 0
            _signal_group(child, 15)
            child.poll.return_value = None
            import subprocess
            child.wait.side_effect = subprocess.TimeoutExpired("fixture", 0.1)
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
