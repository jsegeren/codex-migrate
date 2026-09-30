"""Sandbox-only hosted upload adapter for already encrypted Vault objects.

The first-party service decides whether an object may be checked or needs an
immutable PUT. It alone issues the short-lived Worker grants. Staging through
this adapter never publishes a snapshot or calls it a protected backup.
"""

from __future__ import annotations

import json
import re
import time
from typing import Mapping, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from codex_migrate.errors import MigrationError
from codex_migrate.vault_hosted_recovery_client import _origin
from codex_migrate.vault_hosted_snapshot_stage import HostedSnapshotStage
from codex_migrate.vault_http_store import CapabilityHttpStore, _NoRedirect
from codex_migrate.vault_remote_inventory import encrypted_snapshot_inventory
from codex_migrate.vault_remote_transfer import (
    StageResult, StagedObject, stage_encrypted_snapshot,
)


_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")
_TOKEN = re.compile(r"hv1_[A-Za-z0-9_-]{43}\Z")
_GRANT = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_MAX_RESPONSE = 2048


class HostedPublicationStale(MigrationError):
    """A different verified snapshot advanced this Vault after reservation."""


class HostedUploadClient:
    """Pinned origins and a Keychain-sourced device bearer, never a bucket key.

    Callers must explicitly opt into mutations. This is intentionally not
    exposed in the customer UI while hosted billing and recovery are dark.
    """

    def __init__(self, service_origin: str, worker_origin: str,
                 device_token: str, account_id: str, vault_id: str, *,
                 timeout: float = 30.0, allow_loopback_http: bool = False):
        self._service_origin = _origin(service_origin, allow_loopback_http)
        self._worker_origin = _origin(worker_origin, allow_loopback_http)
        if (not isinstance(device_token, str) or not _TOKEN.fullmatch(device_token)
                or not isinstance(account_id, str) or not _UUID.fullmatch(account_id)
                or not isinstance(vault_id, str) or not _UUID.fullmatch(vault_id)
                or isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not 0 < timeout <= 120):
            raise MigrationError("The hosted upload authorization is invalid.")
        self._device_token = device_token
        self._account_id = account_id
        self._vault_id = vault_id
        self._timeout = timeout
        self._allow_loopback_http = allow_loopback_http
        self._opener = build_opener(_NoRedirect())
        self._object_lease_token = None
        self._object_lease_reservation = None
        self._object_lease_until = 0.0
        self._service_request_counts: dict[str, int] = {}
        self._worker_attempt_counts = {
            "head": 0, "put": 0, "put_bytes": 0,
            "put_confirmed": 0, "put_confirmed_bytes": 0,
        }

    def service_request_counts(self) -> dict[str, int]:
        """Content-free attempted request counts for cost/latency acceptance."""
        return dict(self._service_request_counts)

    def worker_attempt_counts(self) -> dict[str, int]:
        """Content-free Worker attempts; confirmed PUTs exclude uncertain replies."""
        return dict(self._worker_attempt_counts)

    def _object_lease(self, reservation_id: str) -> str:
        if (self._object_lease_token is not None and
                self._object_lease_reservation == reservation_id and
                time.monotonic() < self._object_lease_until):
            return self._object_lease_token
        started = time.monotonic()
        result = self._post({"action": "lease", "vaultId": self._vault_id,
                             "reservationId": reservation_id})
        lease = result.get("lease")
        if (set(result) != {"lease"} or not isinstance(lease, str) or
                len(lease) > 750 or
                not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", lease)):
            raise MigrationError("The hosted object authorization is invalid.")
        # Server validity is 60 seconds. Refresh well before expiry even if
        # the lease response itself took time to reach this client.
        self._object_lease_token = lease
        self._object_lease_reservation = reservation_id
        self._object_lease_until = started + 40.0
        return lease

    def _post(self, claim: dict, *, receipt_page: bool = False,
              publication: bool = False, verification: bool = False,
              checkpointed_publication: bool = False,
              published_lookup: bool = False) -> dict:
        if sum((receipt_page, publication, verification,
                checkpointed_publication, published_lookup)) > 1:
            raise MigrationError("The hosted upload request is invalid.")
        body = json.dumps(claim, separators=(",", ":")).encode("utf-8")
        request_limit = (256 * 1024 if receipt_page else 18_000 if published_lookup
                         else 2_000 if claim.get("action") == "batch" else 700)
        if len(body) > request_limit:
            raise MigrationError("The hosted upload request is too large.")
        path = ("/api/hosted-receipt-page" if receipt_page else
                "/api/hosted-publish" if publication else
                "/api/hosted-verify-step" if verification else
                "/api/hosted-publish-checkpointed" if checkpointed_publication
                else "/api/hosted-published-chunks" if published_lookup
                else "/api/hosted-upload")
        headers = {"Authorization": "Bearer " + self._device_token,
                   "Content-Type": "application/json",
                   "Content-Length": str(len(body))}
        if claim.get("action") in ("decide", "put", "batch"):
            headers["X-Hosted-Upload-Lease"] = self._object_lease(
                claim["reservationId"])
        request = Request(self._service_origin + path, data=body,
                          headers=headers, method="POST")
        action = claim.get("action") if not published_lookup else "published_lookup"
        if not isinstance(action, str):
            action = "unknown"
        self._service_request_counts[action] = (
            self._service_request_counts.get(action, 0) + 1)
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                if (response.status != 200 or
                        response.headers.get("Content-Encoding", "identity") != "identity" or
                        response.headers.get("Content-Type", "").split(";")[0] !=
                        "application/json"):
                    raise MigrationError("The hosted upload service response is invalid.")
                response_limit = (50_000 if published_lookup else
                                  20_000 if claim.get("action") == "batch"
                                  else _MAX_RESPONSE)
                data = response.read(response_limit + 1)
                if len(data) > response_limit:
                    raise MigrationError("The hosted upload service response is too large.")
        except HTTPError as error:
            if (error.code == 409 and (publication or checkpointed_publication)
                    and error.headers.get("Content-Encoding", "identity") == "identity"
                    and error.headers.get("Content-Type", "").split(";")[0] ==
                    "application/json"):
                try:
                    if json.loads(error.read(129)) == {"error": "stale_snapshot"}:
                        raise HostedPublicationStale(
                            "Another verified backup advanced this Vault. "
                            "Review and abandon this pending upload before starting a new backup.")
                except (OSError, UnicodeError, ValueError):
                    pass
            raise MigrationError("The hosted upload service is unavailable.") from None
        except (URLError, OSError, ValueError):
            # Never include the bearer, object path, response body or URL.
            raise MigrationError("The hosted upload service is unavailable.") from None
        try:
            result = json.loads(data)
        except (UnicodeError, ValueError):
            raise MigrationError("The hosted upload service response is invalid.") from None
        if not isinstance(result, dict):
            raise MigrationError("The hosted upload service response is invalid.")
        return result

    def published_chunks(self, ids: list[str]) -> dict[str, Tuple[int, str]]:
        """Read published-only ciphertext facts, not provider-presence proof.

        A later exact HEAD and the service's independent publication verifier
        must still check R2 before this can count as a protected snapshot.
        """
        if (not isinstance(ids, list) or not 1 <= len(ids) <= 256 or
                any(not isinstance(item, str) or not _HEX.fullmatch(item)
                    for item in ids) or len(set(ids)) != len(ids)):
            raise MigrationError("The hosted chunk lookup is invalid.")
        result = self._post({"vaultId": self._vault_id, "ids": ids},
                            published_lookup=True)
        rows = result.get("objects")
        if set(result) != {"objects"} or not isinstance(rows, list) or len(rows) > len(ids):
            raise MigrationError("The hosted chunk lookup response is invalid.")
        candidates = set(ids)
        observed: dict[str, Tuple[int, str]] = {}
        prior = ""
        for row in rows:
            if (not isinstance(row, dict) or set(row) != {"id", "bytes", "sha256"} or
                    not isinstance(row["id"], str) or row["id"] not in candidates or
                    row["id"] <= prior or type(row["bytes"]) is not int or
                    not 1 <= row["bytes"] <= 100_000_000 or
                    not isinstance(row["sha256"], str) or
                    not _HEX.fullmatch(row["sha256"])):
                raise MigrationError("The hosted chunk lookup response is invalid.")
            prior = row["id"]
            observed[row["id"]] = (row["bytes"], row["sha256"])
        return observed

    def reserve(self, *, apply: bool = False) -> str:
        return self.reserve_with_base(apply=apply)[0]

    def reserve_with_base(self, *, reservation_id: Optional[str] = None,
                          apply: bool = False
                          ) -> Tuple[str, Optional[str]]:
        """Retry a pre-recorded ID without creating another reservation."""
        if apply is not True:
            raise MigrationError("Hosted upload changes require explicit confirmation.")
        if reservation_id is not None:
            self._require_reservation(reservation_id)
        # New PUT grants grow the reservation by exact distinct ciphertext
        # bytes. Reserving the full snapshot would falsely exhaust capacity
        # for a mostly-unchanged incremental backup.
        claim = {"action": "reserve", "vaultId": self._vault_id, "bytes": 1}
        if reservation_id is not None:
            claim["reservationId"] = reservation_id
        result = self._post(claim)
        reservation_id = self._reservation(result, include_base=True)
        if claim.get("reservationId") is not None and reservation_id != claim["reservationId"]:
            raise MigrationError("The hosted upload reservation changed on retry.")
        return reservation_id, result["baseSnapshotId"]

    def renew(self, reservation_id: str, *, apply: bool = False) -> str:
        if apply is not True:
            raise MigrationError("Hosted upload changes require explicit confirmation.")
        self._require_reservation(reservation_id)
        result = self._post({"action": "renew", "vaultId": self._vault_id,
                             "reservationId": reservation_id})
        return self._reservation(result, reservation_id)

    def abandon(self, reservation_id: str, *, apply: bool = False) -> None:
        """Quarantine this reservation; remote deletion and quota release follow later."""
        if apply is not True:
            raise MigrationError("Hosted upload changes require explicit confirmation.")
        self._require_reservation(reservation_id)
        result = self._post({"action": "abandon", "vaultId": self._vault_id,
                             "reservationId": reservation_id})
        if set(result) != {"cleanupPending"} or result["cleanupPending"] is not True:
            raise MigrationError("The hosted upload abandon response is invalid.")

    def reservation_status(self, reservation_id: str) -> str:
        """Read authoritative cleanup state without requiring a subscription."""
        return self.reservation_receipt(reservation_id)["state"]

    def reservation_receipt(self, reservation_id: str) -> dict:
        """Reconcile a lost publication response to one exact published ID."""
        self._require_reservation(reservation_id)
        result = self._post({"action": "status", "vaultId": self._vault_id,
                             "reservationId": reservation_id})
        state = result.get("state")
        if state in ("active", "cleanup_pending", "released"):
            valid = set(result) == {"state"}
        elif state == "published":
            snapshot_id = result.get("snapshotId")
            count = result.get("verifiedObjectCount")
            valid = (set(result) == {"state", "snapshotId", "verifiedObjectCount"}
                     and isinstance(snapshot_id, str) and
                     _UUID.fullmatch(snapshot_id) is not None and
                     type(count) is int and 3 <= count <= 1_000_000)
        else:
            valid = False
        if not valid:
            raise MigrationError("The hosted upload status response is invalid.")
        return result

    @staticmethod
    def _require_reservation(reservation_id: str) -> None:
        if not isinstance(reservation_id, str) or not _UUID.fullmatch(reservation_id):
            raise MigrationError("The hosted upload reservation is invalid.")

    @staticmethod
    def _reservation(result: dict, expected: str = "", *,
                     include_base: bool = False) -> str:
        value = result.get("reservationId")
        keys = {"reservationId", "expiresAt"}
        if include_base:
            keys.add("baseSnapshotId")
        base = result.get("baseSnapshotId")
        if (set(result) != keys or
                not isinstance(value, str) or not _UUID.fullmatch(value) or
                (expected and value != expected) or
                (include_base and base is not None and
                 (not isinstance(base, str) or not _UUID.fullmatch(base))) or
                not isinstance(result.get("expiresAt"), str) or
                not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z",
                                 result["expiresAt"])):
            raise MigrationError("The hosted upload reservation response is invalid.")
        return value

    def _item(self, expected: Mapping[str, Tuple[int, str]], key: str) -> dict:
        if key not in expected:
            raise MigrationError("The hosted object is outside the selected Vault.")
        size, digest = expected[key]
        return {"key": key, "bytes": size, "sha256": digest}

    def _grant(self, result: dict, *, head: bool = False) -> str:
        keys = {"action", "workerOrigin", "grant"} if head else {"workerOrigin", "grant"}
        grant = result.get("grant")
        if (set(result) != keys or (head and result.get("action") != "head") or
                result.get("workerOrigin") != self._worker_origin or
                not isinstance(grant, str) or not _GRANT.fullmatch(grant) or
                len(grant) > 2048):
            raise MigrationError("The hosted upload grant is invalid.")
        return grant

    def object_store(self, reservation_id: str,
                     expected: Mapping[str, Tuple[int, str]], *,
                     apply: bool = False) -> "HostedUploadObjectStore":
        self._require_reservation(reservation_id)
        if apply is not True:
            raise MigrationError("Hosted upload changes require explicit confirmation.")
        # Let the transport validate the exact relative-key inventory before
        # any request. No broad bucket credentials reach this object.
        CapabilityHttpStore(self._worker_origin, self._account_id, self._vault_id,
                            expected, lambda *_: "invalid.invalid",
                            timeout=self._timeout,
                            allow_loopback_http=self._allow_loopback_http)
        return HostedUploadObjectStore(self, reservation_id, dict(expected))

    def submit_pages(self, reservation_id: str, staged: StageResult, *,
                     apply: bool = False) -> int:
        """Admit bounded claims; an ACK is not R2 verification or protection.

        Retrying from the first page is safe because the server admits exact
        duplicate claims idempotently and rejects conflicting object facts.
        """
        if apply is not True:
            raise MigrationError("Hosted upload changes require explicit confirmation.")
        self._require_reservation(reservation_id)
        if (not isinstance(staged, StageResult) or
                not isinstance(staged.snapshot_id, str) or
                not _UUID.fullmatch(staged.snapshot_id) or
                not isinstance(staged.objects, tuple) or
                not 3 <= len(staged.objects) <= 1_000_000 or
                any(not isinstance(item, StagedObject) or
                    not isinstance(item.bytes, int) or
                    isinstance(item.bytes, bool) or item.bytes < 1
                    for item in staged.objects) or
                not isinstance(staged.remote_bytes_checked, int) or
                isinstance(staged.remote_bytes_checked, bool) or
                staged.remote_bytes_checked < len(staged.objects) or
                staged.remote_bytes_checked != sum(item.bytes for item in staged.objects)):
            raise MigrationError("The staged hosted inventory is invalid.")
        acknowledged = 0
        for page in staged.object_pages():
            result = self._post({"action": "page", "vaultId": self._vault_id,
                                 "reservationId": reservation_id,
                                 "snapshotId": staged.snapshot_id,
                                 "expectedCount": len(staged.objects),
                                 "expectedBytes": staged.remote_bytes_checked,
                                 "objects": page}, receipt_page=True)
            if (set(result) != {"acceptedObjects"} or
                    type(result["acceptedObjects"]) is not int or
                    result["acceptedObjects"] != len(page)):
                raise MigrationError("The hosted receipt page was not acknowledged.")
            acknowledged += len(page)
        return acknowledged

    def publish(self, reservation_id: str, snapshot_id: str, *,
                apply: bool = False) -> int:
        """Request independent server verification, then last-good publication.

        A transport failure, including a lost successful response, is not a
        protection receipt. The caller may retry this exact reservation and
        snapshot; the server's publication transaction is idempotent.
        """
        if apply is not True:
            raise MigrationError("Hosted upload changes require explicit confirmation.")
        self._require_reservation(reservation_id)
        if not isinstance(snapshot_id, str) or not _UUID.fullmatch(snapshot_id):
            raise MigrationError("The hosted snapshot is invalid.")
        result = self._post({"action": "publish", "vaultId": self._vault_id,
                             "reservationId": reservation_id,
                             "snapshotId": snapshot_id}, publication=True)
        count = result.get("verifiedObjectCount")
        if (set(result) != {"snapshotId", "verifiedObjectCount"} or
                result.get("snapshotId") != snapshot_id or
                type(count) is not int or not 3 <= count <= 1_000_000):
            raise MigrationError("The hosted publication response is invalid.")
        return count

    def verify_next(self, reservation_id: str, snapshot_id: str, *,
                    apply: bool = False) -> Tuple[int, bool]:
        """Checkpoint provider proofs or bounded recent published proofs; not protection."""
        if apply is not True:
            raise MigrationError("Hosted upload changes require explicit confirmation.")
        self._require_reservation(reservation_id)
        if not isinstance(snapshot_id, str) or not _UUID.fullmatch(snapshot_id):
            raise MigrationError("The hosted snapshot is invalid.")
        result = self._post({"action": "verify_next", "vaultId": self._vault_id,
                             "reservationId": reservation_id,
                             "snapshotId": snapshot_id}, verification=True)
        count = result.get("verifiedObjects")
        ready = result.get("ready")
        if (set(result) != {"verifiedObjects", "ready"} or
                type(count) is not int or not 0 <= count <= 2048 or
                type(ready) is not bool or ready != (count == 0)):
            raise MigrationError("The hosted verification response is invalid.")
        return count, ready

    def publish_checkpointed(self, reservation_id: str, snapshot_id: str, *,
                             source_coverage: str,
                             apply: bool = False) -> int:
        """Only the server's completed publication returns a protection count."""
        if apply is not True:
            raise MigrationError("Hosted upload changes require explicit confirmation.")
        self._require_reservation(reservation_id)
        if not isinstance(snapshot_id, str) or not _UUID.fullmatch(snapshot_id):
            raise MigrationError("The hosted snapshot is invalid.")
        if source_coverage not in ("complete", "needs_attention"):
            raise MigrationError("The hosted source coverage is invalid.")
        result = self._post({"action": "publish_checkpointed",
                             "vaultId": self._vault_id,
                             "reservationId": reservation_id,
                             "snapshotId": snapshot_id,
                             "sourceCoverage": source_coverage},
                            checkpointed_publication=True)
        count = result.get("verifiedObjectCount")
        if (set(result) != {"snapshotId", "verifiedObjectCount"} or
                result.get("snapshotId") != snapshot_id or
                type(count) is not int or not 3 <= count <= 1_000_000):
            raise MigrationError("The hosted publication response is invalid.")
        return count

    def verify_and_publish(self, reservation_id: str, snapshot_id: str, *,
                           source_coverage: str,
                           apply: bool = False) -> int:
        """Resume bounded proof steps; return only after publication succeeds.

        A failed network request is ambiguous, never success. Reinvoking this
        method with the same IDs resumes the service's exact verified pages.
        """
        if apply is not True:
            raise MigrationError("Hosted upload changes require explicit confirmation.")
        self._require_reservation(reservation_id)
        if not isinstance(snapshot_id, str) or not _UUID.fullmatch(snapshot_id):
            raise MigrationError("The hosted snapshot is invalid.")
        last_renewal = time.monotonic()
        # The server returns 128 until the final page. 7,814 calls cover its
        # one-million-object maximum plus the empty ready check.
        for _ in range(7_814):
            if time.monotonic() - last_renewal >= 25 * 60:
                self.renew(reservation_id, apply=True)
                last_renewal = time.monotonic()
            _, ready = self.verify_next(reservation_id, snapshot_id, apply=True)
            if ready:
                if time.monotonic() - last_renewal >= 25 * 60:
                    self.renew(reservation_id, apply=True)
                return self.publish_checkpointed(reservation_id, snapshot_id,
                                                  source_coverage=source_coverage,
                                                  apply=True)
        raise MigrationError("Hosted verification did not complete safely.")

    def publish_hosted_stage(self, reservation_id: str,
                             staged: HostedSnapshotStage, *,
                             apply: bool = False) -> dict:
        """Publish a bounded hosted-only stage only after server-side proof."""
        if apply is not True:
            raise MigrationError("Hosted backup changes require explicit confirmation.")
        self._require_reservation(reservation_id)
        if (not isinstance(staged, HostedSnapshotStage) or
                staged.reservation_id != reservation_id):
            raise MigrationError("The hosted stage belongs to another reservation.")
        claim = staged.upload_claim()
        if self.submit_pages(reservation_id, claim, apply=True) != len(claim.objects):
            raise MigrationError("The hosted snapshot receipt is incomplete.")
        verified = self.verify_and_publish(reservation_id, claim.snapshot_id,
                                           source_coverage=("complete" if
                                               staged.at_risk_threads == 0 else
                                               "needs_attention"), apply=True)
        if verified != len(claim.objects):
            raise MigrationError("The hosted publication receipt is incomplete.")
        return {"snapshotId": claim.snapshot_id,
                "verifiedObjectCount": verified,
                "sourceCoverage": ("complete" if staged.at_risk_threads == 0 else
                                   "needs_attention"),
                "encryptedBytes": claim.remote_bytes_checked,
                "transcriptFiles": staged.transcript_files,
                "transcriptBytes": staged.transcript_bytes,
                "restagedPlaintextBytes": staged.restaged_plaintext_bytes,
                "reusedPlaintextBytes": staged.reused_plaintext_bytes,
                "atRiskThreads": staged.at_risk_threads,
                **({"titleIndexUnavailable": True}
                   if staged.title_index_unavailable else {})}

    def back_up_snapshot(self, vault: str, *, reservation_id: str,
                         snapshot: str = "latest",
                         crypto_helper: Optional[str] = None,
                         apply: bool = False) -> dict:
        """Upload one encrypted snapshot and return only a published receipt.

        This dark adapter does not create a local snapshot or install a schedule.
        The caller must first reserve and durably record the reservation ID.
        A network error or lost publication response is ambiguous, never a
        successful backup. Retry with that same ID; objects are immutable and
        the service independently verifies them before moving last-good.
        """
        if apply is not True:
            raise MigrationError("Hosted backup changes require explicit confirmation.")
        self._require_reservation(reservation_id)
        inventory = encrypted_snapshot_inventory(
            vault, snapshot=snapshot, crypto_helper=crypto_helper)
        expected = {item.remote_key: (item.bytes, item.sha256)
                    for item in inventory.files}
        if len(expected) != len(inventory.files):
            raise MigrationError("The hosted snapshot inventory has duplicate objects.")
        store = self.object_store(reservation_id, expected, apply=True)
        staged = stage_encrypted_snapshot(
            vault, store, snapshot=snapshot, crypto_helper=crypto_helper)
        if (staged.snapshot_id != inventory.snapshot_id or
                len(staged.objects) != len(expected) or
                {item.key: (item.bytes, item.sha256) for item in staged.objects}
                != expected):
            raise MigrationError("The hosted snapshot changed during staging.")
        if self.submit_pages(reservation_id, staged, apply=True) != len(staged.objects):
            raise MigrationError("The hosted snapshot receipt is incomplete.")
        verified = self.verify_and_publish(
            reservation_id, staged.snapshot_id,
            # This older local-Vault mirror path does not attest source
            # coverage; never turn it into a complete business-backup claim.
            source_coverage="needs_attention", apply=True)
        if verified != len(staged.objects):
            raise MigrationError("The hosted publication receipt is incomplete.")
        return {"snapshotId": staged.snapshot_id,
                "verifiedObjectCount": verified,
                "uploadedFiles": staged.uploaded_files,
                "reusedFiles": staged.reused_files,
                "encryptedBytes": staged.remote_bytes_checked}


