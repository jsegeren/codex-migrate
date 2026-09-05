"""Strict SSH and rsync transport without shell-built local commands."""

from __future__ import annotations

import base64
from dataclasses import asdict
import ipaddress
import json
import os
from pathlib import Path
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time
from typing import Callable, List, Optional, Sequence, Tuple

from codex_migrate.config import MigrationConfig
from codex_migrate.machines import destination_guard, machine_comparison


OutputCallback = Callable[[str], None]


class TransportError(RuntimeError):
    pass


def _ssh_failure_message(stderr: str, stdout: str) -> str:
    """Turn common SSH failures into bounded, actionable guidance.

    SSH runs in BatchMode, so host verification and key authentication happen
    without an interactive password prompt.  Preserve an unknown diagnostic for
    support, but do not make users infer those two common preconditions from
    OpenSSH's raw stderr.
    """
    raw = (stderr.strip() or stdout.strip() or "remote command failed")[:4096]
    lowered = raw.lower()
    if "remote host identification has changed" in lowered:
        return (
            "The saved SSH identity for the new Mac has changed. No password was "
            "attempted. Stop and compare the new Mac's ED25519 fingerprint through "
            "a trusted channel before changing any saved host-key entry."
        )
    if ("host key verification failed" in lowered
            or ("host key is known" in lowered and "strict checking" in lowered)):
        return (
            "SSH stopped before authentication because the new Mac's host key is "
            "not trusted. Your password was not attempted. On this Mac, run "
            "`ssh new-user@new-mac.local`; on the new Mac, run "
            "`ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`. Accept the host "
            "key only when the fingerprints match exactly, then retry."
        )
    if ("permission denied" in lowered
            or "no supported authentication methods available" in lowered
            or "too many authentication failures" in lowered):
        return (
            "The SSH host was verified, but non-interactive key authentication "
            "failed. The helper does not send or prompt for a password. Add this "
            "Mac's public SSH key to the destination account, verify the same SSH "
            "address connects without a password, then retry."
        )
    if "could not resolve hostname" in lowered or "nodename nor servname provided" in lowered:
        return (
            "The new Mac's SSH address could not be resolved. Confirm its Sharing "
            "name or IP address and that both Macs are on the intended network."
        )
    if "connection refused" in lowered:
        return (
            "The new Mac is reachable, but Remote Login is not accepting SSH. "
            "Enable Remote Login for the destination account and retry."
        )
    if ("operation timed out" in lowered or "connection timed out" in lowered
            or "no route to host" in lowered):
        return (
            "The new Mac could not be reached over the current network. Keep both "
            "Macs awake, reconnect Wi-Fi or wired networking, and retry."
        )
    return raw


def _signal_group(process: subprocess.Popen, number: int) -> None:
    try:
        os.killpg(process.pid, number)
    except ProcessLookupError:
        pass
    except PermissionError as error:
        # Darwin may report EPERM, rather than ESRCH, during exit. Only
        # tolerate it after reaping this exact child; live failures stay loud.
        if process.poll() is None:
            try:
                process.wait(timeout=0.1)
            except subprocess.TimeoutExpired:
                raise error


def _stop_process(process: subprocess.Popen) -> None:
    """Reap our local child group, including suspended transfers, on abort."""
    # The group leader may already have exited while a descendant still owns
    # a pipe. Clean the whole group and bound pipe draining, not just wait().
    _signal_group(process, signal.SIGTERM)
    _signal_group(process, signal.SIGCONT)
    try:
        process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        _signal_group(process, signal.SIGKILL)
        process.communicate(timeout=5)


