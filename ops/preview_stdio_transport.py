"""Operator-only protected Preview recovery relay over an owned process pipe.

The VM keeps its own native device Keychain and recovery key. The operator
keeps the Vercel login on the host. No listener, login-cache copy, protection
disablement, self-issued grant, or object-download proxy is involved.
"""
import base64
from contextlib import contextmanager
from email.message import Message
import json
import os
import select
import signal
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import Request

from codex_migrate import vault_hosted_enrollment_client as enrollment
from codex_migrate import vault_hosted_recovery_client as recovery
from vercel_preview_transport import HEADERS, LIMIT, PREVIEW, PreviewOpener, Response

PATHS = frozenset(("/api/hosted-enrollment", "/api/hosted-recovery"))
RESPONSE_HEADERS = frozenset(("content-type", "content-encoding", "content-length"))
FRAME_LIMIT = 2 * LIMIT


def require(value):
    if not value:
        raise ValueError("invalid_recovery_relay")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result)
        result[key] = value
    return result


def decode_body(value):
    require(isinstance(value, str) and len(value) <= (LIMIT + 2) // 3 * 4)
    data = base64.b64decode(value, validate=True)
    require(len(data) <= LIMIT and base64.b64encode(data).decode("ascii") == value)
    return data


def checked_headers(value, allowed):
    require(isinstance(value, dict) and len(value) <= len(allowed))
    seen = set()
    for key, content in value.items():
        require(isinstance(key, str) and key.lower() in allowed and key.lower() not in seen
                and isinstance(content, str) and len(content) <= 8192
                and not any(c in content for c in "\r\n\x00"))
        seen.add(key.lower())
    return value


class Frames:
    """Bound both partial reads and writes; never log raw protocol frames."""

    def __init__(self, reader, writer):
        self.read_fd, self.write_fd = reader.fileno(), writer.fileno()
        self.buffer = bytearray()

    def read(self, timeout):
        deadline = time.monotonic() + timeout
        while b"\n" not in self.buffer:
            remaining = deadline - time.monotonic()
            require(remaining > 0 and select.select([self.read_fd], [], [], remaining)[0])
            block = os.read(self.read_fd, min(4096, FRAME_LIMIT + 1 - len(self.buffer)))
            require(block and len(self.buffer) + len(block) <= FRAME_LIMIT)
            self.buffer.extend(block)
        line, _, rest = self.buffer.partition(b"\n")
        self.buffer = bytearray(rest)
        value = json.loads(line, object_pairs_hook=unique_object)
        require(isinstance(value, dict))
        return value

    def write(self, value, timeout):
        data = json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode() + b"\n"
        require(len(data) <= FRAME_LIMIT)
        deadline = time.monotonic() + timeout
        while data:
            remaining = deadline - time.monotonic()
            require(remaining > 0 and select.select([], [self.write_fd], [], remaining)[1])
            size = os.write(self.write_fd, data[:4096])
            require(size > 0)
            data = data[size:]


class StdioRecoveryOpener:
    def __init__(self, origin, reader, writer):
        require(isinstance(origin, str) and PREVIEW.fullmatch(origin))
        self.origin = origin
        self.frames = Frames(reader, writer)
        self.sequence = 0

    def open(self, request, timeout=30):
        try:
            path = request.full_url[len(self.origin):]
            require(request.full_url == self.origin + path and path in PATHS
                    and request.get_method() == "POST" and isinstance(request.data, bytes)
                    and len(request.data) <= LIMIT
                    and type(timeout) in (int, float) and 0 < timeout <= 120)
            headers = checked_headers(dict(request.header_items()), HEADERS)
            self.sequence += 1
            self.frames.write({"type": "request", "id": self.sequence, "path": path,
                "headers": headers, "body": base64.b64encode(request.data).decode("ascii"),
                "timeout": timeout}, timeout)
            reply = self.frames.read(timeout + 20)
            require(set(reply) == {"type", "id", "status", "headers", "body"}
                    and reply["type"] == "response" and type(reply["id"]) is int
                    and reply["id"] == self.sequence and type(reply["status"]) is int
                    and 100 <= reply["status"] <= 599)
            fields = Message()
            for key, value in checked_headers(reply["headers"], RESPONSE_HEADERS).items():
                fields[key] = value
            return Response(decode_body(reply["body"]), reply["status"], fields)
        except (OSError, ValueError, TypeError, KeyError):
            raise URLError("Protected recovery relay could not be verified.") from None


@contextmanager
def stdio_recovery(origin):
    """Select explicitly in the VM; R2 still uses native HTTPS and real grants."""
    opener = StdioRecoveryOpener(origin, sys.stdin.buffer, sys.stdout.buffer)
    modules = (enrollment, recovery)
    previous = [module.build_opener for module in modules]
    try:
        for module in modules:
            module.build_opener = lambda *args: opener
        yield
    finally:
        for module, original in zip(modules, previous):
            module.build_opener = original


def relay_request(opener, value, expected_sequence):
    """Host revalidates the frame before using its already-authorized CLI."""
    require(set(value) == {"type", "id", "path", "headers", "body", "timeout"}
            and value["type"] == "request" and type(value["id"]) is int
            and value["id"] == expected_sequence and value["path"] in PATHS
            and type(value["timeout"]) in (int, float) and 0 < value["timeout"] <= 120)
    headers = checked_headers(value["headers"], HEADERS)
    request = Request(opener.origin + value["path"], data=decode_body(value["body"]),
                      headers=headers, method="POST")
    with opener.open(request, timeout=value["timeout"]) as response:
        data = response.read(LIMIT + 1)
        require(len(data) <= LIMIT and type(response.status) is int
                and 100 <= response.status <= 599)
        fields = {key: val for key, val in response.headers.items()
                  if key.lower() in RESPONSE_HEADERS}
        checked_headers(fields, RESPONSE_HEADERS)
        return {"type": "response", "id": expected_sequence, "status": response.status,
                "headers": fields, "body": base64.b64encode(data).decode("ascii")}


def signal_owned_group(process, value):
    try:
        os.killpg(process.pid, value)
    except ProcessLookupError:
        pass
    except PermissionError:
        # Darwin can report EPERM for an already-exited empty group. Do not
        # mistake that for containment: verify no non-zombie member remains.
        require(process.poll() is not None)
        result = subprocess.run(["/bin/ps", "-e", "-o", "pgid=,stat="],
                                capture_output=True, timeout=2)
        require(result.returncode == 0 and len(result.stdout) <= 256 * 1024)
        for line in result.stdout.splitlines():
            group, state = line.split()
            require(int(group) != process.pid or state.startswith(b"Z"))


def relay_process(command, origin, working_directory, *, max_seconds=900, max_requests=300,
                  environment=None):
    """Host-owned Tart exec command only; argv must contain no credential.

    The caller fixes the command and checks the VM identity. There is no shell,
    remote listener or upload route. Guest diagnostics never enter host output.
    The final signal is only a harness result, not release certification.
    """
    require(isinstance(command, list) and command and all(isinstance(v, str) for v in command)
            and type(max_seconds) is int and 0 < max_seconds <= 900
            and type(max_requests) is int and 0 < max_requests <= 300
            and (environment is None or (isinstance(environment, dict)
                 and all(isinstance(k, str) and isinstance(v, str)
                         for k, v in environment.items()))))
    opener = PreviewOpener(origin, working_directory)
    process = None
    try:
        with open(os.devnull, "wb") as errors:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=errors, start_new_session=True, env=environment)
            frames = Frames(process.stdout, process.stdin)
            deadline = time.monotonic() + max_seconds
            sequence = 1
            while True:
                remaining = deadline - time.monotonic()
                require(remaining > 0)
                value = frames.read(min(140, remaining))
                if value.get("type") == "result":
                    require(set(value) == {"type", "passed", "action"}
                            and type(value["passed"]) is bool and value["action"] == "recover"
                            and not frames.buffer)
                    process.stdin.close()
                    require(process.wait(timeout=min(10, remaining)) == (0 if value["passed"] else 1))
                    remaining = deadline - time.monotonic()
                    require(remaining > 0 and select.select([frames.read_fd], [], [],
                                                           min(2, remaining))[0])
                    require(not os.read(frames.read_fd, 1))
                    return {"passed": value["passed"], "action": "recover",
                            "relayed_api_requests": sequence - 1,
                            "complete_release_acceptance": False}
                require(sequence <= max_requests)
                frames.write(relay_request(opener, value, sequence), min(20, remaining))
                sequence += 1
    except (OSError, ValueError, TypeError, KeyError, URLError, subprocess.SubprocessError):
        raise ValueError("protected_recovery_relay_failed") from None
    finally:
        if process is not None:
            # The owned group can outlive its leader. Never use leader liveness
            # as proof that inherited pipe holders or descendants are gone.
            signal_owned_group(process, signal.SIGTERM)
            if process.poll() is None:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
            signal_owned_group(process, signal.SIGKILL)
            process.wait(timeout=5)
            for stream in (process.stdin, process.stdout):
                if stream is not None and not stream.closed:
                    stream.close()