class HostedUploadObjectStore:
    """Interpret put_required as no HEAD grant, never as an observed 404."""

    def __init__(self, client: HostedUploadClient, reservation_id: str,
                 expected: Mapping[str, Tuple[int, str]]):
        self._client = client
        self._reservation_id = reservation_id
        self._expected = expected
        self._last_renewal = time.monotonic()
        self._ordered_keys = tuple(expected)
        self._positions = {key: index for index, key in enumerate(self._ordered_keys)}
        self._prepared_once: set[str] = set()
        self._prepared: dict[str, Tuple[dict, float]] = {}
        self._uploaded: set[str] = set()

    def _prefetch(self, key: str) -> None:
        if key in self._prepared_once:
            return
        start = self._positions[key]
        keys = [candidate for candidate in self._ordered_keys[start:start + 4]
                if candidate not in self._prepared_once]
        items = [self._client._item(self._expected, candidate) for candidate in keys]
        started = time.monotonic()
        result = self._client._post({"action": "batch",
                                     "vaultId": self._client._vault_id,
                                     "reservationId": self._reservation_id,
                                     "items": items})
        rows = result.get("objects")
        if (set(result) != {"workerOrigin", "objects"} or
                result["workerOrigin"] != self._client._worker_origin or
                not isinstance(rows, list) or len(rows) != len(keys)):
            raise MigrationError("The hosted object batch response is invalid.")
        checked = {}
        for candidate, row in zip(keys, rows):
            if not isinstance(row, dict):
                raise MigrationError("The hosted object batch response is invalid.")
            action = row.get("action")
            grants = (("grant",) if action == "head" else
                      ("putGrant", "headGrant") if action == "put_required" else ())
            if (not grants or set(row) != {"action", *grants} or
                    any(not isinstance(row[name], str) or
                        not _GRANT.fullmatch(row[name]) or len(row[name]) > 2048
                        for name in grants)):
                raise MigrationError("The hosted object batch response is invalid.")
            checked[candidate] = (row, started + 20.0)
        self._prepared.update(checked)
        self._prepared_once.update(keys)

    def _cached(self, key: str) -> Optional[dict]:
        entry = self._prepared.get(key)
        return entry[0] if entry and time.monotonic() < entry[1] else None

    def _ensure_lease(self) -> None:
        # A 55-minute reservation cannot cover a slow first backup. Renew
        # well before expiry, with fresh server-side entitlement checks. A
        # suspended process whose lease expired fails closed on renewal.
        now = time.monotonic()
        if now - self._last_renewal >= 25 * 60:
            self._client.renew(self._reservation_id, apply=True)
            self._last_renewal = time.monotonic()

    def _transport(self, method: str, key: str, grant: str) -> CapabilityHttpStore:
        size, digest = self._expected[key]
        scoped = (f"accounts/{self._client._account_id}/vaults/"
                  f"{self._client._vault_id}/{key}")

        def exact(request_method: str, request_key: str,
                  request_size: int, request_digest: str) -> str:
            if (request_method, request_key, request_size, request_digest) != (
                    method, scoped, size, digest):
                raise MigrationError("The hosted object grant does not match its inventory.")
            return grant

        return CapabilityHttpStore(
            self._client._worker_origin, self._client._account_id,
            self._client._vault_id, self._expected, exact,
            timeout=self._client._timeout,
            allow_loopback_http=self._client._allow_loopback_http)

    def _checked_metadata(self, key: str, grant: str):
        transport = self._transport("HEAD", key, grant)
        self._client._worker_attempt_counts["head"] += 1
        return transport.checked_metadata(key)

    def checked_metadata(self, key: str):
        item = self._client._item(self._expected, key)
        self._ensure_lease()
        self._prefetch(key)
        cached = self._cached(key)
        if cached is not None:
            if cached["action"] == "put_required" and key not in self._uploaded:
                return None
            grant = cached["grant"] if cached["action"] == "head" else cached["headGrant"]
            return self._checked_metadata(key, grant)
        result = self._client._post({"action": "decide",
                                     "vaultId": self._client._vault_id,
                                     "reservationId": self._reservation_id,
                                     "item": item})
        if result == {"action": "put_required"}:
            return None
        grant = self._client._grant(result, head=True)
        return self._checked_metadata(key, grant)

    def put_if_absent(self, key, source, length):
        item = self._client._item(self._expected, key)
        self._ensure_lease()
        cached = self._cached(key)
        if cached is not None and cached["action"] == "put_required":
            grant = cached["putGrant"]
        else:
            result = self._client._post({"action": "put",
                                         "vaultId": self._client._vault_id,
                                         "reservationId": self._reservation_id,
                                         "item": item})
            grant = self._client._grant(result)
        transport = self._transport("PUT", key, grant)
        bytes_attempted = self._expected[key][0]
        self._client._worker_attempt_counts["put"] += 1
        self._client._worker_attempt_counts["put_bytes"] += bytes_attempted
        try:
            transport.put_if_absent(key, source, length)
        except Exception:
            # A lost response may mean the immutable PUT succeeded. Never
            # keep treating this object as absent from a cached preflight.
            self._prepared.pop(key, None)
            raise
        self._client._worker_attempt_counts["put_confirmed"] += 1
        self._client._worker_attempt_counts["put_confirmed_bytes"] += bytes_attempted
        self._uploaded.add(key)
