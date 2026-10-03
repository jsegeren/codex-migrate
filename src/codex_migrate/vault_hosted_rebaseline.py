"""One reviewed intentional-deletion approval, never an unattended bypass.

The private report contains IDs/relative paths and content fingerprints, not
conversation bodies, titles, credentials or recovery keys. It is a local
confirmation record, not server verification or evidence of a recovery drill.
"""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Optional
import uuid

from codex_migrate.errors import MigrationError
from codex_migrate.vault_backup import _atomic_json, _helper_path, _metadata, _require_unlinked_path
from codex_migrate.vault_hosted_enrollment_client import HostedEnrollmentClient
from codex_migrate.vault_hosted_schedule import MAX_PRIOR_BYTES, SERVICE_ORIGIN, _UUID
from codex_migrate.vault_hosted_source_loss import missing_unidentified_transcripts, missing_verified_threads
from codex_migrate.vault_hosted_source_review import _inventory, _validate_prior
from codex_migrate.vault_identity import loss_warnings
from codex_migrate.vault_schedule import (
    _ensure_owned_directory, _home, _pending_update, _safe_json, _update_lock,
)


_FORMAT = "codex-vault-hosted-deletion-review"
_MAX_REPORT = 16 * 1024 * 1024
_FACTS = ("collection", "path", "size", "sha256", "thread_id", "identity_state",
          "records", "user_messages", "assistant_messages")
_HEX = re.compile(r"[0-9a-f]{64}\Z")


def _bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def catalog_digest(rows, *, prior=False):
    """Content identity, not a stat hint; titles/chunk encoding are not bodies."""
    facts = [{key: row.get(key) for key in _FACTS} for row in rows]
    facts.sort(key=lambda row: (row["collection"], row["path"]))
    domain = b"codex-vault-deletion-review/prior/v1\x00" if prior else b"codex-vault-deletion-review/source/v1\x00"
    return hashlib.sha256(domain + _bytes(facts)).hexdigest()


def _source_root(home):
    root = _home(home) / ".codex"
    _require_unlinked_path(root)
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise MigrationError("The Codex source root is unsafe.")
    return [info.st_dev, info.st_ino, info.st_uid]


def _deletions(prior, current, missing_attachments):
    if (missing_attachments or
            any(row.get("identity_state") == "needs_review" or row.get("at_risk") is True
                for row in prior + current)):
        raise MigrationError("Resolve damaged, ambiguous or incomplete history before deletion review.")
    for collections in (("active", "archived"), ("paginated",)):
        before = [row for row in prior if row["collection"] in collections]
        after = [row for row in current if row["collection"] in collections]
        if loss_warnings(before, after):
            raise MigrationError("A remaining thread shortened; deletion approval cannot clear that risk.")
        old_ids = {row.get("thread_id"): row for row in before if row.get("thread_id")}
        if any(row.get("thread_id") in old_ids and any(
                type(old_ids[row["thread_id"]].get(key)) is int and
                row.get(key, 0) < old_ids[row["thread_id"]][key]
                for key in ("size", "records", "user_messages", "assistant_messages"))
               for row in after):
            raise MigrationError("A remaining thread shortened; deletion approval cannot clear that risk.")
    # Unidentified files do not have stable thread IDs; still refuse a detected
    # shrink of a remaining same-path file rather than laundering it as deletion.
    old_paths = {(row["collection"], row["path"]): row for row in prior}
    for row in current:
        old = old_paths.get((row["collection"], row["path"]))
        if old is None or row["collection"] == "attachments":
            continue
        if (any(type(old.get(key)) is int and row.get(key, 0) < old[key]
                for key in ("records", "user_messages", "assistant_messages")) or
                row["size"] < old["size"]):
            raise MigrationError("A remaining file shortened; deletion approval cannot clear that risk.")
    missing_ids = missing_verified_threads(prior, current)
    missing_files = missing_unidentified_transcripts(prior, current)
    now_attachments = {row["path"] for row in current if row["collection"] == "attachments"}
    missing_attachments = sorted(row["path"] for row in prior if row["collection"] == "attachments"
                                 and row["path"] not in now_attachments)
    if not missing_ids and not missing_files:
        raise MigrationError("There are no supported intentional thread deletions to approve.")
    if not any(row["collection"] != "attachments" for row in current):
        raise MigrationError("An empty history requires support review, not a green replacement backup.")
    return missing_ids, missing_files, missing_attachments


