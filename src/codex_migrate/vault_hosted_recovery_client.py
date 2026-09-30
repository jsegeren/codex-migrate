"""Read a complete published hosted inventory before any recovery write.

The device bearer comes from enrollment/Keychain, not a download link. This
adapter never stores that bearer, a recovery key, or signed object grants on
disk. It is not wired to the buyer UI until hosted release gates pass.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from tempfile import TemporaryDirectory
from typing import Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

from codex_migrate.errors import MigrationError
from codex_migrate.vault_backup import _helper_path, _run_helper
from codex_migrate.vault_http_store import CapabilityHttpStore, _NoRedirect
from codex_migrate.vault_remote_inventory import MAX_CHUNKS, MAX_ENCRYPTED_MANIFEST_BYTES
from codex_migrate.vault_remote_recovery import _Object, _copy_to_file, _objects


_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
_KEY = re.compile(rf"(?:metadata/{_UUID}\.json|manifests/{_UUID}\.cvmanifest|"
                  rf"refs/{_UUID}\.json|objects/[0-9a-f]{{2}}/[0-9a-f]{{62}}\.cvchunk)\Z")
_TOKEN = re.compile(r"(?:hv1_|hvb1_)[A-Za-z0-9_-]{43}\Z")
_GRANT = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\Z")
_PAGE_SIZE = 256
_HISTORY_PAGE_SIZE = 50
_PUBLISHED_AT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z\Z")
_MAX_RESPONSE = 128 * 1024
_UNSPECIFIED = object()


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

    def _latest(self) -> Tuple[str, str, Optional[dict]]:
        """Distinguish an authenticated empty Vault from a failed lookup."""
        latest_reply = self._post({"action": "latest", "vaultId": self._vault_id})
        if set(latest_reply) != {"accountId", "workerOrigin", "latest"}:
            raise MigrationError("The hosted recovery pointer is invalid.")
        account_id = latest_reply["accountId"]
        worker_origin = latest_reply["workerOrigin"]
        latest = latest_reply["latest"]
        if (not isinstance(account_id, str) or not re.fullmatch(_UUID, account_id)
                or not isinstance(worker_origin, str)):
            raise MigrationError("The hosted recovery pointer is invalid.")
        _origin(worker_origin, self._allow_loopback_http)
        if latest is None:
            return account_id, worker_origin, None
        if (not isinstance(latest, dict)
                or set(latest) != {"snapshotId", "totalObjects", "totalBytes",
                                   "sourceCoverage"}
                or not isinstance(latest["snapshotId"], str)
                or not re.fullmatch(_UUID, latest["snapshotId"])
                or type(latest["totalObjects"]) is not int
                or not 3 <= latest["totalObjects"] <= MAX_CHUNKS + 3
                or type(latest["totalBytes"]) is not int
                or latest["totalBytes"] < latest["totalObjects"]
                or latest["sourceCoverage"] not in
                ("unknown", "complete", "needs_attention")):
            raise MigrationError("The hosted recovery pointer is invalid.")
        return account_id, worker_origin, latest

    def latest_snapshot(self, *, expected_account_id: str) -> Optional[dict]:
        """Read a validated current pointer; this does not reserve or protect."""
        if (not isinstance(expected_account_id, str) or
                not re.fullmatch(_UUID, expected_account_id)):
            raise MigrationError("The hosted recovery account is invalid.")
        account_id, _, latest = self._latest()
        if account_id != expected_account_id:
            raise MigrationError("The hosted recovery account changed.")
        return latest

    def published_snapshot(self, snapshot_id: str, *,
                           expected_account_id: str,
                           expected_worker_origin: str) -> dict:
        """Read one immutable published version's source-reported coverage."""
        if (not isinstance(snapshot_id, str) or not re.fullmatch(_UUID, snapshot_id)
                or not isinstance(expected_account_id, str)
                or not re.fullmatch(_UUID, expected_account_id)
                or not isinstance(expected_worker_origin, str)):
            raise MigrationError("The hosted recovery version is invalid.")
        reply = self._post({"action": "snapshot", "vaultId": self._vault_id,
                            "snapshotId": snapshot_id})
        if (set(reply) != {"accountId", "workerOrigin", "snapshot"}
                or reply["accountId"] != expected_account_id
                or reply["workerOrigin"] != expected_worker_origin):
            raise MigrationError("The hosted recovery version is invalid.")
        selected = self._summary(reply["snapshot"])
        if selected["snapshotId"] != snapshot_id:
            raise MigrationError("The hosted recovery version is invalid.")
        return selected

    def latest_source_complete_snapshot(self, *, expected_account_id: str,
                                        expected_worker_origin: str) -> Optional[dict]:
        """Read the newest Mac-reported complete version, if one exists."""
        if (not isinstance(expected_account_id, str)
                or not re.fullmatch(_UUID, expected_account_id)
                or not isinstance(expected_worker_origin, str)):
            raise MigrationError("The hosted recovery account is invalid.")
        reply = self._post({"action": "latest_complete", "vaultId": self._vault_id})
        if (set(reply) != {"accountId", "workerOrigin", "latestComplete"}
                or reply["accountId"] != expected_account_id
                or reply["workerOrigin"] != expected_worker_origin):
            raise MigrationError("The hosted complete version is invalid.")
        if reply["latestComplete"] is None:
            return None
        selected = self._summary(reply["latestComplete"])
        if selected["sourceCoverage"] != "complete":
            raise MigrationError("The hosted complete version is invalid.")
        return selected

    def account_storage_usage(self, *, expected_account_id: str) -> dict:
        """Read server-accounted retained bytes, not a customer bill or R2 proof."""
        if (not isinstance(expected_account_id, str) or
                not re.fullmatch(_UUID, expected_account_id)):
            raise MigrationError("The hosted recovery account is invalid.")
        reply = self._post({"action": "usage", "vaultId": self._vault_id})
        if (set(reply) != {"accountId", "retainedBytes", "reservedBytes"} or
                reply["accountId"] != expected_account_id or
                type(reply["retainedBytes"]) is not int or
                not 0 <= reply["retainedBytes"] <= 2**53 - 1 or
                type(reply["reservedBytes"]) is not int or
                not 0 <= reply["reservedBytes"] <= 2**53 - 1):
            raise MigrationError("The hosted storage usage is invalid.")
        return {"retainedBytes": reply["retainedBytes"],
                "reservedBytes": reply["reservedBytes"]}

    @staticmethod
    def _summary(value: object) -> dict:
        if (not isinstance(value, dict)
                or set(value) != {"snapshotId", "totalObjects", "totalBytes",
                                  "sourceCoverage"}
                or not isinstance(value["snapshotId"], str)
                or not re.fullmatch(_UUID, value["snapshotId"])
                or type(value["totalObjects"]) is not int
                or not 3 <= value["totalObjects"] <= MAX_CHUNKS + 3
                or type(value["totalBytes"]) is not int
                or value["totalBytes"] < value["totalObjects"]
                or value["sourceCoverage"] not in
                ("unknown", "complete", "needs_attention")):
            raise MigrationError("The hosted recovery version is invalid.")
        return value

    @staticmethod
    def _published_at(value: object) -> str:
        if not isinstance(value, str) or not _PUBLISHED_AT.fullmatch(value):
            raise MigrationError("The hosted recovery history is invalid.")
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise MigrationError("The hosted recovery history is invalid.") from None
        return value

    def history_page(self, before: Optional[Tuple[str, str]] = None
                     ) -> Tuple[List[dict], Optional[Tuple[str, str]]]:
        """Discover one bounded page of published versions; never download data."""
        account_id, worker_origin, _latest = self._latest()
        claim = {"action": "history", "vaultId": self._vault_id}
        if before is not None:
            if not isinstance(before, tuple) or len(before) != 2:
                raise MigrationError("The hosted recovery history cursor is invalid.")
            claim["beforeAt"] = self._published_at(before[0])
            if not isinstance(before[1], str) or not re.fullmatch(_UUID, before[1]):
                raise MigrationError("The hosted recovery history cursor is invalid.")
            claim["beforeSnapshotId"] = before[1]
        page = self._post(claim)
        if (set(page) != {"accountId", "workerOrigin", "snapshots", "nextCursor"}
                or page["accountId"] != account_id
                or page["workerOrigin"] != worker_origin
                or not isinstance(page["snapshots"], list)
                or len(page["snapshots"]) > _HISTORY_PAGE_SIZE):
            raise MigrationError("The hosted recovery history is invalid.")
        prior = before
        entries = []
        for item in page["snapshots"]:
            if not isinstance(item, dict) or set(item) != {
                    "snapshotId", "totalObjects", "totalBytes",
                    "sourceCoverage", "publishedAt"}:
                raise MigrationError("The hosted recovery history is invalid.")
            summary = self._summary({key: item[key] for key in (
                "snapshotId", "totalObjects", "totalBytes", "sourceCoverage")})
            position = (self._published_at(item["publishedAt"]), summary["snapshotId"])
            if prior is not None and position >= prior:
                raise MigrationError("The hosted recovery history is invalid.")
            prior = position
            entries.append(item)
        next_cursor = page["nextCursor"]
        if next_cursor is not None:
            if (len(entries) != _HISTORY_PAGE_SIZE or
                    not isinstance(next_cursor, dict)
                    or set(next_cursor) != {"publishedAt", "snapshotId"}
                    or (self._published_at(next_cursor["publishedAt"]),
                        next_cursor["snapshotId"]) != prior):
                raise MigrationError("The hosted recovery history is invalid.")
            return entries, prior
        return entries, None

    def prepare(self, *, max_bytes: int,
                expected_pointer: Optional[Tuple[str, str, dict]] = None,
                selected_snapshot_id: Optional[str] = None
                ) -> Tuple[dict, CapabilityHttpStore]:
        """Return a validated receipt and exact-object read store, without writes."""
        if type(max_bytes) is not int or max_bytes <= 0:
            raise MigrationError("The hosted recovery size limit is invalid.")
        account_id, worker_origin, latest = self._latest()
        if latest is None:
            raise MigrationError("This Vault has no verified hosted backup yet.")
        if (expected_pointer is not None and
                (account_id, worker_origin, latest) != expected_pointer):
            raise MigrationError("The hosted recovery pointer changed or exceeds its limit.")
        selected = latest
        if selected_snapshot_id is not None:
            if not isinstance(selected_snapshot_id, str) or not re.fullmatch(
                    _UUID, selected_snapshot_id):
                raise MigrationError("The hosted recovery version is invalid.")
            reply = self._post({"action": "snapshot", "vaultId": self._vault_id,
                                "snapshotId": selected_snapshot_id})
            if (set(reply) != {"accountId", "workerOrigin", "snapshot"}
                    or reply["accountId"] != account_id
                    or reply["workerOrigin"] != worker_origin):
                raise MigrationError("The hosted recovery version is invalid.")
            selected = self._summary(reply["snapshot"])
            if selected["snapshotId"] != selected_snapshot_id:
                raise MigrationError("The hosted recovery version is invalid.")
        if selected["totalBytes"] > max_bytes:
            raise MigrationError("The hosted recovery version exceeds its limit.")
        snapshot_id = selected["snapshotId"]
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
                    or page["totalObjects"] != selected["totalObjects"]
                    or page["totalBytes"] != selected["totalBytes"]
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
            if len(expected) > selected["totalObjects"]:
                raise MigrationError("The hosted recovery inventory is invalid.")
            next_cursor = page["nextCursor"]
            if next_cursor is None:
                break
            if (len(page["objects"]) != _PAGE_SIZE or
                    next_cursor != prior or next_cursor == cursor):
                raise MigrationError("The hosted recovery inventory is invalid.")
            cursor = next_cursor
        if (len(expected) != selected["totalObjects"] or
                sum(size for size, _ in expected.values()) != selected["totalBytes"]):
            raise MigrationError("The hosted recovery inventory is incomplete.")
        metadata = f"metadata/{snapshot_id}.json"
        manifest = f"manifests/{snapshot_id}.cvmanifest"
        reference = f"refs/{snapshot_id}.json"
        chunks = sorted(key for key in expected if key.startswith("objects/"))
        order = [metadata, *chunks, manifest, reference]
        if len(order) != len(expected) or any(key not in expected for key in order):
            raise MigrationError("The hosted recovery inventory is invalid.")
        receipt = {"version": 1, "snapshot_id": snapshot_id,
                   "remote_bytes_checked": selected["totalBytes"],
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

    def prior_catalog(self, *, key_id: str, crypto_helper: str, max_bytes: int,
                      expected_snapshot_id: object = _UNSPECIFIED,
                      expected_account_id: Optional[str] = None,
                      include_chunks: bool = False,
                      ) -> Tuple[Optional[str], List[dict]]:
        """Read only the authenticated prior manifest for hosted loss warnings.

        No prior pointer is a genuine first backup, not a transport error. A
        caller must retain the returned snapshot identity through publication;
        this read alone does not provide compare-and-swap protection.
        """
        if type(max_bytes) is not int or max_bytes <= 0:
            raise MigrationError("The hosted recovery size limit is invalid.")
        if (expected_snapshot_id is not _UNSPECIFIED and
                expected_snapshot_id is not None and
                (not isinstance(expected_snapshot_id, str) or
                 not re.fullmatch(_UUID, expected_snapshot_id))):
            raise MigrationError("The reserved hosted snapshot base is invalid.")
        if (expected_account_id is not None and
                (not isinstance(expected_account_id, str) or
                 not re.fullmatch(_UUID, expected_account_id))):
            raise MigrationError("The hosted recovery account is invalid.")
        pointer = self._latest()
        if expected_account_id is not None and pointer[0] != expected_account_id:
            raise MigrationError("The hosted recovery account changed.")
        latest = pointer[2]
        observed = None if latest is None else latest["snapshotId"]
        if expected_snapshot_id is not _UNSPECIFIED and observed != expected_snapshot_id:
            raise MigrationError("The hosted backup changed after reservation.")
        if latest is None:
            return None, []
        helper = _helper_path(crypto_helper)
        snapshot_id = latest["snapshotId"]
        key = f"manifests/{snapshot_id}.cvmanifest"
        manifest = self._post({"action": "manifest", "vaultId": self._vault_id,
                               "snapshotId": snapshot_id})
        size = manifest.get("bytes")
        digest = manifest.get("sha256")
        token = manifest.get("grant")
        if (set(manifest) != {"accountId", "workerOrigin", "snapshotId",
                              "bytes", "sha256", "grant"} or
                manifest["accountId"] != pointer[0] or
                manifest["workerOrigin"] != pointer[1] or
                manifest["snapshotId"] != snapshot_id or
                type(size) is not int or not 0 < size <= MAX_ENCRYPTED_MANIFEST_BYTES or
                not isinstance(digest, str) or
                not re.fullmatch(r"[0-9a-f]{64}", digest) or
                not isinstance(token, str) or not _GRANT.fullmatch(token) or
                len(token) > 2048):
            raise MigrationError("The prior hosted manifest grant is invalid.")
        if size > max_bytes:
            raise MigrationError("The prior hosted manifest exceeds its selected size limit.")
        expected = {key: (size, digest)}
        scoped = f"accounts/{pointer[0]}/vaults/{self._vault_id}/{key}"

        def grant(method: str, scoped_key: str, object_size: int,
                  object_digest: str) -> str:
            if (method != "GET" or scoped_key != scoped or
                    (object_size, object_digest) != (size, digest)):
                raise MigrationError("The prior hosted manifest grant is out of scope.")
            return token

        store = CapabilityHttpStore(pointer[1], pointer[0], self._vault_id,
                                    expected, grant, timeout=self._timeout,
                                    allow_loopback_http=self._allow_loopback_http)
        stream = store.open_read(key)
        if stream is None:
            raise MigrationError("The prior hosted manifest is missing.")
        with TemporaryDirectory(prefix="codex-vault-prior-") as temporary:
            path = os.path.join(temporary, "prior.cvmanifest")
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                                 os.O_NOFOLLOW, 0o600)
            with stream:
                _copy_to_file(stream, descriptor, _Object(key, size, digest))
            catalog = _run_helper(helper, [
                "staging-catalog" if include_chunks else "catalog",
                "--key-id", key_id, "--snapshot-id", snapshot_id,
                "--manifest", path,
            ])
        files = catalog.get("files")
        if (catalog.get("snapshot_id") != snapshot_id or
                not isinstance(files, list) or len(files) > 100_000 or
                not all(isinstance(item, dict) for item in files)):
            raise MigrationError("The prior hosted catalog is invalid.")
        return snapshot_id, files
