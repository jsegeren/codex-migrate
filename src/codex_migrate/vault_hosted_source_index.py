"""Private source fingerprints anchored to a published hosted snapshot.

This is only a read-avoidance hint. The prior encrypted manifest supplies the
content/chunk facts, the service supplies published ciphertext facts, and a
new snapshot still needs independent publication verification.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
from typing import Dict, Optional, Tuple

from codex_migrate.errors import MigrationError
from codex_migrate.vault_backup import (
    _atomic_json, _helper_path, _json_bytes, _require_unlinked_path, _run_helper,
)
from codex_migrate.vault_hosted_chunk_journal import HostedChunkJournal


_FORMAT = "codex-vault-hosted-source-index"
_MAX_BYTES = 32 * 1024 * 1024
_MAX_FILES = 100_000
_HEX = re.compile(r"[0-9a-f]{64}\Z")
SourceFacts = Dict[Tuple[str, str], Tuple[int, int, int, int, int]]
PaginatedFacts = Optional[Tuple[Optional[Tuple[int, int, int, int, int]], ...]]


class SourceIndexInvalid(MigrationError):
    """A damaged optimization hint, not a damaged published backup."""


def _read_private(path: Path) -> Optional[dict]:
    _require_unlinked_path(path, allow_missing_leaf=True)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise MigrationError("The hosted source index is unavailable.") from error
    try:
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                    info.st_nlink != 1 or info.st_mode & 0o077 or
                    info.st_size > _MAX_BYTES):
                raise MigrationError("The hosted source index is unsafe.")
            raw = stream.read(_MAX_BYTES + 1)
            if len(raw) > _MAX_BYTES:
                raise MigrationError("The hosted source index is unsafe.")
            value = json.loads(raw)
    except (OSError, UnicodeError, ValueError) as error:
        raise SourceIndexInvalid("The hosted source index is invalid.") from error
    if not isinstance(value, dict):
        raise SourceIndexInvalid("The hosted source index is invalid.")
    return value


def _header(journal: HostedChunkJournal, snapshot_id: str) -> dict:
    return {"format": _FORMAT, "version": 2,
            "accountId": journal.account_id, "vaultId": journal.vault_id,
            "keyId": journal.key_id, "snapshotId": snapshot_id}


def _facts(value: dict) -> SourceFacts:
    rows = value.get("files")
    version = value.get("version")
    keys = {"format", "version", "accountId", "vaultId",
            "keyId", "snapshotId", "files", "mac"}
    if (type(version) is not int or version not in (1, 2) or
            set(value) != (keys | ({"paginated"} if version == 2 else set())) or
            not isinstance(value.get("mac"), str) or
            not _HEX.fullmatch(value["mac"]) or
            not isinstance(rows, list) or len(rows) > _MAX_FILES):
        raise SourceIndexInvalid("The hosted source index is invalid.")
    result: SourceFacts = {}
    for row in rows:
        if (not isinstance(row, list) or len(row) != 7 or
                row[0] not in ("active", "archived") or
                not isinstance(row[1], str) or not row[1] or
                row[1].startswith("/") or "\\" in row[1] or "\0" in row[1] or
                any(part in ("", ".", "..") for part in row[1].split("/")) or
                any(type(number) is not int or number < 0 for number in row[2:])):
            raise SourceIndexInvalid("The hosted source index is invalid.")
        identity = (row[0], row[1])
        if identity in result:
            raise SourceIndexInvalid("The hosted source index has duplicate files.")
        result[identity] = tuple(row[2:])
    _paginated(value)
    return result


def _paginated(value: dict) -> PaginatedFacts:
    if value.get("version") == 1:
        return None
    rows = value.get("paginated")
    if rows is None:
        return None
    if (not isinstance(rows, list) or len(rows) != 3 or rows[0] is None or
            any(row is not None and
                (not isinstance(row, list) or len(row) != 5 or
                 any(type(number) is not int or number < 0 for number in row))
                for row in rows)):
        raise SourceIndexInvalid("The hosted paginated source hint is invalid.")
    return tuple(None if row is None else tuple(row) for row in rows)


def _authenticate(value: dict, key_id: str, crypto_helper: str) -> str:
    unsigned = {key: item for key, item in value.items() if key != "mac"}
    reply = _run_helper(_helper_path(crypto_helper), [
        "source-index-mac", "--key-id", key_id],
        input_data=_json_bytes(unsigned))
    digest = reply.get("hmac_sha256")
    if (set(reply) != {"hmac_sha256"} or not isinstance(digest, str) or
            not _HEX.fullmatch(digest)):
        raise MigrationError("The hosted source-index authenticator failed.")
    return digest


def published_source_facts(journal: HostedChunkJournal, *,
                           crypto_helper: str, include_paginated: bool = False):
    """Use only the index whose snapshot is this reservation's exact base."""
    journal.ensure_private_directory()
    empty = ({}, None) if include_paginated else {}
    try:
        base = journal.base_snapshot_id
    except MigrationError:
        return empty  # Legacy direct staging has no safe published base to reuse.
    if base is None:
        return empty
    try:
        value = _read_private(journal.directory.parent / "source-index.json")
    except SourceIndexInvalid:
        return empty
    if value is None:
        return empty
    if (value.get("version") not in (1, 2) or
            any(value.get(key) != expected for key, expected in
                _header(journal, base).items() if key != "version")):
        return empty  # Lost promotion or key rotation: scan the source instead.
    try:
        facts = _facts(value)
    except SourceIndexInvalid:
        return empty
    if value["mac"] != _authenticate(value, journal.key_id, crypto_helper):
        return empty  # Tampering or corruption cannot suppress a source read.
    return (facts, _paginated(value)) if include_paginated else facts


