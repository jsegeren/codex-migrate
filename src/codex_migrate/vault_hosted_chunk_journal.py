"""Durable opaque chunk receipts for a dark hosted-only backup run.

Every completed line is fsynced before a caller may delete its temporary
ciphertext. A truncated final line is safe to discard because deletion can
only follow an acknowledged, complete fsync. This is not a backup receipt:
the service still must independently verify and publish a whole snapshot.
"""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import re
import stat
from typing import Dict, Optional, Tuple

from codex_migrate.errors import MigrationError
from codex_migrate.vault_backup import (
    _atomic_json, _canonical_macos_path, _fsync_directory,
    _require_unlinked_path,
)


_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_FORMAT = "codex-vault-hosted-chunk-journal"
_MAX_LOG_BYTES = 32 * 1024 * 1024


class HostedChunkJournal:
    """One reservation's owner-only receipts, held under an exclusive lock."""

    def __init__(self, directory: Path, *, account_id: str, vault_id: str,
                 reservation_id: str, snapshot_id: str, key_id: str):
        ids = (account_id, vault_id, reservation_id, snapshot_id, key_id)
        if any(not isinstance(value, str) or not _UUID.fullmatch(value)
               for value in ids):
            raise MigrationError("The hosted chunk journal identity is invalid.")
        self.directory = _canonical_macos_path(Path(directory))
        self._header = {"format": _FORMAT, "version": 1,
                        "accountId": account_id, "vaultId": vault_id,
                        "reservationId": reservation_id,
                        "snapshotId": snapshot_id, "keyId": key_id}
        self._metadata = self.directory / "journal.json"
        self._log = self.directory / "chunks.jsonl"
        self._lock = self.directory / "journal.lock"
        self._lock_descriptor: Optional[int] = None
        self._descriptor: Optional[int] = None
        self.records: Dict[str, Tuple[int, str]] = {}

    @property
    def reservation_id(self) -> str:
        return self._header["reservationId"]

    def __enter__(self) -> "HostedChunkJournal":
        _require_unlinked_path(self.directory)
        info = self.directory.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or
                info.st_mode & 0o077):
            raise MigrationError("The hosted chunk journal folder is not private.")
        try:
            lock = os.open(self._lock,
                           os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            self._lock_descriptor = lock
            lock_info = os.fstat(lock)
            if (not stat.S_ISREG(lock_info.st_mode) or
                    lock_info.st_uid != os.getuid() or lock_info.st_nlink != 1 or
                    lock_info.st_mode & 0o077):
                raise MigrationError("The hosted chunk journal lock is unsafe.")
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._open_locked()
            return self
        except (OSError, MigrationError) as error:
            self.__exit__()
            if isinstance(error, MigrationError):
                raise
            raise MigrationError("The hosted chunk journal is busy or unavailable.") from error

    def _open_locked(self) -> None:
        _require_unlinked_path(self._metadata, allow_missing_leaf=True)
        try:
            self._metadata.lstat()
        except FileNotFoundError:
            _atomic_json(self._metadata, self._header)
        try:
            descriptor = os.open(self._metadata,
                                 os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as stream:
                metadata_info = os.fstat(stream.fileno())
                if (not stat.S_ISREG(metadata_info.st_mode) or
                        metadata_info.st_uid != os.getuid() or
                        metadata_info.st_nlink != 1 or
                        metadata_info.st_mode & 0o077 or
                        metadata_info.st_size > 1024):
                    raise MigrationError("The hosted chunk journal identity is unsafe.")
                header = json.load(stream)
        except (OSError, UnicodeError, ValueError) as error:
            raise MigrationError("The hosted chunk journal identity is invalid.") from error
        if header != self._header:
            raise MigrationError("The hosted chunk journal belongs to another run.")
        descriptor = os.open(self._log,
                             os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        self._descriptor = descriptor
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                info.st_nlink != 1 or info.st_mode & 0o077 or
                info.st_size > _MAX_LOG_BYTES):
            raise MigrationError("The hosted chunk journal log is unsafe.")
        # Fsync the directory entry too: a later receipt must remain reachable
        # after a crash before any caller may discard its scratch ciphertext.
        _fsync_directory(self.directory)
        self.records = self._read_records()

    def __exit__(self, *_: object) -> None:
        if self._descriptor is not None:
            os.close(self._descriptor)
            self._descriptor = None
        if self._lock_descriptor is not None:
            os.close(self._lock_descriptor)
            self._lock_descriptor = None

    def _read_records(self) -> Dict[str, Tuple[int, str]]:
        assert self._descriptor is not None
        size = os.fstat(self._descriptor).st_size
        if size > _MAX_LOG_BYTES:
            raise MigrationError("The hosted chunk journal log is too large.")
        os.lseek(self._descriptor, 0, os.SEEK_SET)
        parts = []
        remaining = size
        while remaining:
            part = os.read(self._descriptor, min(1024 * 1024, remaining))
            if not part:
                raise MigrationError("The hosted chunk journal log changed while reading.")
            parts.append(part)
            remaining -= len(part)
        data = b"".join(parts)
        complete = data.rfind(b"\n") + 1
        if complete < len(data):
            # A partial tail cannot have authorized scratch deletion. Do not
            # silently discard malformed *complete* records in the middle.
            os.ftruncate(self._descriptor, complete)
            os.fsync(self._descriptor)
            data = data[:complete]
        records: Dict[str, Tuple[int, str]] = {}
        for raw in data.splitlines():
            try:
                row = json.loads(raw)
            except (UnicodeError, ValueError) as error:
                raise MigrationError("The hosted chunk journal log is invalid.") from error
            if not isinstance(row, dict) or set(row) != {"id", "bytes", "sha256"}:
                raise MigrationError("The hosted chunk journal log is invalid.")
            identifier = row["id"]
            size = row["bytes"]
            digest = row["sha256"]
            if (not isinstance(identifier, str) or not _HEX.fullmatch(identifier) or
                    type(size) is not int or not 1 <= size <= 100_000_000 or
                    not isinstance(digest, str) or not _HEX.fullmatch(digest)):
                raise MigrationError("The hosted chunk journal log is invalid.")
            facts = (size, digest)
            if identifier in records and records[identifier] != facts:
                raise MigrationError("The hosted chunk journal has conflicting ciphertext.")
            records[identifier] = facts
        return records

    def record(self, identifier: str, size: int, digest: str) -> None:
        if self._descriptor is None:
            raise MigrationError("The hosted chunk journal is not locked.")
        if (not isinstance(identifier, str) or not _HEX.fullmatch(identifier) or
                type(size) is not int or not 1 <= size <= 100_000_000 or
                not isinstance(digest, str) or not _HEX.fullmatch(digest)):
            raise MigrationError("The hosted chunk receipt is invalid.")
        facts = (size, digest)
        existing = self.records.get(identifier)
        if existing is not None:
            if existing != facts:
                raise MigrationError("The hosted chunk receipt conflicts with its journal.")
            return
        line = (json.dumps({"id": identifier, "bytes": size, "sha256": digest},
                           sort_keys=True, separators=(",", ":")) + "\n").encode()
        current = os.fstat(self._descriptor).st_size
        if current + len(line) > _MAX_LOG_BYTES:
            raise MigrationError("The hosted chunk journal is full.")
        written = os.write(self._descriptor, line)
        if written != len(line):
            raise MigrationError("The hosted chunk journal write was incomplete.")
        os.fsync(self._descriptor)
        self.records[identifier] = facts
