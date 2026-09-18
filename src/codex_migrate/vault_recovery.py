"""Verification, recovery-key transfer and safe staging for Codex Vault."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import os
from pathlib import Path
import stat
from typing import Dict, List, Optional, Tuple
import uuid

from codex_migrate.errors import MigrationError
from codex_migrate.vault_backup import (
    FORMAT_VERSION,
    _canonical_macos_path,
    _helper_path,
    _metadata,
    _read_json,
    _require_unlinked_path,
    _run_helper,
)


@dataclass(frozen=True)
class RestorePlan:
    vault: str
    snapshot_id: str
    transcript_files: int
    transcript_bytes: int
    chunks: int
    output: Optional[str]
    applied: bool = False

    def as_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class RestoreResult:
    vault: str
    snapshot_id: str
    transcript_files: int
    transcript_bytes: int
    output: str
    applied: bool = True

    def as_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class SnapshotInfo:
    snapshot_id: str
    created_at: str
    latest: bool

    def as_dict(self) -> Dict[str, object]:
        return asdict(self)


def _vault_root(vault: str) -> Path:
    root = Path(vault).expanduser()
    if not root.is_absolute():
        raise ValueError("Vault path must be absolute")
    root = _canonical_macos_path(root)
    _require_unlinked_path(root)
    if not root.is_dir():
        raise MigrationError("The selected Codex Vault is not a folder.")
    return root


def _snapshot(
    vault: str,
    snapshot: str,
) -> Tuple[Path, str, str, Path, Path]:
    root = _vault_root(vault)
    key_id = _metadata(_read_json(root / "vault.json"))
    if snapshot == "latest":
        reference_path = root / "latest.json"
    else:
        try:
            snapshot = str(uuid.UUID(snapshot)).lower()
        except (ValueError, TypeError, AttributeError):
            raise ValueError("snapshot must be 'latest' or a UUID") from None
        reference_path = root / "refs" / (snapshot + ".json")
    reference = _read_json(reference_path)
    required = {"format", "version", "snapshot_id", "created_at", "manifest"}
    if set(reference) != required:
        raise MigrationError("The Vault snapshot reference has an unsupported shape.")
    if (reference.get("format") != "codex-vault-reference"
            or reference.get("version") != FORMAT_VERSION):
        raise MigrationError("The Vault snapshot reference has an unsupported version.")
    try:
        snapshot_id = str(uuid.UUID(str(reference.get("snapshot_id")))).lower()
    except (ValueError, TypeError, AttributeError):
        raise MigrationError("The Vault snapshot reference has an invalid identity.") from None
    if snapshot != "latest" and snapshot_id != snapshot:
        raise MigrationError("The Vault snapshot reference identity does not match its name.")
    expected_manifest = "manifests/" + snapshot_id + ".cvmanifest"
    if reference.get("manifest") != expected_manifest or not isinstance(reference.get("created_at"), str):
        raise MigrationError("The Vault snapshot reference has invalid manifest metadata.")
    manifest = root / expected_manifest
    objects = root / "objects"
    for path in (manifest, objects):
        _require_unlinked_path(path)
    if not manifest.is_file() or not objects.is_dir():
        raise MigrationError("The Vault snapshot is incomplete.")
    return root, key_id, snapshot_id, manifest, objects


def _verification(
    vault: str,
    snapshot: str,
    crypto_helper: Optional[str],
) -> Tuple[Path, str, str, Path, Path, Dict[str, object]]:
    root, key_id, snapshot_id, manifest, objects = _snapshot(vault, snapshot)
    helper = _helper_path(crypto_helper)
    verified = _run_helper(
        helper,
        ["verify", "--key-id", key_id, "--snapshot-id", snapshot_id,
         "--object-dir", str(objects), "--manifest", str(manifest)],
    )
    if (verified.get("snapshot_id") != snapshot_id
            or not isinstance(verified.get("files"), int)
            or verified["files"] < 0
            or not isinstance(verified.get("chunks"), int)
            or verified["chunks"] < 0
            or not isinstance(verified.get("bytes"), int)
            or verified["bytes"] < 0):
        raise MigrationError("The Vault verification result is invalid.")
    return root, key_id, snapshot_id, manifest, objects, verified


def verify_snapshot(
    vault: str,
    *,
    snapshot: str = "latest",
    crypto_helper: Optional[str] = None,
) -> RestorePlan:
    root, _, snapshot_id, _, _, verified = _verification(
        vault, snapshot, crypto_helper)
    return RestorePlan(
        vault=str(root), snapshot_id=snapshot_id,
        transcript_files=verified["files"], transcript_bytes=verified["bytes"],
        chunks=verified["chunks"], output=None,
    )


def list_snapshots(vault: str, *, limit: int = 100) -> List[SnapshotInfo]:
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1000:
        raise ValueError("snapshot limit must be between 1 and 1000")
    root, _, latest_id, _, _ = _snapshot(vault, "latest")
    references = root / "refs"
    _require_unlinked_path(references)
    if not references.is_dir():
        raise MigrationError("The Vault snapshot history is missing.")
    paths = sorted(references.glob("*.json"))
    if len(paths) > 1000:
        raise MigrationError("The Vault snapshot history is unexpectedly large.")
    history = []
    for path in paths:
        try:
            snapshot_id = str(uuid.UUID(path.stem)).lower()
        except (ValueError, TypeError, AttributeError):
            raise MigrationError("The Vault snapshot history contains an invalid reference.") from None
        _, _, checked_id, _, _ = _snapshot(str(root), snapshot_id)
        reference = _read_json(path)
        created_at = reference.get("created_at")
        if not isinstance(created_at, str) or not 1 <= len(created_at) <= 64:
            raise MigrationError("The Vault snapshot history contains an invalid timestamp.")
        try:
            created = datetime.fromisoformat(created_at)
        except ValueError:
            raise MigrationError(
                "The Vault snapshot history contains an invalid timestamp.") from None
        if created.tzinfo is None:
            raise MigrationError("The Vault snapshot history contains an invalid timestamp.")
        history.append(SnapshotInfo(
            snapshot_id=checked_id,
            created_at=created_at,
            latest=checked_id == latest_id,
        ))
    history.sort(key=lambda item: (item.created_at, item.snapshot_id), reverse=True)
    return history[:limit]


def _restore_output(source_home: str, vault: Path, output: str) -> Path:
    destination = Path(output).expanduser()
    if not destination.is_absolute():
        raise ValueError("restore output must be an absolute path")
    destination = _canonical_macos_path(destination)
    _require_unlinked_path(destination, allow_missing_leaf=True)
    source = _canonical_macos_path(Path(source_home) / ".codex")
    for protected in (source, vault):
        try:
            overlap = os.path.commonpath((str(protected), str(destination))) in (
                str(protected), str(destination))
        except ValueError:
            overlap = False
        if overlap:
            raise MigrationError(
                "Restore output must be separate from live Codex data and the encrypted Vault."
            )
    if destination.exists():
        info = destination.lstat()
        if not stat.S_ISDIR(info.st_mode) or any(destination.iterdir()):
            raise MigrationError("Restore output must be a new or empty folder.")
    return destination


def restore_snapshot(
    source_home: str,
    vault: str,
    output: str,
    *,
    snapshot: str = "latest",
    crypto_helper: Optional[str] = None,
) -> RestoreResult:
    root, key_id, snapshot_id, manifest, objects = _snapshot(vault, snapshot)
    destination = _restore_output(source_home, root, output)
    helper = _helper_path(crypto_helper)
    result = _run_helper(
        helper,
        ["restore", "--key-id", key_id, "--snapshot-id", snapshot_id,
         "--object-dir", str(objects), "--manifest", str(manifest),
         "--output", str(destination)],
    )
    if (result.get("snapshot_id") != snapshot_id
            or not isinstance(result.get("files"), int) or result["files"] < 0
            or not isinstance(result.get("bytes"), int) or result["bytes"] < 0
            or result.get("output") != str(destination)):
        raise MigrationError("The staged Vault restore result is invalid.")
    return RestoreResult(
        vault=str(root), snapshot_id=snapshot_id,
        transcript_files=result["files"], transcript_bytes=result["bytes"],
        output=str(destination),
    )


def plan_restore(
    source_home: str,
    vault: str,
    output: str,
    *,
    snapshot: str = "latest",
    crypto_helper: Optional[str] = None,
) -> RestorePlan:
    root, _, snapshot_id, _, _, verified = _verification(
        vault, snapshot, crypto_helper)
    destination = _restore_output(source_home, root, output)
    return RestorePlan(
        vault=str(root), snapshot_id=snapshot_id,
        transcript_files=verified["files"], transcript_bytes=verified["bytes"],
        chunks=verified["chunks"], output=str(destination),
    )


def import_recovery_key(
    vault: str,
    recovery_key: str,
    *,
    crypto_helper: Optional[str] = None,
) -> str:
    root = _vault_root(vault)
    key_id = _metadata(_read_json(root / "vault.json"))
    if not recovery_key.startswith("CV1-") or len(recovery_key) > 256:
        raise ValueError("recovery key has an invalid format")
    helper = _helper_path(crypto_helper)
    result = _run_helper(
        helper, ["import-key", "--key-id", key_id],
        input_data=(recovery_key + "\n").encode("utf-8"),
    )
    if result.get("key_id") != key_id or result.get("imported") is not True:
        raise MigrationError("The recovery key import result is invalid.")
    return key_id


def export_recovery_key(
    vault: str,
    *,
    crypto_helper: Optional[str] = None,
) -> str:
    root = _vault_root(vault)
    key_id = _metadata(_read_json(root / "vault.json"))
    helper = _helper_path(crypto_helper)
    result = _run_helper(helper, ["export-key", "--key-id", key_id])
    recovery_key = result.get("recovery_key")
    if (result.get("key_id") != key_id or not isinstance(recovery_key, str)
            or not recovery_key.startswith("CV1-")):
        raise MigrationError("The recovery key export result is invalid.")
    return recovery_key
