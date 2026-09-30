"""Dark business worker pairing with a separate device-only Keychain secret.

An administrator's approved seat and the worker's emailed code are needed to
claim the first device. This is not company recovery authorization: a lost
employee Mac still needs a separately governed replacement-device path.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from codex_migrate.errors import MigrationError
from codex_migrate.vault_backup import _helper_path, _run_helper
from codex_migrate.vault_hosted_recovery_client import HostedRecoveryClient, _origin
from codex_migrate.vault_hosted_upload_client import HostedUploadClient
from codex_migrate.vault_http_store import _NoRedirect


_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")
_CODE = re.compile(r"hvwe1_[A-Za-z0-9_-]{43}\Z")
_TOKEN = re.compile(r"hvb1_[A-Za-z0-9_-]{43}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_DOMAIN = b"codex-backup-business-device-v1\0"


def _identity(value: object, account_id: str, seat_id: str,
              vault_id: str, device_id: str) -> dict:
    if (not isinstance(value, dict) or
            set(value) != {"accountId", "seatId", "vaultId", "deviceId"} or
            value != {"accountId": account_id, "seatId": seat_id,
                      "vaultId": vault_id, "deviceId": device_id}):
        raise MigrationError("The business device identity changed.")
    return value


class BusinessHostedEnrollmentClient:
    """Pair a worker device without accepting an individual purchase token."""

    def __init__(self, service_origin: str, *, timeout: float = 30.0,
                 allow_loopback_http: bool = False):
        self._origin = _origin(service_origin, allow_loopback_http)
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or
                not 0 < timeout <= 120):
            raise MigrationError("The business enrollment timeout is invalid.")
        self._timeout = timeout
        self._allow_loopback_http = allow_loopback_http
        self._opener = build_opener(_NoRedirect())

    def _post(self, claim: dict, token: str = "") -> dict:
        body = json.dumps(claim, separators=(",", ":")).encode("utf-8")
        if len(body) > 512 or (token and not _TOKEN.fullmatch(token)):
            raise MigrationError("The business enrollment request is invalid.")
        headers = {"Content-Type": "application/json",
                   "Content-Length": str(len(body))}
        if token:
            headers["Authorization"] = "Bearer " + token
        request = Request(self._origin + "/api/hosted-business-device",
                          data=body, headers=headers, method="POST")
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                if (response.status != 200 or
                        response.headers.get("Content-Encoding", "identity") !=
                        "identity" or
                        response.headers.get("Content-Type", "").split(";")[0] !=
                        "application/json"):
                    raise MigrationError("The business enrollment response is invalid.")
                data = response.read(2049)
                if len(data) > 2048:
                    raise MigrationError("The business enrollment response is too large.")
        except (HTTPError, URLError, OSError, ValueError):
            raise MigrationError("Business enrollment could not be confirmed.") from None
        try:
            value = json.loads(data)
        except (UnicodeError, ValueError):
            raise MigrationError("The business enrollment response is invalid.") from None
        if not isinstance(value, dict):
            raise MigrationError("The business enrollment response is invalid.")
        return value

    def create_device(self, *, crypto_helper: Optional[str] = None,
                      apply: bool = False) -> str:
        if apply is not True:
            raise MigrationError("Business device creation requires confirmation.")
        created = _run_helper(_helper_path(crypto_helper),
                              ["hosted-business-device-create"])
        device_id = created.get("device_id")
        if (set(created) != {"device_id", "token_hash"} or
                not isinstance(device_id, str) or not _UUID.fullmatch(device_id) or
                not isinstance(created.get("token_hash"), str) or
                not _HASH.fullmatch(created["token_hash"])):
            raise MigrationError("The business device credential is invalid.")
        return device_id

    @staticmethod
    def _credential(device_id: str, crypto_helper: Optional[str]) -> tuple:
        if not isinstance(device_id, str) or not _UUID.fullmatch(device_id):
            raise MigrationError("The business device identifier is invalid.")
        value = _run_helper(_helper_path(crypto_helper),
                            ["hosted-business-device-read", "--device-id", device_id])
        token = value.get("token")
        digest = value.get("token_hash")
        if (set(value) != {"device_id", "token_hash", "token"} or
                value.get("device_id") != device_id or
                not isinstance(token, str) or not _TOKEN.fullmatch(token) or
                not isinstance(digest, str) or not _HASH.fullmatch(digest) or
                hashlib.sha256(_DOMAIN + token.encode("ascii")).hexdigest() != digest):
            raise MigrationError("The business device credential is invalid.")
        return token, digest

    def claim(self, account_id: str, seat_id: str, vault_id: str,
              code: str, device_id: str, *,
              crypto_helper: Optional[str] = None, apply: bool = False) -> dict:
        if (apply is not True or any(not isinstance(value, str) or
                not _UUID.fullmatch(value) for value in
                (account_id, seat_id, vault_id, device_id)) or
                not isinstance(code, str) or not _CODE.fullmatch(code)):
            raise MigrationError("The business device claim is invalid.")
        _, digest = self._credential(device_id, crypto_helper)
        # A timeout may mean the one-use code already committed. Resolve this
        # exact saved device instead of minting a second secret.
        value = self._post({"action": "claim", "accountId": account_id,
                            "seatId": seat_id, "vaultId": vault_id,
                            "code": code, "deviceId": device_id,
                            "deviceTokenHash": digest})
        return _identity(value, account_id, seat_id, vault_id, device_id)

    def resolve(self, device_id: str, *, crypto_helper: Optional[str] = None) -> dict:
        token, _ = self._credential(device_id, crypto_helper)
        return self._resolve_with_token(device_id, token)

    def _resolve_with_token(self, device_id: str, token: str) -> dict:
        value = self._post({"action": "resolve", "deviceId": device_id}, token)
        if (not isinstance(value, dict) or
                set(value) != {"accountId", "seatId", "vaultId", "deviceId"} or
                value.get("deviceId") != device_id or
                any(not isinstance(value.get(name), str) or
                    not _UUID.fullmatch(value[name]) for name in
                    ("accountId", "seatId", "vaultId"))):
            raise MigrationError("The business device identity changed.")
        return value

    def backup_clients(self, device_id: str, *,
                       crypto_helper: Optional[str] = None) -> tuple:
        token, _ = self._credential(device_id, crypto_helper)
        identity = self._resolve_with_token(device_id, token)
        recovery = HostedRecoveryClient(
            self._origin, token, identity["vaultId"], timeout=self._timeout,
            allow_loopback_http=self._allow_loopback_http)
        account_id, worker_origin, _ = recovery._latest()
        if account_id != identity["accountId"]:
            raise MigrationError("The business backup account changed.")
        upload = HostedUploadClient(
            self._origin, worker_origin, token, account_id,
            identity["vaultId"], timeout=self._timeout,
            allow_loopback_http=self._allow_loopback_http)
        return upload, recovery
