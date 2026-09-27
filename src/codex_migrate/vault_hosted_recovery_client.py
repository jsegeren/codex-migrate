"""Read a complete published hosted inventory before any recovery write.

The device bearer comes from enrollment/Keychain, not a download link. This
adapter never stores that bearer, a recovery key, or signed object grants on
disk. It is not wired to the buyer UI until hosted release gates pass.
"""

from __future__ import annotations

import json
import re
from typing import Dict, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

from codex_migrate.errors import MigrationError
from codex_migrate.vault_http_store import CapabilityHttpStore, _NoRedirect
from codex_migrate.vault_remote_inventory import MAX_CHUNKS
from codex_migrate.vault_remote_recovery import _objects


_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
_KEY = re.compile(rf"(?:metadata/{_UUID}\.json|manifests/{_UUID}\.cvmanifest|"
                  rf"refs/{_UUID}\.json|objects/[0-9a-f]{{2}}/[0-9a-f]{{62}}\.cvchunk)\Z")
_TOKEN = re.compile(r"hv1_[A-Za-z0-9_-]{43}\Z")
_GRANT = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\Z")
_PAGE_SIZE = 256
_MAX_RESPONSE = 128 * 1024


def _origin(value: str, allow_loopback_http: bool) -> str:
    try:
        parsed = urlsplit(value)
        parsed.port
    except (TypeError, ValueError):
        raise MigrationError("The hosted recovery service is invalid.") from None
    if (parsed.username or parsed.password or parsed.path or parsed.query
            or parsed.fragment or not parsed.hostname or parsed.hostname.endswith(".")
            or parsed.scheme not in ("https", "http")
            or (parsed.scheme == "http" and not (allow_loopback_http
                 and parsed.hostname in ("127.0.0.1", "::1")))):
        raise MigrationError("The hosted recovery service is invalid.")
    return value.rstrip("/")


