"""Narrow HTTP transport for encrypted hosted Vault objects.

The caller supplies short-lived, object-specific grants from an authenticated
service. This transport cannot sign grants, publish snapshots, or access R2
credentials. It is deliberately not wired to the customer UI until that
service and the hosted release gates exist.
"""

from __future__ import annotations

import hashlib
import io
import re
from typing import BinaryIO, Callable, Mapping, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from codex_migrate.errors import MigrationError


_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
_OBJECT = (rf"(?:metadata/{_UUID}\.json|objects/[0-9a-f]{{2}}/"
           rf"[0-9a-f]{{62}}\.cvchunk|manifests/{_UUID}\.cvmanifest|"
           rf"refs/{_UUID}\.json)")
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\Z")
_MAX_OBJECT_BYTES = 100 * 1000 * 1000


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


class CapabilityHttpStore:
    """Use a pinned Worker origin and grants scoped to exact expected objects.

    ``grant(method, key, bytes, sha256)`` must authenticate the customer and
    derive ownership, entitlement and object facts server-side. For GET it
    must grant only an object in a published snapshot. The mapping is a client
    safety boundary, not authority for the grant issuer.
    """

    def __init__(self, origin: str, account_id: str, vault_id: str,
                 expected: Mapping[str, Tuple[int, str]],
                 grant: Callable[[str, str, int, str], str], *,
                 timeout: float = 30.0, allow_loopback_http: bool = False):
        if not isinstance(origin, str):
            raise MigrationError("The hosted object service origin is invalid.")
        try:
            parsed = urlsplit(origin)
            parsed.port
        except ValueError:
            raise MigrationError("The hosted object service origin is invalid.") from None
        if (parsed.username or parsed.password
                or parsed.path or parsed.query or parsed.fragment
                or not parsed.hostname or parsed.hostname.endswith(".")
                or parsed.scheme not in ("https", "http")
                or (parsed.scheme == "http" and not (allow_loopback_http
                     and parsed.hostname in ("127.0.0.1", "::1")))):
            raise MigrationError("The hosted object service origin is invalid.")
        if not isinstance(timeout, (int, float)) or not 0 < timeout <= 120:
            raise MigrationError("The hosted object timeout is invalid.")
        if not callable(grant) or not isinstance(expected, Mapping):
            raise MigrationError("The hosted object grants are unavailable.")
        prefix = f"accounts/{account_id}/vaults/{vault_id}/"
        if (not re.fullmatch(_UUID, account_id)
                or not re.fullmatch(_UUID, vault_id) or not expected):
            raise MigrationError("The hosted Vault scope is invalid.")
        checked = {}
        for key, value in expected.items():
            if (not isinstance(key, str) or not re.fullmatch(_OBJECT, key)
                    or not isinstance(value, tuple) or len(value) != 2
                    or type(value[0]) is not int or not 0 < value[0] <= _MAX_OBJECT_BYTES
                    or not isinstance(value[1], str) or not _HEX.fullmatch(value[1])):
                raise MigrationError("The hosted Vault object inventory is invalid.")
            checked[key] = value
        self._origin = origin.rstrip("/")
        self._prefix = prefix
        self._expected = checked
        self._grant = grant
        self._timeout = timeout
        self._opener = build_opener(_NoRedirect())

    def _request(self, method: str, key: str, body: Optional[BinaryIO] = None):
        try:
            size, digest = self._expected[key]
        except KeyError:
            raise MigrationError("The hosted object is outside the selected Vault.") from None
        scoped_key = self._prefix + key
        try:
            token = self._grant(method, scoped_key, size, digest)
        except Exception:
            raise MigrationError("The hosted object grant is unavailable.") from None
        if not isinstance(token, str) or not _TOKEN.fullmatch(token) or len(token) > 2048:
            raise MigrationError("The hosted object grant is invalid.")
        headers = {"Authorization": "Bearer " + token}
        if method == "PUT":
            headers["Content-Length"] = str(size)
            headers["Content-Type"] = "application/octet-stream"
        request = Request(self._origin + "/v1/object/" + scoped_key,
                          data=body, headers=headers, method=method)
        try:
            return self._opener.open(request, timeout=self._timeout)
        except HTTPError as error:
            # A valid HEAD grant has exactly three outcomes: verified, absent,
            # or conflicting. A mismatch must never be mistaken for absence.
            if method == "HEAD" and error.code == 404:
                error.close()
                return None
            error.close()
            raise MigrationError("The hosted object request was refused or could not be verified.") from None
        except (URLError, OSError, ValueError):
            # Do not put a signed URL, bearer token, customer path or response
            # body into a diagnostic from the underlying HTTP library.
            raise MigrationError("The hosted object service is unavailable.") from None

    def checked_metadata(self, key: str) -> Optional[Tuple[int, str]]:
        response = self._request("HEAD", key)
        if response is None:
            return None
        with response:
            if response.status != 200:
                raise MigrationError("The hosted object was not verified.")
        return self._expected[key]

    def put_if_absent(self, key: str, source: BinaryIO, length: int) -> None:
        expected = self._expected.get(key)
        if expected is None or type(length) is not int or length != expected[0]:
            raise MigrationError("The hosted upload does not match its inventory.")
        # The staging engine gives us an authenticated, frozen BytesIO. Check
        # it once more before granting a network send, without another 100 MB
        # allocation or advancing the stream; its consumed-byte check remains
        # meaningful after the HTTP request.
        if not isinstance(source, io.BytesIO) or source.tell() != 0:
            raise MigrationError("The hosted upload source is not frozen.")
        view = source.getbuffer()
        try:
            if len(view) != length or hashlib.sha256(view).hexdigest() != expected[1]:
                raise MigrationError("The hosted upload source changed.")
        finally:
            view.release()
        with self._request("PUT", key, source) as response:
            if response.status not in (200, 201):
                raise MigrationError("The hosted object upload was not verified.")
        if source.tell() != length:
            raise MigrationError("The hosted object upload was incomplete.")

    def open_read(self, key: str) -> Optional[BinaryIO]:
        response = self._request("GET", key)
        if response is None:
            return None
        if response.status != 200:
            response.close()
            raise MigrationError("The hosted object could not be verified.")
        size, _ = self._expected[key]
        if (response.headers.get("Content-Length") != str(size)
                or response.headers.get("Content-Encoding", "identity") != "identity"):
            response.close()
            raise MigrationError("The hosted object response has unexpected metadata.")
        return response
