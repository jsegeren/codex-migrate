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

    This sandbox adapter does not create snapshots, schedules, or billing. A
    crash between server reservation and the journal write can leave an unused
    server reservation; its expiry and cleanup remain release gates.
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
        if (not isinstance(value, dict) or set(value) != {
                "format", "version", "accountId", "vaultId", "snapshotId",
                "reservationId"} or value["format"] != _FORMAT
                or type(value["version"]) is not int or value["version"] != 1
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
        }

    def back_up_snapshot(self, vault: str, *, snapshot: str = "latest",
                         crypto_helper: Optional[str] = None,
                         apply: bool = False) -> dict:
        if apply is not True:
            raise MigrationError("Hosted backup changes require explicit confirmation.")
        with self._locked():
            inventory = encrypted_snapshot_inventory(
                vault, snapshot=snapshot, crypto_helper=crypto_helper)
            state = self._pending()
            if state is not None and state["snapshotId"] != inventory.snapshot_id:
                raise MigrationError(
                    "A different hosted snapshot is pending; review it before starting another.")
            if state is None:
                reservation_id = self._client.reserve(apply=True)
                state = {"format": _FORMAT, "version": 1,
                         "accountId": self._client._account_id,
                         "vaultId": self._client._vault_id,
                         "snapshotId": inventory.snapshot_id,
                         "reservationId": reservation_id}
                _atomic_json(self._journal, state)
            result = self._client.back_up_snapshot(
                vault, reservation_id=state["reservationId"], snapshot=snapshot,
                crypto_helper=crypto_helper, apply=True)
            if result.get("snapshotId") != state["snapshotId"]:
                raise MigrationError("The hosted publication did not match the pending snapshot.")
            try:
                self._journal.unlink()
                _fsync_directory(self._directory)
            except OSError as error:
                raise MigrationError("The hosted backup published but its journal remains.") from error
            return result
