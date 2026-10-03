"""Operator-only API transport for an authenticated, protected test Preview.

Use the supported Vercel CLI session, not a copied login cache, self-issued
object capability, or shipping protection bypass. Secrets travel on stdin.
R2 transfers retain their normal HTTPS transport and server-issued grants.
"""
from contextlib import contextmanager
from email.parser import BytesParser
import io
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.error import URLError

from codex_migrate import vault_hosted_enrollment_client as enrollment
from codex_migrate import vault_hosted_recovery_client as recovery
from codex_migrate import vault_hosted_upload_client as upload

PREVIEW = re.compile(
    r"https://codex-migrate-[a-z0-9]+-joshuas-projects-d3a5c48d\.vercel\.app\Z")
PATHS = frozenset("/api/" + name for name in (
    "hosted-enrollment", "hosted-recovery", "hosted-upload",
    "hosted-receipt-page", "hosted-publish", "hosted-verify-step",
    "hosted-publish-checkpointed", "hosted-published-chunks"))
HEADERS = frozenset(("authorization", "content-type", "content-length",
                     "x-hosted-upload-lease"))
LIMIT = 256 * 1024
CLI = "/Users/jsegeren/.local/bin/vercel"
CLI_ENVIRONMENT = {
    "HOME": "/Users/jsegeren",
    "PATH": "/Users/jsegeren/.nvm/versions/node/v24.19.0/bin:/usr/bin:/bin",
    "LANG": "en_US.UTF-8",
    "LC_ALL": "en_US.UTF-8",
}


def quoted(value):
    if not isinstance(value, str) or any(c in value for c in "\r\n\x00"):
        raise ValueError("invalid_preview_request")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


class Response(io.BytesIO):
    def __init__(self, body, status, headers):
        super().__init__(body)
        self.status = status
        self.headers = headers


class PreviewOpener:
    def __init__(self, origin, working_directory):
        if not PREVIEW.fullmatch(origin):
            raise ValueError("invalid_preview_origin")
        self.origin = origin
        self.cwd = str(Path(working_directory).resolve(strict=True))
        if not (Path(self.cwd) / ".vercel/project.json").is_file():
            raise ValueError("unlinked_preview_workspace")

    def open(self, request, timeout=30):
        """Preserve real status/headers; no diagnostic can disclose a bearer."""
        try:
            path = request.full_url[len(self.origin):]
            if (request.full_url != self.origin + path or path not in PATHS
                    or request.get_method() != "POST"
                    or not isinstance(request.data, bytes)
                    or len(request.data) > LIMIT
                    or not 0 < timeout <= 120):
                raise ValueError("invalid_preview_request")
            config = ['silent', 'show-error', 'request = "POST"',
                      'proto = "=https"', 'max-redirs = 0',
                      'max-time = ' + str(timeout),
                      'max-filesize = ' + str(LIMIT + 1)]
            for key, value in request.header_items():
                if key.lower() not in HEADERS:
                    raise ValueError("invalid_preview_header")
                config.append("header = " + quoted(key + ": " + value))
            config.append("data-binary = " + quoted(request.data.decode("ascii")))
            with tempfile.TemporaryDirectory(prefix="codex-preview-http-") as temporary:
                # Vercel prepends URL/protection options, so forwarding -q
                # would not make it curl's first argument. An existing empty
                # first-choice startup file prevents fallback to HOME/.curlrc.
                (Path(temporary) / ".curlrc").touch(mode=0o600, exist_ok=False)
                environment = {**CLI_ENVIRONMENT, "CURL_HOME": temporary}
                headers_path = Path(temporary) / "headers"
                config.append("dump-header = " + quoted(str(headers_path)))
                # File-backed capture bounds memory and keeps CLI diagnostics
                # out of terminal output, even on a provider/auth failure.
                with tempfile.TemporaryFile() as body, tempfile.TemporaryFile() as errors:
                    result = subprocess.run([
                        CLI, "curl", path, "--deployment", self.origin,
                        "--", "--config", "-"], cwd=self.cwd,
                        # Do not inherit CLI rerouting, alternate auth, Node
                        # injection, proxy, or governance overrides. The fixed
                        # guard and existing operator login remain authority.
                        env=environment,
                        input=("\n".join(config) + "\n").encode("ascii"),
                        stdout=body, stderr=errors, timeout=timeout + 15)
                    body.seek(0)
                    content = body.read(LIMIT + 1)
                if result.returncode != 0 or len(content) > LIMIT:
                    raise ValueError("preview_request_failed")
                with headers_path.open("rb") as stream:
                    raw = stream.read(16385)
                if len(raw) > 16384:
                    raise ValueError("preview_headers_too_large")
                # curl may include proxy CONNECT / interim status blocks.
                blocks = [b for b in raw.split(b"\r\n\r\n") if b.startswith(b"HTTP/")]
                status_line, fields = blocks[-1].split(b"\r\n", 1)
                status = int(status_line.split()[1])
                if not 100 <= status <= 599:
                    raise ValueError("invalid_preview_response")
                return Response(content, status, BytesParser().parsebytes(fields + b"\r\n"))
        except (OSError, ValueError, IndexError, subprocess.SubprocessError):
            raise URLError("Protected Preview request could not be verified.") from None


@contextmanager
def protected_preview(origin, working_directory):
    """Single-threaded operator process only; never changes shipping clients."""
    opener = PreviewOpener(origin, working_directory)
    modules = (enrollment, recovery, upload)
    previous = [module.build_opener for module in modules]
    try:
        for module in modules:
            module.build_opener = lambda *args: opener
        yield
    finally:
        for module, original in zip(modules, previous):
            module.build_opener = original
