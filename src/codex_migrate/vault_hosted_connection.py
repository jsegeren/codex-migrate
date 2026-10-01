"""Non-secret active device reference, shared by UI and scheduled backups.

The original setup binding is provenance, not the current bearer. Callers hold
the account's update lock while reading this reference and using it, or while
publishing an authenticated rotation. No background worker writes UI StateStore.
"""

import re

from codex_migrate.errors import MigrationError
from codex_migrate.vault_backup import _atomic_json
from codex_migrate.vault_schedule import _ensure_owned_directory, _home, _safe_json


_FORMAT = "codex-vault-hosted-connection"
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")
_FIELDS = {"deviceId", "accountId", "vaultId", "keyId"}


def connection_path(source_home):
    return _home(source_home) / "Library/Application Support/Codex Vault/hosted-connection.json"


def validate_binding(binding):
    if (not isinstance(binding, dict) or set(binding) != _FIELDS or
            any(not isinstance(value, str) or not _UUID.fullmatch(value)
                for value in binding.values())):
        raise MigrationError("The hosted backup connection is invalid.")
    return dict(binding)


def _read(source_home):
    path = connection_path(source_home)
    if path.is_symlink():
        raise MigrationError("The hosted backup connection cannot be linked.")
    if not path.exists():
        return None
    value = _safe_json(path)
    if (path.lstat().st_mode & 0o077 or
            set(value) != {"format", "version", "owner_kind", "binding"} or
            value["format"] != _FORMAT or type(value["version"]) is not int or
            value["version"] != 1 or value["owner_kind"] not in ("individual", "business")):
        raise MigrationError("The saved hosted backup connection is invalid.")
    validate_binding(value["binding"])
    return value


def active_binding(source_home, original, *, owner_kind="individual"):
    """Resolve a rotated device only within the original account/Vault/key."""
    original = validate_binding(original)
    if owner_kind not in ("individual", "business"):
        raise MigrationError("The hosted backup owner is invalid.")
    pending = connection_path(source_home).with_name("hosted-rotation.json")
    if pending.exists() or pending.is_symlink():
        raise MigrationError("Complete the pending hosted device handoff first.")
    saved = _read(source_home)
    if saved is None:
        return original
    if (saved["owner_kind"] != owner_kind or any(
            saved["binding"][field] != original[field]
            for field in ("accountId", "vaultId", "keyId"))):
        raise MigrationError("The hosted backup connection changed account, Vault or key.")
    return dict(saved["binding"])


def save_connection(source_home, binding, *, owner_kind="individual", previous_device=None):
    """Checkpoint only a server-confirmed identity; never silently switch keys.

    A device change requires the old-device reference from the durable rotation
    journal. Repeating that same old-to-new handoff is idempotent after a crash.
    """
    binding = validate_binding(binding)
    if (owner_kind not in ("individual", "business") or
            (previous_device is not None and
             (not isinstance(previous_device, str) or not _UUID.fullmatch(previous_device)))):
        raise MigrationError("The hosted device handoff is invalid.")
    saved = _read(source_home)
    if saved is not None:
        if (saved["owner_kind"] != owner_kind or any(
                saved["binding"][field] != binding[field]
                for field in ("accountId", "vaultId", "keyId")) or
                saved["binding"]["deviceId"] not in (binding["deviceId"], previous_device)):
            raise MigrationError("The hosted device handoff changed identity.")
    path = connection_path(source_home)
    _ensure_owned_directory(_home(source_home), path.parent)
    _atomic_json(path, {"format": _FORMAT, "version": 1,
                       "owner_kind": owner_kind, "binding": binding}, replace=True)
