"""Retryable dark hosted-only backup of this Mac's live Codex transcripts.

No full local ciphertext Vault is required. The small owner-only state records
opaque IDs before network access, while the chunk journal records exact remote
checks before temporary ciphertext can be discarded. Only the service's
published receipt may mark the run protected.
"""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import stat
from typing import Iterator, Optional
import uuid

from codex_migrate.errors import MigrationError
from codex_migrate.vault_backup import (
    _atomic_json, _fsync_directory, _helper_path, _metadata,
    _read_json, _require_unlinked_path,
)
from codex_migrate.vault_hosted_chunk_journal import HostedChunkJournal
from codex_migrate.vault_hosted_live_stage import stage_reserved_hosted_snapshot
from codex_migrate.vault_hosted_no_change import unchanged_published_history
from codex_migrate.vault_hosted_recovery_client import HostedRecoveryClient
from codex_migrate.vault_hosted_source_index import promote_source_facts
from codex_migrate.vault_hosted_upload_client import HostedUploadClient, _UUID
from codex_migrate.vault_schedule import _ensure_owned_directory, _home


_FORMAT = "codex-vault-hosted-live-run"


class HostedLiveBackupRun:
    """One pending hosted snapshot per account/Vault on this Mac.

    This remains dark: enrollment, billing, a LaunchAgent, buyer status and
    clean-Mac R2 recovery are separate release gates.
    """

    def __init__(self, upload: HostedUploadClient, recovery: HostedRecoveryClient,
                 source_home: str):
        if (not isinstance(upload, HostedUploadClient) or
                not isinstance(recovery, HostedRecoveryClient) or
                upload._vault_id != recovery._vault_id or
                upload._service_origin != recovery._origin or
                upload._device_token != recovery._device_token):
            raise MigrationError("The hosted backup clients do not match.")
        self._upload = upload
        self._recovery = recovery
        self._home = _home(source_home)
        self._directory = self._home / (
            "Library/Application Support/Codex Vault/hosted/live-" + upload._vault_id)
        self._state = self._directory / "run.json"
        self._lock = self._directory / "run.lock"

    @contextmanager
    def _locked(self) -> Iterator[None]:
        _ensure_owned_directory(self._home, self._directory)
        if self._directory.lstat().st_mode & 0o077:
            raise MigrationError("The hosted backup state folder is not private.")
        try:
            descriptor = os.open(self._lock,
                                 os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        except OSError as error:
            raise MigrationError("The hosted backup state is unavailable.") from error
        try:
            info = os.fstat(descriptor)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                    info.st_nlink != 1 or info.st_mode & 0o077):
                raise MigrationError("The hosted backup lock is unsafe.")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            os.close(descriptor)

    def _pending(self) -> Optional[dict]:
        _require_unlinked_path(self._state, allow_missing_leaf=True)
        try:
            descriptor = os.open(self._state,
                                 os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return None
        except OSError as error:
            raise MigrationError("The hosted backup state is unavailable.") from error
        try:
            with os.fdopen(descriptor, "rb") as stream:
                info = os.fstat(stream.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                        info.st_nlink != 1 or info.st_mode & 0o077 or
                        info.st_size > 8192):
                    raise MigrationError("The hosted backup state is unsafe.")
                value = json.load(stream)
        except (OSError, UnicodeError, ValueError) as error:
            raise MigrationError("The hosted backup state is invalid.") from error
        common = {"format", "version", "accountId", "vaultId", "reservationId",
                  "snapshotId", "keyId", "phase"}
        version = value.get("version") if isinstance(value, dict) else None
        if version == 2 and type(version) is int:
            common.add("deletionReview")
            binding = value.get("deletionReview")
            if (not isinstance(binding, dict) or set(binding) != {
                    "reviewId", "deviceId", "digest", "sourceDigest", "baseSnapshotId"} or
                    any(not isinstance(binding[key], str) or not _UUID.fullmatch(binding[key])
                        for key in ("reviewId", "deviceId", "baseSnapshotId")) or
                    any(not isinstance(binding[key], str) or not re.fullmatch(r"[0-9a-f]{64}", binding[key])
                        for key in ("digest", "sourceDigest")) or
                    value.get("phase") != "reserving" and
                    value.get("baseSnapshotId") != binding["baseSnapshotId"]):
                raise MigrationError("The pending deletion review is invalid.")
        if (not isinstance(value, dict) or value.get("format") != _FORMAT or
                version not in (1, 2) or type(version) is not int or
                value.get("accountId") != self._upload._account_id or
                value.get("vaultId") != self._upload._vault_id or
                any(not isinstance(value.get(key), str) or
                    not _UUID.fullmatch(value[key]) for key in
                    ("reservationId", "snapshotId", "keyId")) or
                not ((value.get("phase") == "reserving" and set(value) == common) or
                     (value.get("phase") in ("active", "cleanup_pending") and
                      set(value) == common | {"baseSnapshotId"} and
                      (value["baseSnapshotId"] is None or
                       isinstance(value["baseSnapshotId"], str) and
                       _UUID.fullmatch(value["baseSnapshotId"]))))):
            raise MigrationError("The hosted backup state does not match this Vault.")
        return value

    @staticmethod
    def _match_pending(state, *, expected_key_id=None, expected_reservation_id=None):
        for expected in (expected_key_id, expected_reservation_id):
            if expected is not None and (not isinstance(expected, str) or not _UUID.fullmatch(expected)):
                raise MigrationError("The pending upload confirmation is invalid.")
        if (state is not None and expected_key_id is not None and state["keyId"] != expected_key_id or
                expected_reservation_id is not None and
                (state is None or state["reservationId"] != expected_reservation_id)):
            raise MigrationError("The pending upload changed; inspect it again before continuing.")

    def pending(self, *, expected_key_id=None) -> Optional[dict]:
        """Expose opaque state only; never infer protection from a local file."""
        self._match_pending(None, expected_key_id=expected_key_id)
        try:
            info = self._directory.lstat()
        except FileNotFoundError:
            return None
        _require_unlinked_path(self._directory)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or
                info.st_mode & 0o077):
            raise MigrationError("The hosted backup state folder is not private.")
        state = self._pending()
        self._match_pending(state, expected_key_id=expected_key_id)
        return None if state is None else {
            "reservationId": state["reservationId"],
            "snapshotId": state["snapshotId"], "phase": state["phase"]}

    def _confirmed_publication(self, snapshot_id: str, object_count: int,
                               source_coverage: Optional[str] = None) -> dict:
        published = self._recovery.published_snapshot(
            snapshot_id, expected_account_id=self._upload._account_id,
            expected_worker_origin=self._upload._worker_origin)
        if (published["totalObjects"] != object_count or
                source_coverage is not None and
                published["sourceCoverage"] != source_coverage):
            raise MigrationError("The hosted publication receipt does not match its version.")
        return published

    def back_up_live_history(self, metadata: dict, *, crypto_helper: str,
                             max_prior_bytes: int, apply: bool = False,
                             deletion_review_id: Optional[str] = None,
                             deletion_device_id: Optional[str] = None) -> dict:
        from codex_migrate.vault_hosted_rebaseline import consume_review, review_consumed
        if apply is not True:
            raise MigrationError("Hosted backup changes require explicit confirmation.")
        if type(max_prior_bytes) is not int or not 0 < max_prior_bytes <= 1_000_000_000:
            raise MigrationError("The hosted prior-catalog size limit is invalid.")
        _helper_path(crypto_helper)
        key_id = _metadata(metadata)
        if ((deletion_review_id is None) != (deletion_device_id is None) or
                deletion_review_id is not None and any(
                    not isinstance(value, str) or not _UUID.fullmatch(value)
                    for value in (deletion_review_id, deletion_device_id))):
            raise MigrationError("The intentional-deletion review ID is invalid.")
        with self._locked():
            state = self._pending()
            if state is not None and (
                    (state.get("deletionReview", {}).get("reviewId"),
                     state.get("deletionReview", {}).get("deviceId")) !=
                    (deletion_review_id, deletion_device_id)):
                raise MigrationError("Resume the pending upload with its exact deletion confirmation, "
                                     "or abandon it safely. Ordinary backup cannot approve deletion.")
            if state is not None and state["phase"] == "cleanup_pending":
                raise MigrationError(
                    "The abandoned hosted upload needs verified cleanup before another backup.")
            if state is None:
                approval = None
                if deletion_review_id is not None:
                    if review_consumed(str(self._home), deletion_review_id):
                        raise MigrationError("This deletion review was consumed; it cannot be reused.")
                    approval = self._checked_approval(deletion_review_id, key_id,
                                                     crypto_helper, max_prior_bytes, deletion_device_id)
                unchanged = None if approval is not None else unchanged_published_history(
                    str(self._home), self._directory, self._recovery,
                    account_id=self._upload._account_id,
                    vault_id=self._upload._vault_id, key_id=key_id,
                    crypto_helper=crypto_helper, max_prior_bytes=max_prior_bytes)
                if unchanged is not None:
                    return unchanged
                state = {"format": _FORMAT, "version": 1,
                         "accountId": self._upload._account_id,
                         "vaultId": self._upload._vault_id,
                         "reservationId": str(uuid.uuid4()),
                         "snapshotId": str(uuid.uuid4()),
                         "keyId": key_id, "phase": "reserving"}
                if approval is not None:
                    state.update(version=2, deletionReview=approval.stamp)
                # Persist the random ID before the first network call. If its
                # response is lost, the exact ID can be safely retried.
                _atomic_json(self._state, state)
            elif state["keyId"] != key_id:
                raise MigrationError("A different hosted key has a pending upload.")
            reservation_id = state["reservationId"]
            snapshot_id = state["snapshotId"]
            if state["phase"] == "reserving":
                observed_id, base = self._upload.reserve_with_base(
                    reservation_id=reservation_id, apply=True)
                if observed_id != reservation_id:
                    raise MigrationError("The hosted upload reservation changed.")
                if state.get("deletionReview") is not None and base != state["deletionReview"]["baseSnapshotId"]:
                    raise MigrationError("The backup base changed after deletion review; abandon this run safely.")
                state = {**state, "phase": "active", "baseSnapshotId": base}
                _atomic_json(self._state, state, replace=True)
            else:
                status = self._upload.reservation_receipt(reservation_id)
                if status["state"] == "published":
                    if status["snapshotId"] != snapshot_id:
                        raise MigrationError(
                            "The hosted publication does not match the pending snapshot.")
                    published = self._confirmed_publication(
                        snapshot_id, status["verifiedObjectCount"])
                    # A lost publish reply also loses the local risk count.
                    # Reopen this exact encrypted manifest instead of treating
                    # absent loss evidence as zero, or relying on server
                    # coverage alone (the server cannot read conversations).
                    opened = self._recovery.prior_catalog(
                        key_id=key_id, crypto_helper=crypto_helper,
                        max_bytes=max_prior_bytes, expected_snapshot_id=snapshot_id,
                        expected_account_id=self._upload._account_id,
                        **({} if state.get("deletionReview") is None else {"include_version": True}))
                    observed, catalog = opened[:2]
                    if observed != snapshot_id:
                        raise MigrationError("The hosted recovery catalog changed on retry.")
                    self._check_approved_publication(state, catalog, opened[2] if len(opened) == 3 else None)
                    if state.get("deletionReview") is not None and published["sourceCoverage"] != "complete":
                        raise MigrationError("The approved publication has incomplete coverage.")
                    at_risk = {
                        (item["collection"], item.get("thread_id") or item["path"])
                        for item in catalog if item["collection"] != "attachments"
                        and item.get("at_risk") is not False
                    }
                    consume_review(str(self._home), state, "published")
                    self._finish(snapshot_id)
                    return {"snapshotId": snapshot_id,
                            "verifiedObjectCount": status["verifiedObjectCount"],
                            "sourceCoverage": published["sourceCoverage"],
                            "atRiskThreads": len(at_risk)}
                if status["state"] != "active":
                    raise MigrationError("The hosted upload needs cleanup or review.")
                observed_id, base = self._upload.reserve_with_base(
                    reservation_id=reservation_id, apply=True)
                if observed_id != reservation_id or base != state["baseSnapshotId"]:
                    raise MigrationError("The hosted reservation base changed on retry.")

            approval = None
            if state.get("deletionReview") is not None:
                if review_consumed(str(self._home), deletion_review_id):
                    raise MigrationError("This deletion review was consumed; finish its cleanup instead of resuming.")
                approval = self._checked_approval(deletion_review_id, key_id,
                                                 crypto_helper, max_prior_bytes, deletion_device_id)
                if approval.stamp != state["deletionReview"]:
                    raise MigrationError("The deletion approval changed while its upload was pending.")

            journal_dir = self._directory / ("snapshot-" + snapshot_id)
            _ensure_owned_directory(self._home, journal_dir)
            with HostedChunkJournal(
                    journal_dir, account_id=self._upload._account_id,
                    vault_id=self._upload._vault_id,
                    reservation_id=reservation_id, snapshot_id=snapshot_id,
                    key_id=key_id, base_snapshot_id=state["baseSnapshotId"]) as journal:
                staged = stage_reserved_hosted_snapshot(
                    str(self._home), metadata, journal, self._upload,
                    self._recovery, crypto_helper=crypto_helper,
                    max_prior_bytes=max_prior_bytes, apply=True,
                    **({} if approval is None else {"deletion_approval": approval}))
                if approval is not None:
                    if staged.at_risk_threads != 0:
                        raise MigrationError("The reviewed backup has remaining source risk.")
                    approval.check_current(str(self._home))
                    self._recovery.published_snapshot(approval.value["baseSnapshotId"],
                        expected_account_id=self._upload._account_id,
                        expected_worker_origin=self._upload._worker_origin)
                result = self._upload.publish_hosted_stage(
                    reservation_id, staged, apply=True)
            if result.get("snapshotId") != snapshot_id:
                raise MigrationError("The hosted publication did not match the pending snapshot.")
            if result.get("sourceCoverage") not in ("complete", "needs_attention"):
                raise MigrationError("The hosted publication coverage is invalid.")
            self._confirmed_publication(
                snapshot_id, result.get("verifiedObjectCount"),
                result.get("sourceCoverage"))
            if approval is not None:
                observed, catalog, version = self._recovery.prior_catalog(
                    key_id=key_id, crypto_helper=crypto_helper, max_bytes=max_prior_bytes,
                    expected_snapshot_id=snapshot_id, expected_account_id=self._upload._account_id,
                    include_version=True)
                if observed != snapshot_id:
                    raise MigrationError("The reviewed publication changed during confirmation.")
                self._check_approved_publication(state, catalog, version)
                if result["sourceCoverage"] != "complete":
                    raise MigrationError("The approved publication has incomplete coverage.")
                self._recovery.published_snapshot(approval.value["baseSnapshotId"],
                    expected_account_id=self._upload._account_id,
                    expected_worker_origin=self._upload._worker_origin)
            consume_review(str(self._home), state, "published")
            self._finish(snapshot_id)
            return result

    def _checked_approval(self, review_id, key_id, helper, limit, device_id):
        from codex_migrate.vault_hosted_rebaseline import load_rebaseline
        approval = load_rebaseline(str(self._home), review_id)
        approval.check_authority(str(self._home), self._upload._account_id,
                                 self._upload._vault_id, key_id)
        if approval.value["deviceId"] != device_id:
            raise MigrationError("The deletion review belongs to another enrolled device.")
        account, worker, latest = self._recovery._latest()
        if (account != self._upload._account_id or worker != self._upload._worker_origin or
                latest is None or latest.get("sourceCoverage") != "complete" or
                latest["snapshotId"] != approval.value["baseSnapshotId"]):
            raise MigrationError("The backup baseline changed; prepare a new deletion review.")
        base, prior, version = self._recovery.prior_catalog(
            key_id=key_id, crypto_helper=helper, max_bytes=limit,
            expected_snapshot_id=latest["snapshotId"], expected_account_id=account,
            include_version=True)
        from codex_migrate.vault_hosted_source_review import _inventory
        current, missing = _inventory(str(self._home))
        approval.check_catalogs(prior, current, version, base, missing)
        return approval

    @staticmethod
    def _check_approved_publication(state, catalog, version):
        from codex_migrate.vault_hosted_rebaseline import catalog_digest
        binding = state.get("deletionReview")
        if binding is not None:
            from codex_migrate.vault_hosted_source_review import _validate_prior
            if version not in (2, 3, 4) or type(version) is not int:
                raise MigrationError("The approved publication format is invalid.")
            _validate_prior(catalog, version)
        if binding is not None and (catalog_digest(catalog) != binding["sourceDigest"] or
                any(row.get("at_risk") is not False for row in catalog if row["collection"] != "attachments")):
            raise MigrationError("The published backup does not match the approved content.")

    def cleanup_status(self) -> Optional[str]:
        """Report service state; local quarantine alone never releases quota."""
        state = self.pending()
        return (None if state is None else
                self._upload.reservation_status(state["reservationId"]))

    def abandon_pending(self, *, apply: bool = False,
                        expected_key_id=None, expected_reservation_id=None) -> str:
        """Quarantine a failed run; retire its journal only after release.

        Keep the owner-only journal while the provider cleans up. After the
        service confirms release, remove only this run's recognized scratch.
        Neither a lost ACK nor an unexpected local file authorizes a new run.
        """
        from codex_migrate.vault_hosted_rebaseline import consume_review
        if apply is not True:
            raise MigrationError("Hosted backup changes require explicit confirmation.")
        # Validate before opening state or reaching the provider. The exact-ID
        # interface is for a separate customer/operator confirmation, not a
        # generic "cancel whatever is pending" action.
        self._match_pending(None, expected_key_id=expected_key_id)
        if expected_reservation_id is not None and (
                not isinstance(expected_reservation_id, str) or
                not _UUID.fullmatch(expected_reservation_id)):
            raise MigrationError("The pending upload confirmation is invalid.")
        with self._locked():
            state = self._pending()
            self._match_pending(state, expected_key_id=expected_key_id,
                                expected_reservation_id=expected_reservation_id)
            if state is None:
                return "none"
            reservation_id = state["reservationId"]
            receipt = self._upload.reservation_receipt(reservation_id)
            if receipt["state"] == "published":
                if expected_reservation_id is not None:
                    raise MigrationError("This upload published. Resume its exact backup verification; "
                                         "published backups cannot be abandoned.")
                if (state["phase"] == "cleanup_pending" or
                        receipt["snapshotId"] != state["snapshotId"]):
                    raise MigrationError("The hosted publication conflicts with abandonment.")
                self._confirmed_publication(
                    state["snapshotId"], receipt["verifiedObjectCount"])
                if state.get("deletionReview") is not None:
                    raise MigrationError("The reviewed backup published; resume its exact confirmation "
                                         "to verify it instead of abandoning it.")
                self._finish(state["snapshotId"])
                return "published"
            if receipt["state"] == "active":
                if state["phase"] == "cleanup_pending":
                    raise MigrationError("The abandoned hosted upload is active again.")
                consume_review(str(self._home), state, "abandoned")
                try:
                    self._upload.abandon(reservation_id, apply=True)
                    receipt = {"state": "cleanup_pending"}
                except MigrationError:
                    # The ACK may be lost after quarantine. Read the exact
                    # reservation instead of issuing a second blind action.
                    receipt = self._upload.reservation_receipt(reservation_id)
                    if receipt["state"] not in ("cleanup_pending", "released"):
                        raise MigrationError(
                            "The hosted upload could not be confirmed abandoned.") from None
            if receipt["state"] not in ("cleanup_pending", "released"):
                raise MigrationError("The hosted upload needs manual review.")
            consume_review(str(self._home), state, "abandoned")
            if state["phase"] != "cleanup_pending":
                state = {**state, "phase": "cleanup_pending",
                         "baseSnapshotId": state.get("baseSnapshotId", state.get("deletionReview", {}).get("baseSnapshotId"))}
                _atomic_json(self._state, state, replace=True)
            if receipt["state"] == "cleanup_pending":
                return "cleanup_pending"
            self._retire_published_journal(state["snapshotId"], released=True)
            try:
                self._state.unlink()
                _fsync_directory(self._directory)
            except OSError as error:
                raise MigrationError("The released hosted backup journal remains.") from error
            return "released"

    @staticmethod
    def _private_directory(path: Path) -> None:
        info = path.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or
                info.st_mode & 0o077):
            raise MigrationError("The published hosted journal folder is unsafe.")

    @staticmethod
    def _private_file(path: Path) -> None:
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                info.st_nlink != 1 or info.st_mode & 0o077):
            raise MigrationError("The published hosted journal file is unsafe.")

    def _retire_published_journal(self, snapshot_id: str, *, released: bool = False) -> None:
        """Remove only recognized scratch after publication or verified release.

        An unexpected file, especially an unreceipted ciphertext chunk, is
        retained for review rather than guessed to be disposable. A partial
        cleanup is retryable because the run marker is removed last.
        """
        state = self._pending()
        if (state is None or state["phase"] != (
                "cleanup_pending" if released else "active") or
                state["snapshotId"] != snapshot_id):
            raise MigrationError("The hosted run identity changed before cleanup.")
        root = self._directory / ("snapshot-" + snapshot_id)
        _require_unlinked_path(root, allow_missing_leaf=True)
        try:
            self._private_directory(root)
        except FileNotFoundError:
            return  # A prior post-publication cleanup may have reached this point.
        header = root / "journal.json"
        if os.path.lexists(header):
            self._private_file(header)
            expected = {
                "format": "codex-vault-hosted-chunk-journal", "version": 2,
                "accountId": state["accountId"], "vaultId": state["vaultId"],
                "reservationId": state["reservationId"],
                "snapshotId": snapshot_id, "keyId": state["keyId"],
                "baseSnapshotId": state["baseSnapshotId"],
            }
            if _read_json(header) != expected:
                raise MigrationError("The published hosted journal belongs to another run.")
        allowed_files = {"journal.json", "journal.lock", "chunks.jsonl",
                         "manifest-binding.json", "snapshot-time.json", "vault.json",
                         "source-index-candidate.json"}
        file_paths = []
        directory_paths = []
        for child in root.iterdir():
            if child.name in allowed_files:
                self._private_file(child)
                file_paths.append(child)
            elif child.name in ("manifests", "refs"):
                self._private_directory(child)
                expected = (snapshot_id + ".cvmanifest" if child.name == "manifests"
                            else snapshot_id + ".json")
                for nested in child.iterdir():
                    if nested.name != expected:
                        raise MigrationError("The published hosted journal has unknown files.")
                    self._private_file(nested)
                    file_paths.append(nested)
                directory_paths.append(child)
            elif child.name == "scratch":
                self._private_directory(child)
                for prefix in child.iterdir():
                    if not re.fullmatch(r"[0-9a-f]{2}", prefix.name):
                        raise MigrationError("The published hosted scratch is not empty.")
                    self._private_directory(prefix)
                    for chunk in prefix.iterdir():
                        if not released:
                            raise MigrationError("The published hosted scratch is not empty.")
                        if not re.fullmatch(r"[0-9a-f]{62}\.cvchunk", chunk.name):
                            raise MigrationError("The hosted scratch has unknown files.")
                        self._private_file(chunk)
                        file_paths.append(chunk)
                    directory_paths.append(prefix)
                directory_paths.append(child)
            else:
                raise MigrationError("The published hosted journal has unknown files.")
        try:
            for path in file_paths:
                path.unlink()
            for path in directory_paths:
                path.rmdir()
            root.rmdir()
            _fsync_directory(self._directory)
        except OSError as error:
            raise MigrationError("The published hosted journal needs local cleanup.") from error

    def _finish(self, snapshot_id: str) -> None:
        state = self._pending()
        if state is None or state["snapshotId"] != snapshot_id:
            raise MigrationError("The hosted publication changed before source-index promotion.")
        promote_source_facts(self._directory, state)
        try:
            self._retire_published_journal(snapshot_id)
        except OSError as error:
            raise MigrationError("The published hosted journal needs local cleanup.") from error
        try:
            self._state.unlink()
            _fsync_directory(self._directory)
        except OSError as error:
            raise MigrationError("The hosted backup published but its journal remains.") from error
