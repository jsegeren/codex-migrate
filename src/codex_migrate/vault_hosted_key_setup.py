"""Recoverable first-device key setup; secrets stay in Keychain and memory.

Checkpoint an account-bound key ID before native creation. The helper reuses
that ID after a crash, and a saved-copy check never imports or replaces a key.
Matching a saved copy is not clean-Mac recovery or hosted backup certification.
"""

from datetime import datetime, timezone
import re
import uuid

from codex_migrate.errors import MigrationError
from codex_migrate.vault_backup import (
    _atomic_json, _helper_path, _metadata, _run_helper,
)
from codex_migrate.vault_hosted_enrollment_client import _UUID
from codex_migrate.vault_schedule import _safe_json


class HostedKeySetup:
    def __init__(self, registry):
        self.registry = registry
        self._read()

    def _read(self):
        value = self.registry.read().get("hosted_setup_key")
        if value is None:
            return None
        if (not isinstance(value, dict) or
                set(value) != {"binding", "metadata", "saved_copy_confirmed"} or
                type(value["saved_copy_confirmed"]) is not bool or
                not isinstance(value["binding"], dict) or
                set(value["binding"]) != {"deviceId", "accountId", "vaultId"} or
                any(not isinstance(item, str) or not re.fullmatch(_UUID, item)
                    for item in value["binding"].values()) or
                not isinstance(value["metadata"], dict)):
            raise MigrationError("Saved backup key setup needs support; it was not replaced.")
        _metadata(value["metadata"])
        if (type(value["metadata"]["version"]) is not int or
                "recovery_mode" in value["metadata"]):
            raise MigrationError("Saved backup key setup has an unsupported key type.")
        return value

    def _bound(self, binding):
        if (not isinstance(binding, dict) or
                set(binding) != {"deviceId", "accountId", "vaultId"} or
                any(not isinstance(item, str) or not re.fullmatch(_UUID, item)
                    for item in binding.values())):
            raise MigrationError("Confirm the backup connection before preparing its key.")
        value = self._read()
        if value is not None and value["binding"] != binding:
            raise MigrationError("The saved backup key belongs to a different connection.")
        return value

    def confirmed(self, binding):
        value = self._bound(binding)
        return value is not None and value["saved_copy_confirmed"] is True

    def confirmed_binding(self, binding):
        """Non-secret stable key identity, without file writes or Keychain reads."""
        value = self._bound(binding)
        if value is None or value["saved_copy_confirmed"] is not True:
            return None
        return {**binding, "keyId": value["metadata"]["key_id"]}

    def require_connection(self, binding):
        value = self._read()
        if value is not None and value["binding"] != binding:
            raise MigrationError("The saved backup key and connection disagree; contact support.")

    def _save(self, value):
        self.registry.update(hosted_setup_key=value)
        self.registry.sync_recovery_checkpoint()

    def _metadata_file(self, metadata):
        path = self.registry.root / "hosted-key.json"
        if path.exists() or path.is_symlink():
            if _safe_json(path) != metadata:
                raise MigrationError("Saved backup key metadata disagrees; it was not replaced.")
        else:
            _atomic_json(path, metadata)
        return path

    def prepare(self, binding):
        value = self._bound(binding)
        if value is None:
            value = {"binding": dict(binding), "metadata": {
                "format": "codex-vault", "version": 1,
                "storage_codec": "lzfse-v1", "key_id": str(uuid.uuid4()),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }, "saved_copy_confirmed": False}
            self._save(value)
        else:
            # A prior sync may have failed after its rename. Repeat full sync
            # before touching Keychain, even when the checkpoint is readable.
            self.registry.sync_recovery_checkpoint()
        self._metadata_file(value["metadata"])
        key_id = value["metadata"]["key_id"]
        result = _run_helper(_helper_path(None), ["prepare-key", "--key-id", key_id])
        if (set(result) != {"key_id", "recovery_key"} or
                result.get("key_id") != key_id or
                not isinstance(result.get("recovery_key"), str) or
                not re.fullmatch(r"CV1-[A-Za-z0-9_-]{43}", result["recovery_key"])):
            raise MigrationError("The backup helper did not confirm the saved key.")
        return result["recovery_key"]

    def confirm(self, binding, recovery_key):
        if (not isinstance(recovery_key, str) or
                not re.fullmatch(r"CV1-[A-Za-z0-9_-]{43}", recovery_key)):
            raise MigrationError("Enter the recovery key from your saved copy.")
        value = self._bound(binding)
        if value is None:
            raise MigrationError("Prepare your backup key first.")
        self._metadata_file(value["metadata"])
        key_id = value["metadata"]["key_id"]
        result = _run_helper(_helper_path(None),
            ["check-recovery-key", "--key-id", key_id],
            input_data=(recovery_key + "\n").encode("ascii"))
        if (set(result) != {"key_id", "verified"} or
                result.get("key_id") != key_id or result.get("verified") is not True):
            raise MigrationError("Your saved recovery key could not be verified.")
        self._save({**value, "saved_copy_confirmed": True})

    def backup_metadata(self, binding):
        """Return only checked, non-secret metadata after saved-copy confirmation."""
        value = self._bound(binding)
        if value is None or value["saved_copy_confirmed"] is not True:
            raise MigrationError("Confirm your saved recovery key before hosted backup.")
        return self._metadata_file(value["metadata"]), value["metadata"]["key_id"]
