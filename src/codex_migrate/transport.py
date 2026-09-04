"""Strict SSH and rsync transport without shell-built local commands."""

from __future__ import annotations

import os
from pathlib import Path
import shlex
import signal
import socket
import subprocess
import threading
import time
from typing import Callable, List, Optional, Sequence, Tuple

from codex_migrate.config import MigrationConfig


OutputCallback = Callable[[str], None]


class TransportError(RuntimeError):
    pass


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

    def ssh_base(self) -> List[str]:
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
        if options.identity_file:
            args.extend(["-i", options.identity_file])
        if options.known_hosts_file:
            args.extend(["-o", "UserKnownHostsFile=%s" % options.known_hosts_file])
        if options.host_key_alias:
            args.extend(["-o", "HostKeyAlias=%s" % options.host_key_alias])
        return args

    def ssh_transport_string(self) -> str:
        return " ".join(shlex.quote(item) for item in self.ssh_base())

    def run_remote(self, script: str, timeout: int = 60) -> subprocess.CompletedProcess:
        command = self.ssh_base() + [self.config.target, "/bin/zsh -s"]
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        with self._remote_lock:
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
            message = result.stderr.strip() or result.stdout.strip() or "remote command failed"
            raise TransportError(message)
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

    def route(self) -> str:
        host = self.config.target.rsplit("@", 1)[1].strip("[]")
        try:
            address = socket.gethostbyname(host)
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
            if address.startswith("169.254."):
                return "Direct link (%s → %s)" % (interface, address)
            if interface == "en0":
                return "Wi-Fi (%s)" % address
            return "%s (%s)" % (interface, address)
        except (OSError, socket.error, subprocess.SubprocessError):
            return "SSH (%s)" % host

    def benchmark(self, megabytes: int = 16) -> float:
        started = time.monotonic()
        producer = subprocess.Popen(
            ["/bin/dd", "if=/dev/zero", "bs=1048576", "count=%d" % megabytes],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        consumer = subprocess.Popen(
            self.ssh_base() + [self.config.target, "/bin/cat >/dev/null"],
            stdin=producer.stdout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        assert producer.stdout is not None
        producer.stdout.close()
        _, error = consumer.communicate(timeout=60)
        producer.wait(timeout=10)
        if consumer.returncode != 0 or producer.returncode != 0:
            raise TransportError(error.decode("utf-8", "replace").strip())
        elapsed = max(0.001, time.monotonic() - started)
        return (megabytes * 8.0) / elapsed

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
        remote = "%s:%s" % (self.config.target, shlex.quote(destination.rstrip("/") + "/"))
        command = [
            "/usr/bin/rsync",
            "-aE",
            "--partial",
            "--delete-after",
            "--progress",
            "--timeout=120",
            "-e",
            self.ssh_transport_string(),
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