@dataclass(frozen=True)
class RebaselineApproval:
    # Bytes prevent mutation after the pending run binds this exact document.
    document: bytes

    @property
    def value(self):
        return json.loads(self.document)

    @property
    def stamp(self):
        return {"reviewId": self.value["reviewId"],
                "deviceId": self.value["deviceId"],
                "digest": hashlib.sha256(self.document).hexdigest(),
                "sourceDigest": self.value["sourceDigest"],
                "baseSnapshotId": self.value["baseSnapshotId"]}

    def check_authority(self, source_home, account_id, vault_id, key_id):
        value = self.value
        if (value["sourceHome"] != str(_home(source_home)) or
                (value["accountId"], value["vaultId"], value["keyId"]) !=
                (account_id, vault_id, key_id) or
                value["sourceRoot"] != _source_root(source_home)):
            raise MigrationError("The deletion review belongs to another backup source or key.")

    def check_catalogs(self, prior, current, version, base, missing_attachments=()):
        value = self.value
        _validate_prior(prior, version)
        _validate_prior(current, 4)
        if (base != value["baseSnapshotId"] or version != value["priorVersion"] or
                catalog_digest(prior, prior=True) != value["priorDigest"] or
                catalog_digest(current) != value["sourceDigest"]):
            raise MigrationError("The source or prior backup changed; prepare a new deletion review.")
        ids, files, attachments = _deletions(prior, current, missing_attachments)
        if (ids != value["missingThreadIds"] or files != value["missingFiles"] or
                attachments != value["missingAttachments"]):
            raise MigrationError("The deletion review no longer matches the missing history.")

    def check_current(self, source_home):
        if self.value["sourceRoot"] != _source_root(source_home):
            raise MigrationError("The Codex source root changed after review.")
        current, missing = _inventory(source_home)
        if missing or catalog_digest(current) != self.value["sourceDigest"]:
            raise MigrationError("History changed after review; prepare a new deletion review.")


def _path(home, review_id):
    if not isinstance(review_id, str) or not _UUID.fullmatch(review_id):
        raise MigrationError("The deletion review ID is invalid.")
    return home / "Library/Application Support/Codex Vault/hosted/deletion-reviews" / (review_id + ".json")


def load_rebaseline(source_home: str, review_id: str) -> RebaselineApproval:
    """Read only the exact owner-private record; no arbitrary input filename."""
    home = _home(source_home)
    path = _path(home, review_id)
    _require_unlinked_path(path)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                    info.st_nlink != 1 or info.st_mode & 0o077 or info.st_size > _MAX_REPORT):
                raise MigrationError("The deletion review is not owner-private.")
            value = json.loads(stream.read(_MAX_REPORT + 1))
        keys = {"format", "version", "reviewId", "deviceId", "accountId", "vaultId", "keyId",
                "sourceHome", "baseSnapshotId", "priorVersion", "priorDigest", "sourceDigest",
                "missingThreadIds", "missingFiles", "missingAttachments", "sourceRoot"}
        if (not isinstance(value, dict) or set(value) != keys or value["format"] != _FORMAT or
                type(value["version"]) is not int or value["version"] != 1 or
                value["reviewId"] != review_id or value["sourceHome"] != str(home) or
                any(not isinstance(value[key], str) or not _UUID.fullmatch(value[key])
                    for key in ("reviewId", "deviceId", "accountId", "vaultId", "keyId", "baseSnapshotId")) or
                type(value["priorVersion"]) is not int or value["priorVersion"] not in (2, 3, 4) or
                any(not isinstance(value[key], str) or not _HEX.fullmatch(value[key])
                    for key in ("priorDigest", "sourceDigest")) or
                not isinstance(value["sourceRoot"], list) or len(value["sourceRoot"]) != 3 or
                any(type(entry) is not int or entry < 0 for entry in value["sourceRoot"]) or
                not isinstance(value["missingThreadIds"], list) or
                not isinstance(value["missingFiles"], list) or
                not isinstance(value["missingAttachments"], list) or
                sum(len(value[key]) for key in ("missingThreadIds", "missingFiles", "missingAttachments")) > 100_000):
            raise MigrationError("The deletion review binding is invalid.")
        # Actual entries are checked against fresh validated catalogs before
        # any staging. Neither this file nor its ID alone authorizes a backup.
        return RebaselineApproval(_bytes(value))
    except (OSError, ValueError, UnicodeError):
        raise MigrationError("The deletion review could not be read safely.") from None


def review_consumed(source_home, review_id):
    path = _path(_home(source_home), review_id).with_suffix(".receipt.json")
    _require_unlinked_path(path, allow_missing_leaf=True)
    return os.path.lexists(path)


