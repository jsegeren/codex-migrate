"""Sandbox enrollment client; never expose the device bearer to browser JS.

The native helper saves a new device token in Keychain before a server claim.
If a claim response is lost, keep that token: resolve the same device instead
of minting a second identity. This is not wired to the buyer UI or live host.
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
from codex_migrate.vault_hosted_recovery_client import HostedRecoveryClient
from codex_migrate.vault_hosted_recovery_client import _origin
from codex_migrate.vault_hosted_upload_client import HostedUploadClient
from codex_migrate.vault_http_store import _NoRedirect


_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
_PURCHASE = re.compile(r"cs_(?:test|live)_[A-Za-z0-9]+\.[0-9a-f]{64}\Z")
_CODE = re.compile(r"hve1_[A-Za-z0-9_-]{43}\Z")
_TOKEN = re.compile(r"hv1_[A-Za-z0-9_-]{43}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_MAX_REQUEST = 700
_MAX_RESPONSE = 2048
_MAX_VAULT_LIST_RESPONSE = 12 * 1024


def _require_apply(apply: bool) -> None:
    if apply is not True:
        raise MigrationError("Hosted enrollment changes require explicit confirmation.")


def _identity(value: object, device_id: str) -> dict:
    if (not isinstance(value, dict) or
            set(value) != {"accountId", "vaultId", "deviceId"} or
            value.get("deviceId") != device_id or
            not isinstance(value.get("accountId"), str) or
            not re.fullmatch(_UUID, value["accountId"]) or
            not isinstance(value.get("vaultId"), str) or
            not re.fullmatch(_UUID, value["vaultId"])):
        raise MigrationError("The hosted enrollment response is invalid.")
    return value


class HostedEnrollmentClient:
    """Use a pinned first-party origin; server writes remain sandbox-only."""

    def __init__(self, service_origin: str, *, timeout: float = 30.0,
                 allow_loopback_http: bool = False):
        self._origin = _origin(service_origin, allow_loopback_http)
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or
                not 0 < timeout <= 120):
            raise MigrationError("The hosted enrollment timeout is invalid.")
        self._timeout = timeout
        self._allow_loopback_http = allow_loopback_http
        self._opener = build_opener(_NoRedirect())

    def _post(self, claim: dict, token: str = "", *,
              max_response: int = _MAX_RESPONSE) -> dict:
        body = json.dumps(claim, separators=(",", ":")).encode("utf-8")
        if len(body) > _MAX_REQUEST or (token and not _TOKEN.fullmatch(token)):
            raise MigrationError("The hosted enrollment request is invalid.")
        headers = {"Content-Type": "application/json",
                   "Content-Length": str(len(body))}
        if token:
            headers["Authorization"] = "Bearer " + token
        request = Request(self._origin + "/api/hosted-enrollment", data=body,
                          headers=headers, method="POST")
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                if (response.status != 200 or
                        response.headers.get("Content-Encoding", "identity") != "identity" or
                        response.headers.get("Content-Type", "").split(";")[0] !=
                        "application/json"):
                    raise MigrationError("The hosted enrollment response is invalid.")
                data = response.read(max_response + 1)
                if len(data) > max_response:
                    raise MigrationError("The hosted enrollment response is too large.")
        except (HTTPError, URLError, OSError, ValueError):
            # The exception must not disclose the purchase link, emailed code,
            # device bearer, server body, or provider diagnostics.
            raise MigrationError("Hosted enrollment could not be confirmed.") from None
        try:
            result = json.loads(data)
        except (UnicodeError, ValueError):
            raise MigrationError("The hosted enrollment response is invalid.") from None
        if not isinstance(result, dict):
            raise MigrationError("The hosted enrollment response is invalid.")
        return result

    def begin(self, purchase_token: str, *, apply: bool = False) -> None:
        _require_apply(apply)
        if not isinstance(purchase_token, str) or not _PURCHASE.fullmatch(purchase_token):
            raise MigrationError("The purchase link is invalid for hosted enrollment.")
        if self._post({"action": "begin", "purchaseToken": purchase_token}) != {"status": "sent"}:
            raise MigrationError("The hosted enrollment response is invalid.")

    def create_device(self, *, crypto_helper: Optional[str] = None,
                      apply: bool = False) -> str:
        """Persist a bearer in Keychain; return only its nonsecret device ID."""
        _require_apply(apply)
        created = _run_helper(_helper_path(crypto_helper), ["hosted-device-create"])
        device_id = created.get("device_id")
        if (set(created) != {"device_id", "token_hash"} or
                not isinstance(device_id, str) or not re.fullmatch(_UUID, device_id) or
                not isinstance(created.get("token_hash"), str) or
                not _HASH.fullmatch(created["token_hash"])):
            raise MigrationError("The hosted device credential is invalid.")
        return device_id

    def claim(self, purchase_token: str, code: str, device_id: str, *,
              crypto_helper: Optional[str] = None, apply: bool = False) -> dict:
        _require_apply(apply)
        if (not isinstance(purchase_token, str) or not _PURCHASE.fullmatch(purchase_token)
                or not isinstance(code, str) or not _CODE.fullmatch(code)
                or not isinstance(device_id, str) or not re.fullmatch(_UUID, device_id)):
            raise MigrationError("The hosted enrollment claim is invalid.")
        device_hash = self._device_hash(device_id, crypto_helper)
        # Never delete this Keychain item on a timeout. The server may already
        # have claimed it; resolve(device_id) is the safe ambiguous retry.
        result = self._post({"action": "claim", "purchaseToken": purchase_token,
                             "code": code, "deviceId": device_id,
                             "deviceTokenHash": device_hash})
        return _identity(result, device_id)

    @staticmethod
    def _device_hash(device_id: str, crypto_helper: Optional[str]) -> str:
        listed = _run_helper(_helper_path(crypto_helper), ["hosted-device-list"])
        devices = listed.get("devices")
        if not isinstance(devices, list):
            raise MigrationError("The hosted device credential is unavailable.")
        selected = [item for item in devices if isinstance(item, dict) and
                    item.get("device_id") == device_id]
        if (len(selected) != 1 or set(selected[0]) != {"device_id", "token_hash"} or
                not isinstance(selected[0]["token_hash"], str) or
                not _HASH.fullmatch(selected[0]["token_hash"])):
            raise MigrationError("The hosted device credential is unavailable.")
        return selected[0]["token_hash"]

    def begin_recovery(self, purchase_token: str, *, apply: bool = False) -> None:
        """Email a fresh code for pairing to an already enrolled Vault."""
        _require_apply(apply)
        if not isinstance(purchase_token, str) or not _PURCHASE.fullmatch(purchase_token):
            raise MigrationError("The purchase link is invalid for hosted recovery.")
        if self._post({"action": "begin_recovery",
                       "purchaseToken": purchase_token}) != {"status": "sent"}:
            raise MigrationError("The hosted recovery response is invalid.")

    def list_recovery_vaults(self, purchase_token: str, code: str) -> list:
        """List opaque Vault IDs only after the buyer proves their email."""
        if (not isinstance(purchase_token, str) or not _PURCHASE.fullmatch(purchase_token)
                or not isinstance(code, str) or not _CODE.fullmatch(code)):
            raise MigrationError("The hosted recovery challenge is invalid.")
        result = self._post({"action": "list_recovery_vaults",
                             "purchaseToken": purchase_token, "code": code},
                            max_response=_MAX_VAULT_LIST_RESPONSE)
        vaults = result.get("vaults")
        if (set(result) != {"vaults"} or not isinstance(vaults, list) or
                not 1 <= len(vaults) <= 64):
            raise MigrationError("The hosted recovery Vault list is invalid.")
        seen = set()
        for item in vaults:
            if (not isinstance(item, dict) or
                    set(item) != {"vaultId", "lastGoodAt"} or
                    not isinstance(item["vaultId"], str) or
                    not re.fullmatch(_UUID, item["vaultId"]) or
                    item["vaultId"] in seen or
                    (item["lastGoodAt"] is not None and
                     (not isinstance(item["lastGoodAt"], str) or
                      not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z",
                                       item["lastGoodAt"])))):
                raise MigrationError("The hosted recovery Vault list is invalid.")
            seen.add(item["vaultId"])
        return vaults

    def claim_recovery(self, purchase_token: str, code: str, vault_id: str,
                       device_id: str, *, crypto_helper: Optional[str] = None,
                       apply: bool = False) -> dict:
        """Pair a fresh Keychain device to one owned Vault; never create data."""
        _require_apply(apply)
        if (not isinstance(purchase_token, str) or not _PURCHASE.fullmatch(purchase_token)
                or not isinstance(code, str) or not _CODE.fullmatch(code)
                or not isinstance(vault_id, str) or not re.fullmatch(_UUID, vault_id)
                or not isinstance(device_id, str) or not re.fullmatch(_UUID, device_id)):
            raise MigrationError("The hosted recovery claim is invalid.")
        device_hash = self._device_hash(device_id, crypto_helper)
        result = self._post({"action": "claim_recovery",
                             "purchaseToken": purchase_token, "code": code,
                             "vaultId": vault_id, "deviceId": device_id,
                             "deviceTokenHash": device_hash})
        identity = _identity(result, device_id)
        if identity["vaultId"] != vault_id:
            raise MigrationError("The hosted recovery claim changed the selected Vault.")
        return identity

    def _credential(self, device_id: str, crypto_helper: Optional[str]) -> str:
        """Read and validate the bearer only inside the native client process."""
        if not isinstance(device_id, str) or not re.fullmatch(_UUID, device_id):
            raise MigrationError("The hosted device identifier is invalid.")
        credential = _run_helper(_helper_path(crypto_helper), [
            "hosted-device-read", "--device-id", device_id])
        token = credential.get("token")
        if (set(credential) != {"device_id", "token_hash", "token"} or
                credential.get("device_id") != device_id or
                not isinstance(token, str) or not _TOKEN.fullmatch(token) or
                not isinstance(credential.get("token_hash"), str) or
                not _HASH.fullmatch(credential["token_hash"]) or
                hashlib.sha256(b"codex-vault-hosted-session-v1\0" +
                               token.encode("ascii")).hexdigest() !=
                credential["token_hash"]):
            raise MigrationError("The hosted device credential is invalid.")
        return token

    def _session(self, device_id: str, crypto_helper: Optional[str]) -> tuple:
        token = self._credential(device_id, crypto_helper)
        identity = _identity(
            self._post({"action": "resolve", "deviceId": device_id}, token),
            device_id)
        return token, identity

    def resolve(self, device_id: str, *, crypto_helper: Optional[str] = None) -> dict:
        """Recover an ambiguous claim using the same Keychain-held bearer."""
        return self._session(device_id, crypto_helper)[1]

    def upload_client(self, device_id: str, worker_origin: str, *,
                      crypto_helper: Optional[str] = None) -> HostedUploadClient:
        """Open a dark upload adapter without handing its bearer to browser code."""
        token, identity = self._session(device_id, crypto_helper)
        return HostedUploadClient(
            self._origin, worker_origin, token, identity["accountId"],
            identity["vaultId"], timeout=self._timeout,
            allow_loopback_http=self._allow_loopback_http)

    def recovery_client(self, device_id: str, *,
                        crypto_helper: Optional[str] = None) -> HostedRecoveryClient:
        """Open a dark recovery adapter using only the Keychain-held bearer."""
        token, identity = self._session(device_id, crypto_helper)
        return HostedRecoveryClient(
            self._origin, token, identity["vaultId"], timeout=self._timeout,
            allow_loopback_http=self._allow_loopback_http)

    def backup_clients(self, device_id: str, *,
                       crypto_helper: Optional[str] = None) -> tuple:
        """Bind both adapters to one device and the service's Worker origin.

        An unattended backup must not take its transfer origin from an
        editable schedule file or command line. The authenticated recovery
        pointer supplies it, even when this Vault has no snapshot yet.
        """
        token, identity = self._session(device_id, crypto_helper)
        recovery = HostedRecoveryClient(
            self._origin, token, identity["vaultId"], timeout=self._timeout,
            allow_loopback_http=self._allow_loopback_http)
        account_id, worker_origin, _ = recovery._latest()
        if account_id != identity["accountId"]:
            raise MigrationError("The hosted backup account changed.")
        upload = HostedUploadClient(
            self._origin, worker_origin, token, identity["accountId"],
            identity["vaultId"], timeout=self._timeout,
            allow_loopback_http=self._allow_loopback_http)
        return upload, recovery