def record_source_facts(journal: HostedChunkJournal, facts: SourceFacts, *,
                        crypto_helper: str,
                        paginated: PaginatedFacts = None) -> None:
    """Save a candidate, never the published index, before server publication."""
    journal.ensure_private_directory()
    if len(facts) > _MAX_FILES:
        raise MigrationError("The hosted source index has too many files.")
    rows = [[collection, path, *identity]
            for (collection, path), identity in sorted(facts.items())]
    value = {**_header(journal, journal.snapshot_id), "files": rows,
             "paginated": None if paginated is None else [
                 None if row is None else list(row) for row in paginated]}
    value["mac"] = _authenticate(value, journal.key_id, crypto_helper)
    _facts(value)
    path = journal.directory / "source-index-candidate.json"
    try:
        existing = _read_private(path)
    except SourceIndexInvalid:
        existing = None  # The authenticated manifest binding still guards retry.
    if existing is not None:
        if existing != value:
            raise MigrationError("The hosted source changed on snapshot retry.")
        return
    _atomic_json(path, value, replace=os.path.lexists(path))


def promote_source_facts(directory: Path, state: dict) -> None:
    """Advance the hint only after the exact snapshot is published."""
    journal = directory / ("snapshot-" + state["snapshotId"])
    if not os.path.lexists(journal):
        return  # A previous cleanup already retired this run's hint.
    try:
        candidate = _read_private(journal / "source-index-candidate.json")
    except SourceIndexInvalid:
        return
    if candidate is None:
        return  # A crash or older client costs a full scan, not protection.
    expected = {"format": _FORMAT,
                "accountId": state["accountId"], "vaultId": state["vaultId"],
                "keyId": state["keyId"], "snapshotId": state["snapshotId"]}
    if (candidate.get("version") not in (1, 2) or
            any(candidate.get(key) != value for key, value in expected.items())):
        raise MigrationError("The hosted source index belongs to another backup.")
    try:
        _facts(candidate)
    except SourceIndexInvalid:
        return
    target = directory / "source-index.json"
    try:
        prior = _read_private(target)
    except SourceIndexInvalid:
        prior = None
    if prior == candidate:
        return
    _atomic_json(target, candidate, replace=os.path.lexists(target))
