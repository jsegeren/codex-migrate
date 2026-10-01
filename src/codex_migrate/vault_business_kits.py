"""Write business recovery kits without printing or replacing credentials.

Writing files on one Mac is not proof of independent company custody. An
assisted pilot must transfer the company kit to its designated custodian and
pass a clean-Mac import-and-restore drill before calling the seat protected.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
from typing import Dict

from codex_migrate.errors import MigrationError
from codex_migrate.vault_backup import (
    BusinessRecoverySetup, _canonical_macos_path, _fsync_directory,
    _json_bytes, _metadata, _read_json, _require_unlinked_path,
    _validate_destination,
)


def _kit_path(value: str, source_home: str, vault: Path) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        raise ValueError("Business recovery kit paths must be absolute.")
    _require_unlinked_path(candidate, allow_missing_leaf=True)
    candidate = _canonical_macos_path(candidate)
    source = _canonical_macos_path(Path(source_home) / ".codex")
    for protected in (source, vault):
        if os.path.commonpath((str(candidate), str(protected))) == str(protected):
            raise MigrationError("Recovery kits must be outside Codex and the Vault.")
    try:
        info = candidate.parent.lstat()
    except OSError as error:
        raise MigrationError("The recovery kit folder is unavailable.") from error
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or
            info.st_mode & 0o077):
        raise MigrationError("Recovery kit folders must be private and owned by you.")
    return candidate


def _credential(value: object, key_id: str, role: str) -> Dict[str, object]:
    if not isinstance(value, dict) or set(value) != {"recovery_key", "envelope"}:
        raise MigrationError("Business recovery material is invalid.")
    secret = value["recovery_key"]
    envelope = value["envelope"]
    if (not isinstance(secret, str) or not secret.startswith("CVB1-") or
            len(secret) > 256 or not isinstance(envelope, dict) or
            set(envelope) != {"version", "key_id", "role", "wrapped_key"} or
            envelope["version"] != 1 or envelope["key_id"] != key_id or
            envelope["role"] != role or
            not isinstance(envelope["wrapped_key"], str)):
        raise MigrationError("Business recovery material is invalid.")
    return value


def save_business_recovery_kits(
    source_home: str, vault: str, setup: BusinessRecoverySetup,
    worker_path: str, company_path: str,
) -> Dict[str, str]:
    """Save both one-time kits to private, non-overwriting files.

    The caller still must deliver the company kit off-device and verify it on
    a clean Mac. A write failure after any secret byte may leave a partial kit;
    never infer custody or protection from file existence alone.
    """
    if not isinstance(setup, BusinessRecoverySetup):
        raise MigrationError("Business recovery setup is invalid.")
    root = _validate_destination(source_home, vault)
    metadata = _read_json(root / "vault.json")
    key_id = _metadata(metadata)
    if metadata.get("recovery_mode") != "business-v1" or setup.key_id != key_id:
        raise MigrationError("Business recovery setup does not match the Vault.")
    worker = _kit_path(worker_path, source_home, root)
    company = _kit_path(company_path, source_home, root)
    if worker == company:
        raise MigrationError("Worker and company recovery kits need separate files.")
    first = _credential(setup.worker_credential, key_id, "worker")
    second = _credential(setup.company_credential, key_id, "company")
    if first["recovery_key"] == second["recovery_key"]:
        raise MigrationError("The business recovery custodians were not independent.")
    paths = (worker, company)
    payloads = (_json_bytes(first), _json_bytes(second))
    opened = []
    writing_started = False
    try:
        # Reserve both exact names before writing either secret. O_EXCL and
        # O_NOFOLLOW prevent overwrite and final-component link redirection.
        for path in paths:
            descriptor = os.open(path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            info = os.fstat(descriptor)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                    info.st_nlink != 1 or info.st_mode & 0o077):
                os.close(descriptor)
                raise MigrationError("A recovery kit destination is unsafe.")
            opened.append((path, descriptor, info.st_ino))
        for (_, descriptor, _), payload in zip(opened, payloads):
            writing_started = True
            view = memoryview(payload)
            while view:
                count = os.write(descriptor, view)
                if count <= 0:
                    raise OSError("Recovery kit write did not advance.")
                view = view[count:]
            os.fsync(descriptor)
        for parent in {path.parent for path in paths}:
            _fsync_directory(parent)
    except (OSError, MigrationError) as error:
        if not writing_started:
            for path, _, inode in opened:
                try:
                    if path.lstat().st_ino == inode:
                        path.unlink()
                except OSError:
                    pass
        raise MigrationError(
            "Recovery kit export did not finish; do not claim protection. "
            "Inspect both chosen paths before retrying."
        ) from error
    finally:
        for _, descriptor, _ in opened:
            os.close(descriptor)
    return {"worker_kit": str(worker), "company_kit": str(company)}


def load_business_recovery_kit(path: str) -> Dict[str, object]:
    """Read one private kit for clean-Mac import without echoing its secret."""
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        raise ValueError("Business recovery kit path must be absolute.")
    _require_unlinked_path(candidate)
    candidate = _canonical_macos_path(candidate)
    try:
        descriptor = os.open(candidate, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as error:
        raise MigrationError("The business recovery kit is unavailable.") from error
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                info.st_nlink != 1 or info.st_mode & 0o077 or
                not 0 < info.st_size <= 4096):
            raise MigrationError("The business recovery kit is not a private regular file.")
        encoded = os.read(descriptor, 4097)
        if len(encoded) != info.st_size:
            raise MigrationError("The business recovery kit changed while reading.")
    except OSError as error:
        raise MigrationError("The business recovery kit could not be read.") from error
    finally:
        os.close(descriptor)
    try:
        value = json.loads(encoded)
    except (UnicodeError, ValueError) as error:
        raise MigrationError("The business recovery kit is invalid.") from error
    if not isinstance(value, dict):
        raise MigrationError("The business recovery kit is invalid.")
    return value
