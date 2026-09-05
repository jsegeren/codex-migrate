import base64
import json
import socket
import subprocess
import threading
import unittest
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

    def test_select_route_benchmarks_resolved_addresses_and_pins_fastest_key(self):
        config = MigrationConfig(
            target="user@new-mac.local",
            target_home="/Users/user",
        ).validate()
        transport = SSHTransport(config)

        def speed(target, alias, megabytes):
            self.assertEqual(alias, "new-mac.local")
            self.assertEqual(megabytes, 8)
            return 900.0 if "169.254.4.2" in target else 120.0

        with patch.object(
            transport,
            "_candidate_addresses",
            return_value=["192.168.1.8", "169.254.4.2"],
        ), patch.object(transport, "_benchmark_target", side_effect=speed), patch.object(
            transport,
            "_route_for_address",
            return_value="Thunderbolt Bridge (bridge0 → 169.254.4.2)",
        ):
            label = transport.select_route(megabytes=8)

        self.assertIn("Thunderbolt Bridge", label)
        self.assertIn("900 Mbps", label)
        self.assertEqual(transport._connection_target, "user@169.254.4.2")
        self.assertEqual(transport._connection_host_key_alias, "new-mac.local")
        self.assertIn("HostKeyAlias=new-mac.local", transport.ssh_base())
        process = transport.rsync_process("/Users/source/project", "/Users/user/staging/project")
        self.assertEqual(process.command[-1], "user@169.254.4.2:/Users/user/staging/project/")

        payload = transport.rsync_bridge_command().split()[-1]
        decoded = json.loads(base64.urlsafe_b64decode(payload.encode()))
        self.assertEqual(decoded["target"], "user@169.254.4.2")
        self.assertEqual(decoded["ssh"]["host_key_alias"], "new-mac.local")

    def test_select_route_keeps_saved_target_when_alternatives_fail_verification(self):
        config = MigrationConfig(
            target="user@new-mac.local",
            target_home="/Users/user",
        ).validate()
        transport = SSHTransport(config)
        with patch.object(
            transport,
            "_candidate_addresses",
            return_value=["192.168.1.8", "169.254.4.2"],
        ), patch.object(
            transport,
            "_benchmark_target",
            side_effect=TransportError("not trusted"),
        ), patch.object(transport, "route", return_value="Wi-Fi (en0 → 192.168.1.8)"):
            label = transport.select_route(megabytes=1)
        self.assertIn("alternative routes could not be verified", label)
        self.assertEqual(transport._connection_target, config.target)
        self.assertIsNone(transport._connection_host_key_alias)

    def test_select_route_stops_instead_of_trying_another_address_after_cancel(self):
        transport = SSHTransport(
            MigrationConfig(target="user@new-mac.local", target_home="/Users/user").validate()
        )
        stopped = [False]

        def interrupted(*_args):
            stopped[0] = True
            raise TransportError("speed probe terminated")

        with patch.object(
            transport,
            "_candidate_addresses",
            return_value=["192.168.1.8", "169.254.4.2"],
        ), patch.object(transport, "_benchmark_target", side_effect=interrupted) as benchmark:
            with self.assertRaisesRegex(TransportError, "route test stopped"):
                transport.select_route(cancelled=lambda: stopped[0])
        self.assertEqual(benchmark.call_count, 1)

    def test_select_route_does_not_benchmark_a_single_address(self):
        transport = SSHTransport(
            MigrationConfig(target="user@new-mac.local", target_home="/Users/user").validate()
        )
        with patch.object(transport, "_candidate_addresses", return_value=["192.168.1.8"]), \
             patch.object(transport, "route", return_value="Wi-Fi"), \
             patch.object(transport, "_benchmark_target") as benchmark:
            self.assertEqual(transport.select_route(), "Wi-Fi")
        benchmark.assert_not_called()

    def test_route_discovery_filters_unsafe_addresses_and_scopes_link_local_ipv6(self):
        transport = SSHTransport(
            MigrationConfig(target="user@new-mac.local", target_home="/Users/user").validate()
        )
        records = [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 22)),
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("192.168.1.8", 22)),
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("224.0.0.1", 22)),
            (socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("fe80::1234", 22, 0, 7)),
            (socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("::", 22, 0, 0)),
        ]
        with patch("codex_migrate.transport.socket.getaddrinfo", return_value=records), \
             patch("codex_migrate.transport.socket.if_indextoname", return_value="en7"), \
             patch.object(transport, "_remote_addresses", return_value=[]):
            self.assertEqual(
                transport._candidate_addresses(),
                ["fe80::1234%en7", "192.168.1.8"],
            )

    def test_route_discovery_uses_only_bounded_private_addresses_from_trusted_mac(self):
        transport = SSHTransport(
            MigrationConfig(target="user@new-mac.local", target_home="/Users/user").validate()
        )
        output = "\n".join((
            "127.0.0.1",
            "169.254.4.2",
            "fe80::1234%bridge0",
            "192.168.1.8",
            "8.8.8.8",
            "not-an-address",
        ))
        with patch.object(
            transport,
            "run_remote_cancellable",
            return_value=SimpleNamespace(stdout=output),
        ) as remote:
            addresses = transport._remote_addresses(lambda: False)
        self.assertEqual(addresses, ["169.254.4.2", "192.168.1.8"])
        self.assertIn("/sbin/ifconfig -a", remote.call_args.args[0])

    def test_route_label_uses_macos_hardware_port_name(self):
        transport = SSHTransport(
            MigrationConfig(target="user@new-mac.local", target_home="/Users/user").validate()
        )
        route = SimpleNamespace(stdout="   interface: bridge0\n")
        ports = SimpleNamespace(stdout=(
            "Hardware Port: Wi-Fi\nDevice: en0\n\n"
            "Hardware Port: Thunderbolt Bridge\nDevice: bridge0\n"
        ))
        with patch("codex_migrate.transport.subprocess.run", side_effect=[route, ports]):
            self.assertEqual(
                transport._route_for_address("169.254.4.2"),
                "Thunderbolt Bridge (bridge0 → 169.254.4.2)",
            )

    def test_benchmark_is_guarded_registered_and_disables_compression(self):
        transport = SSHTransport(
            MigrationConfig(target="user@new-mac.local", target_home="/Users/user").validate()
        )
        child = Mock(pid=12345, returncode=0)
        child.communicate.return_value = (None, b"")
        with patch.object(transport, "machine_guard", return_value="printf guarded\\n"), \
             patch("codex_migrate.transport.subprocess.Popen", return_value=child) as spawn:
            self.assertGreater(
                transport._benchmark_target("user@169.254.4.2", "new-mac.local", 1),
                0,
            )
        command = spawn.call_args.args[0]
        self.assertIn("HostKeyAlias=new-mac.local", command)
        self.assertIn("Compression=no", command)
        self.assertIn("user@169.254.4.2", command)
        self.assertIn("printf guarded", command[-1])
        self.assertEqual(len(child.communicate.call_args.kwargs["input"]), 1024 * 1024)
        self.assertEqual(transport._active_remote, [])

    def test_scoped_ipv6_uses_rsync_brackets_but_not_ssh_hostname_brackets(self):
        transport = SSHTransport(
            MigrationConfig(
                target="user@[fe80::1234%en7]",
                target_home="/Users/user",
            ).validate()
        )
        child = Mock(pid=12345, returncode=0)
        child.communicate.return_value = ("ok", "")
        with patch.object(transport, "machine_guard", return_value=""), \
             patch("codex_migrate.transport.subprocess.Popen", return_value=child) as spawn:
            transport.run_remote("printf ok")
        self.assertIn("user@fe80::1234%en7", spawn.call_args.args[0])
        self.assertNotIn("user@[fe80::1234%en7]", spawn.call_args.args[0])
        process = transport.rsync_process("/Users/source/project", "/Users/user/staging")
        self.assertEqual(process.command[-1], "user@[fe80::1234%en7]:/Users/user/staging/")

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