class HostedRecoveryClient:
    def __init__(self, service_origin: str, device_token: str, vault_id: str, *,
                 timeout: float = 30.0, allow_loopback_http: bool = False):
        self._origin = _origin(service_origin, allow_loopback_http)
        if (not isinstance(device_token, str) or not _TOKEN.fullmatch(device_token)
                or not isinstance(vault_id, str)
                or not re.fullmatch(_UUID, vault_id)
                or isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not 0 < timeout <= 120):
            raise MigrationError("The hosted recovery authorization is invalid.")
        self._device_token = device_token
        self._vault_id = vault_id
        self._timeout = timeout
        self._allow_loopback_http = allow_loopback_http
        self._opener = build_opener(_NoRedirect())

    def _post(self, claim: dict) -> dict:
        body = json.dumps(claim, separators=(",", ":")).encode("utf-8")
        if len(body) > 600:
            raise MigrationError("The hosted recovery request is invalid.")
        request = Request(self._origin + "/api/hosted-recovery", data=body,
                          headers={"Authorization": "Bearer " + self._device_token,
                                   "Content-Type": "application/json",
                                   "Content-Length": str(len(body))}, method="POST")
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                if (response.status != 200 or
                        response.headers.get("Content-Encoding", "identity") != "identity" or
                        response.headers.get("Content-Type", "").split(";")[0] !=
                        "application/json"):
                    raise MigrationError("The hosted recovery service response is invalid.")
                data = response.read(_MAX_RESPONSE + 1)
                if len(data) > _MAX_RESPONSE:
                    raise MigrationError("The hosted recovery service response is too large.")
        except (HTTPError, URLError, OSError, ValueError):
            # Never echo bearer credentials, request URLs, server bodies, or
            # provider diagnostics through a user-facing exception.
            raise MigrationError("The hosted recovery service is unavailable.") from None
        try:
            result = json.loads(data)
        except (UnicodeError, ValueError):
            raise MigrationError("The hosted recovery service response is invalid.") from None
        if not isinstance(result, dict):
            raise MigrationError("The hosted recovery service response is invalid.")
        return result

    def prepare(self, *, max_bytes: int) -> Tuple[dict, CapabilityHttpStore]:
        """Return a validated receipt and exact-object read store, without writes."""
        if type(max_bytes) is not int or max_bytes <= 0:
            raise MigrationError("The hosted recovery size limit is invalid.")
        latest_reply = self._post({"action": "latest", "vaultId": self._vault_id})
        if set(latest_reply) != {"accountId", "workerOrigin", "latest"}:
            raise MigrationError("The hosted recovery pointer is invalid.")
        account_id = latest_reply["accountId"]
        worker_origin = latest_reply["workerOrigin"]
        latest = latest_reply["latest"]
        if latest is None:
            raise MigrationError("This Vault has no verified hosted backup yet.")
        if (not isinstance(account_id, str) or not re.fullmatch(_UUID, account_id)
                or not isinstance(latest, dict)
                or set(latest) != {"snapshotId", "totalObjects", "totalBytes"}
                or not isinstance(latest["snapshotId"], str)
                or not re.fullmatch(_UUID, latest["snapshotId"])
                or type(latest["totalObjects"]) is not int
                or not 3 <= latest["totalObjects"] <= MAX_CHUNKS + 3
                or type(latest["totalBytes"]) is not int
                or not latest["totalObjects"] <= latest["totalBytes"] <= max_bytes):
            raise MigrationError("The hosted recovery pointer is invalid.")
        snapshot_id = latest["snapshotId"]
        prefix = f"accounts/{account_id}/vaults/{self._vault_id}/"
        expected: Dict[str, Tuple[int, str]] = {}
        cursor = None
        while True:
            claim = {"action": "objects", "vaultId": self._vault_id,
                     "snapshotId": snapshot_id}
            if cursor is not None:
                claim["afterKey"] = cursor
            page = self._post(claim)
            if (set(page) != {"snapshotId", "totalObjects", "totalBytes",
                             "objects", "nextCursor"}
                    or page["snapshotId"] != snapshot_id
                    or page["totalObjects"] != latest["totalObjects"]
                    or page["totalBytes"] != latest["totalBytes"]
                    or not isinstance(page["objects"], list)
                    or not 1 <= len(page["objects"]) <= _PAGE_SIZE):
                raise MigrationError("The hosted recovery inventory is invalid.")
            prior = cursor or ""
            for item in page["objects"]:
                if (not isinstance(item, dict)
                        or set(item) != {"key", "bytes", "sha256"}
                        or not isinstance(item["key"], str)
                        or not _KEY.fullmatch(item["key"])
                        or type(item["bytes"]) is not int or item["bytes"] <= 0
                        or not isinstance(item["sha256"], str)
                        or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])):
                    raise MigrationError("The hosted recovery inventory is invalid.")
                scoped = prefix + item["key"]
                if scoped <= prior or item["key"] in expected:
                    raise MigrationError("The hosted recovery inventory is invalid.")
                prior = scoped
                expected[item["key"]] = (item["bytes"], item["sha256"])
            if len(expected) > latest["totalObjects"]:
                raise MigrationError("The hosted recovery inventory is invalid.")
            next_cursor = page["nextCursor"]
            if next_cursor is None:
                break
            if (len(page["objects"]) != _PAGE_SIZE or
                    next_cursor != prior or next_cursor == cursor):
                raise MigrationError("The hosted recovery inventory is invalid.")
            cursor = next_cursor
        if (len(expected) != latest["totalObjects"] or
                sum(size for size, _ in expected.values()) != latest["totalBytes"]):
            raise MigrationError("The hosted recovery inventory is incomplete.")
        metadata = f"metadata/{snapshot_id}.json"
        manifest = f"manifests/{snapshot_id}.cvmanifest"
        reference = f"refs/{snapshot_id}.json"
        chunks = sorted(key for key in expected if key.startswith("objects/"))
        order = [metadata, *chunks, manifest, reference]
        if len(order) != len(expected) or any(key not in expected for key in order):
            raise MigrationError("The hosted recovery inventory is invalid.")
        receipt = {"version": 1, "snapshot_id": snapshot_id,
                   "remote_bytes_checked": latest["totalBytes"],
                   "objects": [{"key": key, "bytes": expected[key][0],
                                "sha256": expected[key][1]} for key in order]}
        _objects(receipt, max_bytes)

        def grant(method: str, scoped_key: str, size: int, digest: str) -> str:
            if (method != "GET" or not scoped_key.startswith(prefix)
                    or expected.get(scoped_key[len(prefix):]) != (size, digest)):
                raise MigrationError("The hosted recovery object is outside its receipt.")
            reply = self._post({"action": "get", "vaultId": self._vault_id,
                                "snapshotId": snapshot_id,
                                "relativeKey": scoped_key[len(prefix):]})
            token = reply.get("grant")
            if (set(reply) != {"workerOrigin", "grant"}
                    or reply["workerOrigin"] != worker_origin
                    or not isinstance(token, str) or not _GRANT.fullmatch(token)
                    or len(token) > 2048):
                raise MigrationError("The hosted recovery grant is invalid.")
            return token

        store = CapabilityHttpStore(worker_origin, account_id, self._vault_id,
                                    expected, grant, timeout=self._timeout,
                                    allow_loopback_http=self._allow_loopback_http)
        return receipt, store
