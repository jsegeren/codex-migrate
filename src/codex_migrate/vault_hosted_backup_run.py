"""Owner-only journal for retrying one dark hosted Vault upload.

The journal contains opaque IDs only. It is not a backup receipt and never
contains a bearer, recovery key, object path, or conversation content.
"""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import stat
from typing import Iterator, Optional
import uuid

from codex_migrate.errors import MigrationError
from codex_migrate.vault_backup import (
    _atomic_json, _fsync_directory, _require_unlinked_path,
)
from codex_migrate.vault_hosted_upload_client import HostedUploadClient, _UUID
from codex_migrate.vault_remote_inventory import encrypted_snapshot_inventory
from codex_migrate.vault_schedule import _ensure_owned_directory, _home


_FORMAT = "codex-vault-hosted-upload"


class HostedBackupRun:
    """Resume only the same snapshot and reservation until publication.

    This sandbox adapter does not create snapshots, schedules, or billing.
    """

    def __init__(self, client: HostedUploadClient, source_home: str):
        if not isinstance(client, HostedUploadClient):
            raise MigrationError("The hosted backup client is invalid.")
        self._client = client
        self._home = _home(source_home)
        self._directory = self._home / "Library/Application Support/Codex Vault/hosted"
        name = "upload-" + client._vault_id
        self._journal = self._directory / (name + ".json")
        self._lock_path = self._directory / (name + ".lock")

    @contextmanager
    def _locked(self) -> Iterator[None]:
        _ensure_owned_directory(self._home, self._directory)
        if self._directory.lstat().st_mode & 0o077:
            raise MigrationError("The hosted backup state folder is not private.")
        try:
            descriptor = os.open(self._lock_path,
                                 os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        except OSError as error:
            raise MigrationError("The hosted backup state is unavailable.") from error
        try:
            info = os.fstat(descriptor)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_nlink != 1 or info.st_mode & 0o077):
                raise MigrationError("The hosted backup lock is unsafe.")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
            except OSError as error:
                raise MigrationError("The hosted backup state is unavailable.") from error
            yield
        finally:
            os.close(descriptor)

    def _pending(self) -> Optional[dict]:
        try:
            descriptor = os.open(self._journal,
                                 os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return None
        except OSError as error:
            raise MigrationError("The hosted backup journal is unavailable.") from error
        try:
            with os.fdopen(descriptor, "rb") as stream:
                info = os.fstat(stream.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                        or info.st_nlink != 1 or info.st_mode & 0o077
                        or info.st_size > 1024):
                    raise MigrationError("The hosted backup journal is unsafe.")
                raw = stream.read(1025)
                if len(raw) > 1024:
                    raise MigrationError("The hosted backup journal is unsafe.")
        except OSError as error:
            raise MigrationError("The hosted backup journal is unavailable.") from error
        try:
            value = json.loads(raw)
        except (UnicodeError, ValueError):
            raise MigrationError("The hosted backup journal is invalid.") from None
        common = {"format", "version", "accountId", "vaultId", "snapshotId",
                  "reservationId"}
        if (not isinstance(value, dict) or
                (set(value) != common or value.get("version") != 1) and
                (set(value) != common | {"state"} or value.get("version") != 2 or
                 value.get("state") not in ("reserving", "cleanup_pending")) or
                value["format"] != _FORMAT
                or type(value["version"]) is not int
                or value["accountId"] != self._client._account_id
                or value["vaultId"] != self._client._vault_id
                or any(not isinstance(value[key], str) or not _UUID.fullmatch(value[key])
                       for key in ("snapshotId", "reservationId"))):
            raise MigrationError("The hosted backup journal does not match this account and Vault.")
        return value

    def pending(self) -> Optional[dict]:
        """Return opaque pending IDs, never a protected-backup claim."""
        if not self._directory.exists():
            return None
        _require_unlinked_path(self._directory)
        info = self._directory.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077):
            raise MigrationError("The hosted backup state folder is not private.")
        state = self._pending()
        return None if state is None else {
            "snapshotId": state["snapshotId"],
            "reservationId": state["reservationId"],
            **({"state": state["state"]} if state["version"] == 2 else {}),
        }

    def cleanup_status(self) -> Optional[str]:
        """Read the server's state; a local quarantine is not quota release."""
        state = self.pending()
        return (None if state is None else
                self._client.reservation_status(state["reservationId"]))

    def back_up_snapshot(self, vault: str, *, snapshot: str = "latest",
                         crypto_helper: Optional[str] = None,
                         apply: bool = False) -> dict:
        if apply is not True:
            raise MigrationError("Hosted backup changes require explicit confirmation.")
        with self._locked():
            state = self._pending()
            if (state is not None and state["version"] == 2 and
                    state["state"] == "cleanup_pending"):
                if self._client.reservation_status(state["reservationId"]) != "released":
                    raise MigrationError(
                        "The abandoned hosted upload is awaiting verified cleanup.")
                try:
                    self._journal.unlink()
                    _fsync_directory(self._directory)
                except OSError as error:
                    raise MigrationError("The released hosted upload journal remains.") from error
                state = None
            # A newer local snapshot may become "latest" while an interrupted
            # upload is waiting. Finish the pinned snapshot before starting a
            # different one; never abandon its reservation implicitly.
            selected_snapshot = (state["snapshotId"] if state is not None
                                 and snapshot == "latest" else snapshot)
            inventory = encrypted_snapshot_inventory(
                vault, snapshot=selected_snapshot, crypto_helper=crypto_helper)
            if state is not None and state["snapshotId"] != inventory.snapshot_id:
                raise MigrationError(
                    "A different hosted snapshot is pending; review it before starting another.")
            if state is None:
                state = {"format": _FORMAT, "version": 2,
                         "accountId": self._client._account_id,
                         "vaultId": self._client._vault_id,
                         "snapshotId": inventory.snapshot_id,
                         "reservationId": str(uuid.uuid4()),
                         "state": "reserving"}
                # Save the chosen ID before calling the service. A lost
                # response or process crash retries this exact reservation.
                _atomic_json(self._journal, state)
            if state["version"] == 2 and state["state"] == "reserving":
                reservation_id, _ = self._client.reserve_with_base(
                    reservation_id=state["reservationId"], apply=True)
                if reservation_id != state["reservationId"]:
                    raise MigrationError("The hosted upload reservation changed.")
                state = {key: value for key, value in state.items() if key != "state"}
                state["version"] = 1
                _atomic_json(self._journal, state, replace=True)
            result = self._client.back_up_snapshot(
                vault, reservation_id=state["reservationId"],
                snapshot=state["snapshotId"],
                crypto_helper=crypto_helper, apply=True)
            if result.get("snapshotId") != state["snapshotId"]:
                raise MigrationError("The hosted publication did not match the pending snapshot.")
            try:
                self._journal.unlink()
                _fsync_directory(self._directory)
            except OSError as error:
                raise MigrationError("The hosted backup published but its journal remains.") from error
            return result

    def abandon_pending(self, *, apply: bool = False) -> bool:
        """Stop retrying only after the service quarantines the exact reservation.

        This does not claim that remote objects are deleted or quota is free.
        If the response is lost, keep the journal so the same abandon can be
        safely retried; the server operation is idempotent.
        """
        if apply is not True:
            raise MigrationError("Hosted backup changes require explicit confirmation.")
        with self._locked():
            state = self._pending()
            if state is None:
                return False
            if state["version"] == 2:
                return True
            try:
                self._client.abandon(state["reservationId"], apply=True)
            except MigrationError:
                # The ACK may be lost after the service committed quarantine,
                # and cleanup may already have completed before this retry.
                if self._client.reservation_status(state["reservationId"]) not in (
                        "cleanup_pending", "released"):
                    raise
            state["version"] = 2
            state["state"] = "cleanup_pending"
            _atomic_json(self._journal, state, replace=True)
            return True