class SSHTransport:
    def __init__(self, config: MigrationConfig) -> None:
        self.config = config
        self._remote_lock = threading.Lock()
        self._active_remote: List[subprocess.Popen] = []
        self._machine_comparison: Optional[Tuple[str, str]] = None
        self._connection_target = config.target
        self._connection_host_key_alias = config.ssh.host_key_alias
        self._route_label: Optional[str] = None

    def reset_route(self) -> None:
        self._connection_target = self.config.target
        self._connection_host_key_alias = self.config.ssh.host_key_alias
        self._route_label = None

    def machine_guard(self) -> str:
        return destination_guard(self.machine_comparison())

    def machine_comparison(self) -> Tuple[str, str]:
        with self._remote_lock:
            if self._machine_comparison is None:
                self._machine_comparison = machine_comparison()
            return self._machine_comparison

    def rsync_bridge_command(self) -> str:
        # A local SSH adapter owns remote quoting. Apple openrsync splits
        # --rsync-path differently from classic rsync; neither may strip our guard.
        ssh_options = asdict(self.config.ssh)
        ssh_options["host_key_alias"] = self._connection_host_key_alias
        payload = base64.urlsafe_b64encode(json.dumps({
            "target": self._connection_target, "target_home": self.config.target_home,
            "ssh": ssh_options,
            "comparison": self.machine_comparison(),
        }).encode()).decode()
        if getattr(sys, "frozen", False):
            entry = [sys.executable]
        else:
            entry = [sys.executable, str(Path(__file__).resolve().with_name("__main__.py"))]
        return " ".join(shlex.quote(arg) for arg in entry + ["_ssh-rsync", payload])

    def _ssh_base(self, host_key_alias: Optional[str]) -> List[str]:
        options = self.config.ssh
        args = [
            "/usr/bin/ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=%d" % options.connect_timeout,
            "-o",
            "ServerAliveInterval=15",
            "-o",
            "ServerAliveCountMax=4",
            "-o",
            "StrictHostKeyChecking=yes",
        ]
        if options.isolated:
            args.extend(["-F", "/dev/null"])
            for option in ("IdentityAgent=none", "IdentitiesOnly=yes", "GlobalKnownHostsFile=/dev/null",
                           "HostKeyAlgorithms=ssh-ed25519", "VerifyHostKeyDNS=no", "UpdateHostKeys=no",
                           "PasswordAuthentication=no", "KbdInteractiveAuthentication=no",
                           "ForwardAgent=no", "ClearAllForwardings=yes", "RequestTTY=no"):
                args.extend(["-o", option])
        if options.identity_file:
            args.extend(["-i", options.identity_file])
        if options.known_hosts_file:
            args.extend(["-o", "UserKnownHostsFile=%s" % options.known_hosts_file])
        if host_key_alias:
            args.extend(["-o", "HostKeyAlias=%s" % host_key_alias])
        return args

    def ssh_base(self) -> List[str]:
        return self._ssh_base(self._connection_host_key_alias)

    def ssh_transport_string(self) -> str:
        return " ".join(shlex.quote(item) for item in self.ssh_base())

    def run_remote(self, script: str, timeout: int = 60) -> subprocess.CompletedProcess:
        return self._run_remote(script, timeout)

    def run_remote_cancellable(self, script: str, timeout: int, cancelled) -> subprocess.CompletedProcess:
        return self._run_remote(script, timeout, cancelled)

    def _run_remote(self, script, timeout, cancelled=None):
        if cancelled and cancelled():
            raise TransportError("Recovery check stopped before connecting")
        script = self.machine_guard() + script
        command = self.ssh_base() + [
            self._ssh_destination(self._connection_target),
            "/bin/zsh -f -s",
        ]
        with self._remote_lock:
            # Pair cancellation's active-child snapshot with launch/registration.
            # The callback only reads a flag; it must not acquire engine locks.
            if cancelled and cancelled():
                raise TransportError("Recovery check stopped before connecting")
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            self._active_remote.append(process)
        try:
            try:
                stdout, stderr = process.communicate(input=script, timeout=timeout)
            except subprocess.TimeoutExpired as error:
                raise TransportError("remote command timed out") from error
        except BaseException:
            _stop_process(process)
            raise
        finally:
            with self._remote_lock:
                if process in self._active_remote:
                    self._active_remote.remove(process)
        result = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        if result.returncode != 0:
            raise TransportError(_ssh_failure_message(result.stderr, result.stdout))
        return result

    def cancel_all(self) -> None:
        with self._remote_lock:
            active = list(self._active_remote)
        for process in active:
            if process.poll() is None:
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                except OSError:
                    pass

    def check(self) -> str:
        result = self.run_remote(
            "set -eu\n"
            "test \"$(uname -s)\" = Darwin\n"
            "command -v rsync >/dev/null\n"
            "command -v sqlite3 >/dev/null\n"
            "command -v diskutil >/dev/null\n"
            "command -v plutil >/dev/null\n"
            "volume_device=$(df \"$HOME\" | tail -1 | awk '{print $1}')\n"
            "filesystem=$(diskutil info -plist \"$volume_device\" | "
            "plutil -extract FilesystemType raw -o - -)\n"
            "printf 'REMOTE_OK=1\\nUSER=%s\\nHOME=%s\\nFILESYSTEM=%s\\n' "
            "\"$(id -un)\" \"$HOME\" \"$filesystem\"\n"
        )
        return result.stdout

    def remote_bytes(self, path: str) -> int:
        quoted = shlex.quote(path)
        result = self.run_remote(
            "if test -e %s; then /usr/bin/du -sk %s | awk '{print $1}'; else echo 0; fi\n"
            % (quoted, quoted),
            timeout=120,
        )
        value = result.stdout.strip().splitlines()[-1]
        return int(value) * 1024

    def remote_free_bytes(self, path: str) -> int:
        quoted = shlex.quote(path)
        result = self.run_remote(
            "/bin/df -Pk %s | /usr/bin/tail -1 | /usr/bin/awk '{print $4}'\n" % quoted,
            timeout=30,
        )
        value = result.stdout.strip().splitlines()[-1]
        return int(value) * 1024

    @staticmethod
    def _target_parts(target: str) -> Tuple[str, str]:
        user, host = target.rsplit("@", 1)
        return user, host.strip("[]")

    @classmethod
    def _ssh_destination(cls, target: str) -> str:
        user, host = cls._target_parts(target)
        return "%s@%s" % (user, host)

    @staticmethod
    def _is_usable_address(address: str) -> bool:
        try:
            parsed = ipaddress.ip_address(address.split("%", 1)[0])
        except ValueError:
            return False
        return not (parsed.is_loopback or parsed.is_multicast or parsed.is_unspecified)

    @staticmethod
    def _format_target(user: str, address: str) -> str:
        if ":" in address:
            return "%s@[%s]" % (user, address)
        return "%s@%s" % (user, address)

    def _resolved_addresses(self) -> List[str]:
        _user, host = self._target_parts(self.config.target)
        if self._is_usable_address(host):
            return [host]
        try:
            records = socket.getaddrinfo(
                host,
                22,
                socket.AF_UNSPEC,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
            )
        except socket.error:
            return []
        addresses: List[str] = []
        for family, _kind, _protocol, _canonical, endpoint in records:
            address = endpoint[0]
            if family == socket.AF_INET6:
                scope_id = endpoint[3]
                try:
                    parsed = ipaddress.ip_address(address.split("%", 1)[0])
                except ValueError:
                    continue
                if parsed.is_link_local and scope_id and "%" not in address:
                    try:
                        address += "%" + socket.if_indextoname(scope_id)
                    except OSError:
                        continue
            if self._is_usable_address(address) and address not in addresses:
                addresses.append(address)
            if len(addresses) == 16:
                break
        return addresses

    @staticmethod
    def _preferred_addresses(addresses: Sequence[str]) -> List[str]:
        def preference(address: str) -> Tuple[int, int]:
            parsed = ipaddress.ip_address(address.split("%", 1)[0])
            return (
                0 if parsed.is_link_local else 1 if parsed.is_private else 2,
                0 if parsed.version == 4 else 1,
            )
        return sorted(addresses, key=preference)[:4]

    def _remote_addresses(self, cancelled=None) -> List[str]:
        script = (
            "set -eu\n"
            "/sbin/ifconfig -a | /usr/bin/awk '\n"
            "  $1 == \"inet\" { print $2 }\n"
            "'\n"
        )
        try:
            if cancelled:
                result = self.run_remote_cancellable(script, 15, cancelled)
            else:
                result = self.run_remote(script, timeout=15)
        except TransportError:
            if cancelled and cancelled():
                raise
            return []
        if len(result.stdout) > 16384:
            return []
        addresses: List[str] = []
        for line in result.stdout.splitlines():
            address = line.strip()
            try:
                parsed = ipaddress.ip_address(address.split("%", 1)[0])
            except ValueError:
                continue
            if (self._is_usable_address(address)
                    and parsed.version == 4
                    and (parsed.is_private or parsed.is_link_local)
                    and address not in addresses):
                addresses.append(address)
            if len(addresses) == 16:
                break
        return addresses

    def _candidate_addresses(self, cancelled=None) -> List[str]:
        addresses = self._resolved_addresses()
        if cancelled and cancelled():
            raise TransportError("Connection route test stopped")
        for address in self._remote_addresses(cancelled):
            if address not in addresses:
                addresses.append(address)
        return self._preferred_addresses(addresses)

    @staticmethod
    def _hardware_port(interface: str) -> Optional[str]:
        if not interface or interface == "unknown":
            return None
        try:
            result = subprocess.run(
                ["/usr/sbin/networksetup", "-listallhardwareports"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        port = None
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if stripped.startswith("Hardware Port:"):
                port = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("Device:"):
                device = stripped.split(":", 1)[1].strip()
                if device == interface:
                    return port
                port = None
        return None

    def _route_for_address(self, address: str) -> str:
        try:
            result = subprocess.run(
                ["/sbin/route", "-n", "get", address],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=5,
                check=False,
            )
            interface = "unknown"
            for line in result.stdout.splitlines():
                if line.strip().startswith("interface:"):
                    interface = line.split(":", 1)[1].strip()
                    break
            port = self._hardware_port(interface)
            parsed = ipaddress.ip_address(address.split("%", 1)[0])
            if port:
                return "%s (%s → %s)" % (port, interface, address)
            if parsed.is_link_local:
                return "Direct link (%s → %s)" % (interface, address)
            if interface == "en0":
                return "Wi-Fi (%s → %s)" % (interface, address)
            return "%s (%s)" % (interface, address)
        except (OSError, ValueError, subprocess.SubprocessError):
            return "SSH (%s)" % address

    def route(self) -> str:
        if self._route_label:
            return self._route_label
        _user, host = self._target_parts(self._connection_target)
        addresses = [host] if self._is_usable_address(host) else self._preferred_addresses(
            self._resolved_addresses()
        )
        if addresses:
            return self._route_for_address(addresses[0])
        return "SSH (%s)" % host

    def _benchmark_target(
        self,
        target: str,
        host_key_alias: Optional[str],
        megabytes: int,
    ) -> float:
        if type(megabytes) is not int or megabytes < 1 or megabytes > 256:
            raise ValueError("connection speed test must be between 1 and 256 MB")
        guard = self.machine_guard()
        command = self._ssh_base(host_key_alias) + [
            "-o",
            "Compression=no",
            self._ssh_destination(target),
            "/bin/zsh -f -c " + shlex.quote(guard + "exec /bin/cat >/dev/null\n"),
        ]
        started = time.monotonic()
        with self._remote_lock:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            self._active_remote.append(process)
        try:
            try:
                _stdout, error = process.communicate(
                    input=b"\0" * (megabytes * 1024 * 1024),
                    timeout=45,
                )
            except subprocess.TimeoutExpired as timeout_error:
                raise TransportError("connection speed test timed out") from timeout_error
        except BaseException:
            _stop_process(process)
            raise
        finally:
            with self._remote_lock:
                if process in self._active_remote:
                    self._active_remote.remove(process)
        if process.returncode != 0:
            raise TransportError(_ssh_failure_message(error.decode("utf-8", "replace"), ""))
        elapsed = max(0.001, time.monotonic() - started)
        return (megabytes * 1024 * 1024 * 8.0) / elapsed / 1_000_000

    def benchmark(self, megabytes: int = 16) -> float:
        return self._benchmark_target(
            self._connection_target,
            self._connection_host_key_alias,
            megabytes,
        )

    def select_route(
        self,
        megabytes: int = 8,
        cancelled: Optional[Callable[[], bool]] = None,
    ) -> str:
        """Compare trusted addresses for the saved host and retain the fastest.

        Candidate IPs come only from the user-provided destination name and the
        bounded interface list read from that already-verified Mac. Each direct
        connection is pinned to the configured destination's trusted SSH key and
        executes the normal destination-machine guard before accepting data.
        """
        self.reset_route()
        if cancelled and cancelled():
            raise TransportError("Connection route test stopped")
        user, original_host = self._target_parts(self.config.target)
        addresses = self._candidate_addresses(cancelled)
        if cancelled and cancelled():
            raise TransportError("Connection route test stopped")
        if len(addresses) < 2:
            return self.route()
        trusted_alias = self.config.ssh.host_key_alias or original_host
        measured = []
        for address in addresses:
            if cancelled and cancelled():
                raise TransportError("Connection route test stopped")
            target = self._format_target(user, address)
            try:
                speed = self._benchmark_target(target, trusted_alias, megabytes)
            except TransportError:
                if cancelled and cancelled():
                    raise TransportError("Connection route test stopped")
                continue
            measured.append((speed, target, address))
        if cancelled and cancelled():
            raise TransportError("Connection route test stopped")
        if not measured:
            self._route_label = self.route() + " · alternative routes could not be verified"
            return self._route_label
        speed, target, address = max(measured)
        self._connection_target = target
        self._connection_host_key_alias = trusted_alias
        self._route_label = "%s · %.0f Mbps · selected from %d addresses" % (
            self._route_for_address(address),
            speed,
            len(addresses),
        )
        return self._route_label

    def rsync_process(
        self,
        source: str,
        destination: str,
        excludes: Sequence[str] = (),
        dry_run: bool = False,
        safe_links: bool = False,
        copy_links: bool = False,
    ) -> "TransferProcess":
        source_path = str(Path(source))
        if not source_path.endswith("/"):
            source_path += "/"
        remote = "%s:%s" % (self._connection_target, destination.rstrip("/") + "/")
        command = [
            "/usr/bin/rsync",
            "-aE",
            "--partial",
            "--delete-after",
            "--progress",
            "--timeout=120",
            "-e",
            self.rsync_bridge_command(),
        ]
        if self.config.compress:
            command.append("-z")
        if dry_run:
            command.extend(["--dry-run", "--itemize-changes"])
        if safe_links:
            command.append("--safe-links")
        if copy_links:
            command.append("--copy-links")
        for pattern in excludes:
            command.extend(["--exclude", pattern])
        command.extend([source_path, remote])
        return TransferProcess(command)


class TransferProcess:
    def __init__(self, command: Sequence[str]) -> None:
        self.command = list(command)
        self.process: Optional[subprocess.Popen] = None
        self._cancel_requested = False
        self._lock = threading.Lock()

    def start(self, on_output: Optional[OutputCallback] = None) -> None:
        with self._lock:
            if self._cancel_requested:
                raise TransportError("transfer cancelled before start")
            self.process = subprocess.Popen(
                self.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
        assert self.process.stdout is not None
        try:
            for line in self.process.stdout:
                if on_output:
                    on_output(line.rstrip())
            return_code = self.process.wait()
        except BaseException:
            _stop_process(self.process)
            raise
        finally:
            self.process.stdout.close()
        if return_code != 0:
            raise TransportError("rsync exited with status %d" % return_code)

    def pause(self) -> None:
        if self.process and self.process.poll() is None:
            os.killpg(os.getpgid(self.process.pid), signal.SIGSTOP)

    def resume(self) -> None:
        if self.process and self.process.poll() is None:
            os.killpg(os.getpgid(self.process.pid), signal.SIGCONT)

    def cancel(self) -> None:
        with self._lock:
            self._cancel_requested = True
            if self.process and self.process.poll() is None:
                _signal_group(self.process, signal.SIGTERM)
                _signal_group(self.process, signal.SIGCONT)
