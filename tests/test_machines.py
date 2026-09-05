import json
import os
import fcntl
import base64
from pathlib import Path
import plistlib
import shlex
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from codex_migrate.config import MigrationConfig
from codex_migrate.errors import MigrationError
from codex_migrate.machines import destination_guard, local_machine_uuid
from codex_migrate.transport import SSHTransport
from codex_migrate.ssh_bridge import run as run_bridge
from codex_migrate.destination_lock import LOCK_NAME


SOURCE = "12345678-1234-1234-1234-123456789ABC"


class MachineTests(unittest.TestCase):
    def test_real_source_bridge_entry_without_pythonpath(self):
        transport = SSHTransport(MigrationConfig(target="user@fixture.invalid", target_home="/Users/user"))
        with patch("codex_migrate.machines.local_machine_uuid", return_value=SOURCE):
            entry = shlex.split(transport.rsync_bridge_command())
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        # Invalid protocol arguments fail before SSH; do not replace the real
        # generated interpreter/entry point (the shell launcher is not Python).
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(entry + ["wrong@fixture.invalid", "rsync", "--server", "."],
                                    cwd=temporary, env=environment, capture_output=True,
                                    text=True, timeout=15)
        self.assertEqual(result.returncode, 76, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn("could not safely start the rsync SSH connection", result.stderr)
        self.assertNotIn("SyntaxError", result.stderr)

    def test_source_parser_rejects_unknown_or_ambiguous_identity(self):
        cases = ({}, [], [{}, {}], [{}], [{"IOPlatformUUID": "private data"}],
                 [{"IOPlatformUUID": "00000000-0000-0000-0000-000000000000"}],
                 [{"IOPlatformUUID": "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF"}])
        for value in cases:
            with self.subTest(value=value), patch("codex_migrate.machines.subprocess.run",
                return_value=SimpleNamespace(stdout=plistlib.dumps(value))):
                with self.assertRaisesRegex(MigrationError, "machine identity") as error:
                    local_machine_uuid()
                self.assertNotIn("private data", str(error.exception))
        for failure in (OSError("private error"), subprocess.TimeoutExpired("fixture", 1),
                        subprocess.CalledProcessError(1, "fixture")):
            with patch("codex_migrate.machines.subprocess.run", side_effect=failure):
                with self.assertRaises(MigrationError):
                    local_machine_uuid()
        for value in (b"private invalid plist", b"<?xml version='1.0'?><plist><private"):
            with patch("codex_migrate.machines.subprocess.run", return_value=SimpleNamespace(stdout=value)):
                with self.assertRaisesRegex(MigrationError, "machine identity"):
                    local_machine_uuid()

    def test_source_uuid_is_normalized_and_not_exposed_by_guard(self):
        with patch("codex_migrate.machines.subprocess.run", return_value=SimpleNamespace(
            stdout=plistlib.dumps([{"IOPlatformUUID": SOURCE.lower()}]))):
            self.assertEqual(local_machine_uuid(), SOURCE)
            first, second = destination_guard(), destination_guard()
        self.assertNotIn(SOURCE, first)
        self.assertNotEqual(first, second)

    def test_self_guard_runs_on_this_mac_and_stops_following_command(self):
        script = destination_guard()
        result = subprocess.run(["/bin/zsh", "-f", "-s"], input=script + "echo MUST_NOT_RUN\n",
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 76)
        self.assertEqual(result.stdout, "")
        self.assertIn("destination is this source Mac", result.stderr)

    def test_different_machine_guard_allows_following_command(self):
        actual = local_machine_uuid()
        source = SOURCE if actual != SOURCE else "87654321-1234-1234-1234-123456789ABC"
        with patch("codex_migrate.machines.local_machine_uuid", return_value=source):
            guard = destination_guard()
        result = subprocess.run(["/bin/zsh", "-f", "-s"], input=guard + "echo ALLOWED\n",
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "ALLOWED\n")

    def test_destination_probe_or_comparison_failure_blocks_command(self):
        with patch("codex_migrate.machines.local_machine_uuid", return_value=SOURCE):
            guard = destination_guard()
        for command in ("/usr/sbin/ioreg -a -r -d 1 -c IOPlatformExpertDevice", "/usr/bin/shasum -a 256"):
            result = subprocess.run(["/bin/zsh", "-f", "-s"],
                input=guard.replace(command, "/usr/bin/false") + "echo MUST_NOT_RUN\n",
                capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 76)
            self.assertEqual(result.stdout, "")
            self.assertIn("No migration command was started", result.stderr)

    def test_no_ssh_child_starts_when_source_identity_is_unknown(self):
        transport = SSHTransport(MigrationConfig(target="user@fixture.invalid", target_home="/Users/user"))
        with patch("codex_migrate.machines.local_machine_uuid", side_effect=MigrationError("unknown")), \
             patch("codex_migrate.transport.subprocess.Popen") as child:
            with self.assertRaises(MigrationError):
                transport.run_remote("echo MUST_NOT_RUN")
            child.assert_not_called()

    def test_bridge_validates_arguments_and_keeps_ssh_strict(self):
        transport = SSHTransport(MigrationConfig(target="user@fixture.invalid", target_home="/Users/user"))
        with patch("codex_migrate.machines.local_machine_uuid", return_value=SOURCE):
            payload = shlex.split(transport.rsync_bridge_command())[-1]
        for prefix in (["user@fixture.invalid"], ["-l", "user", "fixture.invalid"]):
            with patch("codex_migrate.ssh_bridge.os.execv") as execute:
                run_bridge([payload] + prefix + ["rsync", "--server", ".", "/tmp/space's $(bad)"])
            command = execute.call_args.args[1]
            self.assertEqual(command[0], "/usr/bin/ssh")
            self.assertIn("StrictHostKeyChecking=yes", command)
            self.assertIn("BatchMode=yes", command)
            self.assertEqual(command[-2], "user@fixture.invalid")
            # The entire remote command is a single SSH argument, with no
            # rsync implementation-dependent --rsync-path token splitting.
            self.assertTrue(command[-1].startswith("/bin/zsh -f -c "))
        for args in (["someone@other.invalid", "rsync", "--server", "."],
                     ["-l", "other", "fixture.invalid", "rsync", "--server", "."],
                     ["user@fixture.invalid", "sh", "--server", "."],
                     ["user@fixture.invalid", "rsync", "--server", "--sender", "."]):
            with self.subTest(args=args), patch("codex_migrate.ssh_bridge.os.execv") as execute:
                with self.assertRaises(MigrationError):
                    run_bridge([payload] + args)
                execute.assert_not_called()
        for invalid in ("not-base64", base64.b64encode(b'{"target":"PRIVATE"}').decode(), "A" * 17000):
            with patch("codex_migrate.ssh_bridge.os.execv") as execute:
                with self.assertRaises(MigrationError) as error:
                    run_bridge([invalid])
                execute.assert_not_called()
                self.assertNotIn("PRIVATE", str(error.exception))

    def test_bridge_keeps_ipv6_brackets_for_rsync_but_removes_them_for_ssh(self):
        transport = SSHTransport(MigrationConfig(
            target="user@[fe80::1234%en7]",
            target_home="/Users/user",
        ).validate())
        with patch("codex_migrate.machines.local_machine_uuid", return_value=SOURCE):
            payload = shlex.split(transport.rsync_bridge_command())[-1]
        with patch("codex_migrate.ssh_bridge.os.execv") as execute:
            run_bridge([
                payload,
                "-l",
                "user",
                "fe80::1234%en7",
                "rsync",
                "--server",
                ".",
                "/Users/user/staging",
            ])
        command = execute.call_args.args[1]
        self.assertEqual(command[-2], "user@fe80::1234%en7")
        self.assertNotIn("user@[fe80::1234%en7]", command)

    def test_every_remote_script_rechecks_destination(self):
        transport = SSHTransport(MigrationConfig(target="user@fixture.invalid", target_home="/Users/user"))
        child = Mock(returncode=0)
        child.communicate.return_value = ("OK", "")
        with patch("codex_migrate.machines.local_machine_uuid", return_value=SOURCE), \
             patch("codex_migrate.transport.subprocess.Popen", return_value=child):
            transport.run_remote("echo FIRST")
            transport.run_remote("echo SECOND")
        scripts = [call.kwargs["input"] for call in child.communicate.call_args_list]
        self.assertEqual(len(scripts), 2)
        for script in scripts:
            self.assertIn("/usr/sbin/ioreg", script)
            self.assertLess(script.index("destination is this source Mac"), script.index("echo FIRST") if "echo FIRST" in script else script.index("echo SECOND"))
            self.assertNotIn(SOURCE, script)

    def test_guarded_rsync_protocol_preserves_spaces_and_refuses_self_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, destination = root / "source space", root / "destination space's [files]"
            source.mkdir(); destination.mkdir()
            (source / "unfinished file.txt").write_text("fixture contents")
            # Emulate only SSH command execution, not its authentication/network.
            # The real rsync client/server and generated remote guard still run.
            wrapper = root / "fixture-ssh"
            wrapper.write_text("#!" + sys.executable + "\nimport os,sys\n"
                               "args=sys.argv[1:]\n"
                               "if args[:1]==['-l']: args=args[2:]\n"
                               "args=args[1:]\n"
                               "os.execv('/bin/zsh',['/bin/zsh','-f','-c',' '.join(args)])\n")
            wrapper.chmod(0o700)
            bridge = root / "fixture-bridge.py"
            bridge.write_text("import sys\nfrom unittest.mock import patch\n"
                              "sys.path.insert(0," + repr(str(Path(__file__).parents[1] / "src")) + ")\n"
                              "from codex_migrate.ssh_bridge import run\n"
                              "with patch('codex_migrate.transport.SSHTransport.ssh_base',return_value=[" + repr(str(wrapper)) + "]):\n"
                              "    run(sys.argv[2:])\n")
            actual = local_machine_uuid()
            other = SOURCE if actual != SOURCE else "87654321-1234-1234-1234-123456789ABC"
            for identity, allowed in ((actual, False), (other, True)):
                transport = SSHTransport(MigrationConfig(target="user@alias-for-this-mac.invalid", target_home=str(root.resolve())))
                with patch("codex_migrate.machines.local_machine_uuid", return_value=identity):
                    entry = shlex.split(transport.rsync_bridge_command())
                entry[1] = str(bridge)
                with patch.object(transport, "rsync_bridge_command", return_value=shlex.join(entry)):
                    transfer = transport.rsync_process(str(source), str(destination))
                if allowed:
                    with (root / LOCK_NAME).open("a") as lock:
                        os.chmod(root / LOCK_NAME, 0o600)
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        blocked = subprocess.run(transfer.command, capture_output=True, text=True, timeout=15)
                        self.assertNotEqual(blocked.returncode, 0)
                        self.assertIn("Another migration is using this destination", blocked.stderr)
                        self.assertFalse((destination / "unfinished file.txt").exists())
                result = subprocess.run(transfer.command, capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode == 0, allowed, result.stderr)
                if not allowed:
                    self.assertIn("destination is this source Mac", result.stderr)
                self.assertEqual((destination / "unfinished file.txt").exists(), allowed)
            self.assertEqual((destination / "unfinished file.txt").read_text(), "fixture contents")


if __name__ == "__main__":
    unittest.main()
