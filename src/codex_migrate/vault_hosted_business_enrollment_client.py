"""Dark business worker pairing with a separate device-only Keychain secret.

An administrator's approved seat and the worker's emailed code are needed to
claim the first device. A separate, dark administrator-approved path pairs a
short-lived read-only replacement device; it is not a customer recovery flow.
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
_ADMIN_TOKEN = re.compile(r"hva1_[A-Za-z0-9_-]{43}\Z")
_RECOVERY_CODE = re.compile(r"hvcr1_[A-Za-z0-9_-]{43}\Z")
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

    def _post(self, claim: dict, token: str = "", *,
              recovery: bool = False, admin: bool = False) -> dict:
        body = json.dumps(claim, separators=(",", ":")).encode("utf-8")
        if (len(body) > (768 if recovery else 512) or
                (admin and (not recovery or claim.get("action") != "begin")) or
                (token and not (_ADMIN_TOKEN if admin else _TOKEN).fullmatch(token))):
            raise MigrationError("The business enrollment request is invalid.")
        headers = {"Content-Type": "application/json",
                   "Content-Length": str(len(body))}
        if token:
            headers["Authorization"] = "Bearer " + token
        endpoint = ("/api/hosted-business-recovery-device" if recovery else
                    "/api/hosted-business-device")
        request = Request(self._origin + endpoint,
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

    def begin_recovery(self, account_id: str, seat_id: str, vault_id: str,
                       purpose: str, admin_session_token: str, *,
                       apply: bool = False) -> str:
        if (apply is not True or any(not isinstance(value, str) or
                not _UUID.fullmatch(value) for value in
                (account_id, seat_id, vault_id)) or
                not isinstance(purpose, str) or
                not 12 <= len(purpose) <= 250 or purpose != purpose.strip() or
                any(ord(char) < 32 or ord(char) == 127 for char in purpose) or
                not isinstance(admin_session_token, str) or
                not _ADMIN_TOKEN.fullmatch(admin_session_token)):
            raise MigrationError("The company recovery request is invalid.")
        value = self._post({"action": "begin", "accountId": account_id,
                            "seatId": seat_id, "vaultId": vault_id,
                            "purpose": purpose}, admin_session_token,
                           recovery=True, admin=True)
        request_id = value.get("requestId")
        if (set(value) != {"requestId", "status"} or
                value.get("status") != "sent" or
                not isinstance(request_id, str) or
                not _UUID.fullmatch(request_id)):
            raise MigrationError("The company recovery request is invalid.")
        return request_id

    def claim_recovery(self, account_id: str, seat_id: str, vault_id: str,
                       request_id: str, code: str, device_id: str, *,
                       crypto_helper: Optional[str] = None,
                       apply: bool = False) -> dict:
        if (apply is not True or any(not isinstance(value, str) or
                not _UUID.fullmatch(value) for value in
                (account_id, seat_id, vault_id, request_id, device_id)) or
                not isinstance(code, str) or not _RECOVERY_CODE.fullmatch(code)):
            raise MigrationError("The company recovery claim is invalid.")
        _, digest = self._credential(device_id, crypto_helper)
        value = self._post({"action": "claim", "accountId": account_id,
                            "seatId": seat_id, "vaultId": vault_id,
                            "requestId": request_id, "code": code,
                            "deviceId": device_id, "deviceTokenHash": digest},
                           recovery=True)
        return _identity(value, account_id, seat_id, vault_id, device_id)

    def resolve(self, device_id: str, *, crypto_helper: Optional[str] = None) -> dict:
        token, _ = self._credential(device_id, crypto_helper)
        return self._resolve_with_token(device_id, token)

    def rotate_device(self, old_device_id: str, new_device_id: str,
                      expected_account_id: str, expected_seat_id: str,
                      expected_vault_id: str, *,
                      crypto_helper: Optional[str] = None,
                      apply: bool = False) -> dict:
        """Replace an active worker bearer; reconcile lost replies by new ID.

        The caller saves the new Keychain credential and its ID first. Never
        replay an ambiguous rotation or delete either credential here.
        """
        if (apply is not True or any(not isinstance(value, str) or
                not _UUID.fullmatch(value) for value in
                (old_device_id, new_device_id, expected_account_id,
                 expected_seat_id, expected_vault_id)) or
                old_device_id == new_device_id):
            raise MigrationError("The business device rotation is invalid.")
        new_token, new_digest = self._credential(new_device_id, crypto_helper)
        def matching(value: dict) -> dict:
            if "accessPurpose" in value:
                if value["accessPurpose"] != "worker":
                    raise MigrationError("A recovery-only device cannot rotate as a worker.")
                value = {key: val for key, val in value.items()
                         if key != "accessPurpose"}
            return _identity(value, expected_account_id, expected_seat_id,
                             expected_vault_id, new_device_id)

        try:
            return matching(self._resolve_with_token(new_device_id, new_token))
        except MigrationError:
            pass
        old_token, _ = self._credential(old_device_id, crypto_helper)
        old_identity = self._resolve_with_token(old_device_id, old_token)
        if old_identity["accessPurpose"] != "worker":
            raise MigrationError("A recovery-only device cannot rotate as a worker.")
        _identity({key: val for key, val in old_identity.items()
                   if key != "accessPurpose"},
                  expected_account_id, expected_seat_id,
                  expected_vault_id, old_device_id)
        try:
            return matching(self._post({"action": "rotate",
                "oldDeviceId": old_device_id, "newDeviceId": new_device_id,
                "newDeviceTokenHash": new_digest}, old_token))
        except MigrationError:
            try:
                return matching(self._resolve_with_token(new_device_id,
                                                         new_token))
            except MigrationError:
                raise MigrationError(
                    "Business device rotation could not be confirmed.") from None

    def _resolve_with_token(self, device_id: str, token: str) -> dict:
        value = self._post({"action": "resolve", "deviceId": device_id}, token)
        if (not isinstance(value, dict) or
                set(value) != {"accountId", "seatId", "vaultId", "deviceId",
                               "accessPurpose"} or
                value.get("deviceId") != device_id or
                value.get("accessPurpose") not in ("worker", "recovery") or
                any(not isinstance(value.get(name), str) or
                    not _UUID.fullmatch(value[name]) for name in
                    ("accountId", "seatId", "vaultId"))):
            raise MigrationError("The business device identity changed.")
        return value

    def backup_clients(self, device_id: str, *,
                       crypto_helper: Optional[str] = None) -> tuple:
        token, _ = self._credential(device_id, crypto_helper)
        identity = self._resolve_with_token(device_id, token)
        if identity["accessPurpose"] != "worker":
            raise MigrationError("A recovery-only device cannot run backups.")
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

    def recovery_client(self, device_id: str, *,
                        crypto_helper: Optional[str] = None) -> HostedRecoveryClient:
        token, _ = self._credential(device_id, crypto_helper)
        identity = self._resolve_with_token(device_id, token)
        recovery = HostedRecoveryClient(
            self._origin, token, identity["vaultId"], timeout=self._timeout,
            allow_loopback_http=self._allow_loopback_http)
        account_id, _, _ = recovery._latest()
        if account_id != identity["accountId"]:
            raise MigrationError("The business recovery account changed.")
        return recovery