def consume_review(source_home, state, outcome):
    """Terminal receipt before pending cleanup; no snapshot/chunk deletion."""
    binding = state.get("deletionReview")
    if binding is None:
        return
    if outcome not in ("published", "abandoned"):
        raise MigrationError("The deletion-review outcome is invalid.")
    path = _path(_home(source_home), binding["reviewId"]).with_suffix(".receipt.json")
    value = {"format": "codex-vault-hosted-deletion-receipt", "version": 1,
             "accountId": state["accountId"], "vaultId": state["vaultId"], "keyId": state["keyId"],
             "review": binding, "snapshotId": state["snapshotId"], "outcome": outcome}
    _require_unlinked_path(path, allow_missing_leaf=True)
    if os.path.lexists(path):
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                info.st_nlink != 1 or info.st_mode & 0o077):
            raise MigrationError("The consumed deletion receipt is not owner-private.")
        if _safe_json(path) != value:
            raise MigrationError("The consumed deletion review conflicts with this run.")
        return
    _ensure_owned_directory(_home(source_home), path.parent)
    _atomic_json(path, value)


def prepare_rebaseline(source_home: str, device_id: str, metadata_path: str, *,
                       crypto_helper: Optional[str] = None, apply: bool = False) -> dict:
    """Save the complete deletion list. This does not approve or upload it."""
    if apply is not True:
        raise MigrationError("Saving a private deletion review requires explicit confirmation.")
    if not isinstance(device_id, str) or not _UUID.fullmatch(device_id):
        raise MigrationError("The hosted backup device is invalid.")
    if not isinstance(metadata_path, str) or not Path(metadata_path).is_absolute():
        raise MigrationError("Select absolute existing Vault metadata.")
    home = _home(source_home)
    metadata = _safe_json(Path(metadata_path))
    key_id = _metadata(metadata)
    if type(metadata["version"]) is not int or "recovery_mode" in metadata:
        raise MigrationError("This review requires an individual Vault key.")
    helper = str(_helper_path(crypto_helper))
    with _update_lock(str(home), nonblocking=True) as marker:
        if _pending_update(marker) is not None:
            raise MigrationError("Wait for the app update before preparing a deletion review.")
        try:
            upload, recovery = HostedEnrollmentClient(SERVICE_ORIGIN).backup_clients(
                device_id, crypto_helper=helper)
            pointer = recovery._latest()
            account, worker, latest = pointer
            if (account != upload._account_id or worker != upload._worker_origin or latest is None or
                    latest.get("sourceCoverage") != "complete"):
                raise MigrationError("A complete bound previous backup is required.")
            base, prior, version = recovery.prior_catalog(
                key_id=key_id, crypto_helper=helper, max_bytes=MAX_PRIOR_BYTES,
                expected_snapshot_id=latest["snapshotId"], expected_account_id=account,
                include_version=True)
            if base != latest["snapshotId"] or version not in (2, 3, 4):
                raise MigrationError("The previous backup is unbound or lacks loss metadata.")
            _validate_prior(prior, version)
            root_before = _source_root(str(home))
            current, missing = _inventory(str(home))
            _validate_prior(current, 4)
            ids, files, attachments = _deletions(prior, current, missing)
            if recovery._latest() != pointer or root_before != _source_root(str(home)):
                raise MigrationError("The previous backup changed during review.")
            value = {"format": _FORMAT, "version": 1, "reviewId": str(uuid.uuid4()),
                     "deviceId": device_id, "accountId": account, "vaultId": upload._vault_id,
                     "keyId": key_id, "sourceHome": str(home), "baseSnapshotId": base,
                     "priorVersion": version, "priorDigest": catalog_digest(prior, prior=True),
                     "sourceDigest": catalog_digest(current), "missingThreadIds": ids,
                     "missingFiles": files, "missingAttachments": attachments, "sourceRoot": root_before}
            if len(_bytes(value)) > _MAX_REPORT:
                raise MigrationError("The complete review is too large; contact support.")
            path = _path(home, value["reviewId"])
            _ensure_owned_directory(home, path.parent)
            _atomic_json(path, value)
        except Exception:
            raise MigrationError("Intentional-deletion review could not be verified. No backup or "
                                 "Codex data was changed; contact joshua@segeren.com.") from None
    return {"review_id": value["reviewId"], "review_file": str(path), "saved": True,
            "missing_verified_threads": len(ids), "missing_unidentified_transcripts": len(files),
            "missing_attachments": len(attachments),
            "rebaseline_authorized": False, "automatic_protection_verified": False}
