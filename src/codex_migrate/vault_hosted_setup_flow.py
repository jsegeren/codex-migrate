"""Acceptance-gated pairing, key custody and explicit first/manual backup.

Persist the Keychain device reference before claiming a purchase. A lost reply
must resolve that same device; purchase links and email proofs stay in memory.
Recovery-key preparation is explicit and account-bound. Separate backup and
schedule steps use existing server-authorized storage; setup never creates a
trial/subscription or grants upload authorization.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import re
import threading

from codex_migrate.errors import MigrationError
from codex_migrate.vault_hosted_enrollment_client import (
    HostedEnrollmentClient, _CODE, _UUID, _identity,
)
from codex_migrate.vault_hosted_recovery_flow import purchase_token
from codex_migrate.vault_hosted_key_setup import HostedKeySetup
from codex_migrate.vault_hosted_manual import back_up_hosted_history
from codex_migrate.vault_hosted_pending import pending_hosted_upload, abandon_hosted_upload
from codex_migrate.vault_hosted_connection import active_binding
from codex_migrate.vault_hosted_schedule import (
    SERVICE_ORIGIN, hosted_schedule_status, install_hosted_schedule, remove_hosted_schedule,
)
from codex_migrate.vault_schedule import _timestamp, _update_lock, _pending_update, _safe_json


def _backup_receipt(value):
    fields = {"applied", "snapshot_id", "status", "source_coverage",
              "at_risk_threads", "automatic_protection_verified"}
    if (not isinstance(value, dict) or set(value) != fields or
            value["applied"] is not True or
            value["automatic_protection_verified"] is not False or
            not isinstance(value["snapshot_id"], str) or
            not re.fullmatch(_UUID, value["snapshot_id"]) or
            value["status"] not in ("published", "unchanged", "needs_attention") or
            value["source_coverage"] not in ("complete", "needs_attention", "unknown") or
            type(value["at_risk_threads"]) is not int or value["at_risk_threads"] < 0 or
            ((value["status"] == "needs_attention") !=
             (value["source_coverage"] != "complete" or value["at_risk_threads"] > 0))):
        raise MigrationError("The hosted backup receipt is invalid.")
    return dict(value)


class HostedSetupFlow:
    def __init__(self, registry, source_home=None):
        self.registry = registry
        self.source_home = source_home
        self._lock = threading.Lock()
        self._proof = {}
        self._recovery_key = None
        self._pending_upload = None
        self._keys = HostedKeySetup(registry)
        self._binding = registry.read().get("hosted_setup_device")
        if self._binding is not None:
            if (not isinstance(self._binding, dict) or
                    set(self._binding) not in ({"deviceId"},
                        {"deviceId", "accountId", "vaultId"}) or
                    any(not isinstance(value, str) or not re.fullmatch(_UUID, value)
                        for value in self._binding.values())):
                raise MigrationError("Saved backup setup needs support; it was not replaced.")
            self._binding = dict(self._binding)
        # Keys can exist only after full pairing. Refuse inconsistent records
        # before email or claim calls, not after a new remote claim succeeds.
        self._keys.require_connection(self._binding)
        self._last_backup = registry.read().get("hosted_setup_backup")
        if self._last_backup is not None:
            saved_key = registry.read().get("hosted_setup_key")
            if (not isinstance(self._last_backup, dict) or
                    set(self._last_backup) != {"binding", "key_id", "receipt", "checked_at"} or
                    self._last_backup["binding"] != self._binding or
                    saved_key is None or saved_key["saved_copy_confirmed"] is not True or
                    self._last_backup["key_id"] != saved_key["metadata"]["key_id"]):
                raise MigrationError("The saved hosted backup receipt disagrees; contact support.")
            _backup_receipt(self._last_backup["receipt"])
            _timestamp(self._last_backup["checked_at"])
        self._claim_attempted = self._binding is not None
        self._public = {
            "enabled": True, "status": "idle",
            "phase": "pairing_uncertain" if self._binding else "start",
            "upload_authorized": False, "automatic_protection_verified": False,
        }

    def snapshot(self):
        with self._lock:
            result = copy.deepcopy(self._public)
            if self._pending_upload is not None:
                result["pending_upload"] = dict(self._pending_upload)
            if self._last_backup is not None:
                result["last_backup"] = copy.deepcopy(self._last_backup["receipt"])
                result["last_backup_checked_at"] = self._last_backup["checked_at"]
                if self.source_home is not None:
                    try:
                        anchor = self._keys.confirmed_binding(self._binding)
                        if anchor is None:
                            raise MigrationError("The saved recovery key is not confirmed.")
                        result["background"] = hosted_schedule_status(self.source_home,
                            expected_binding=anchor)
                    except Exception:
                        result["background"] = {"enabled": False, "healthy": False,
                            "error": "Background backup status could not be confirmed. Contact Joshua."}
            if (result["phase"] == "key_save" and result["status"] != "running"
                    and self._recovery_key is not None):
                result["recovery_key"] = self._recovery_key
            return result

    def _update(self, **changes):
        with self._lock:
            self._public.update(changes)

    def stage(self, action, payload):
        fields = {"send_code": {"purchase_link"}, "pair": {"code"},
                  "retry_save": set(), "resolve": set(), "reauthorize": set(),
                  "prepare_key": set(), "confirm_key": {"recovery_key"},
                  "first_backup": set(), "enable_schedule": set(), "disable_schedule": set(),
                  "check_upload": set(), "leave_upload_review": set(),
                  "abandon_upload": {"reservation_id", "confirm_abandon"}}
        phases = {"send_code": {"start", "email"}, "pair": {"email"},
                  "retry_save": {"pairing_checkpoint"},
                  "resolve": {"pairing_uncertain", "paired", "key_ready", "backup_ready"},
                  "reauthorize": {"pairing_uncertain"},
                  "prepare_key": {"paired", "key_save"},
                  "confirm_key": {"key_save"},
                  "first_backup": {"key_ready", "backup_ready"},
                  "enable_schedule": {"backup_ready"},
                  "disable_schedule": {"backup_ready", "pairing_uncertain", "pending_upload"},
                  "check_upload": {"key_ready", "backup_ready", "pending_upload"},
                  "leave_upload_review": {"pending_upload"},
                  "abandon_upload": {"pending_upload"}}
        with self._lock:
            if (action not in fields or not isinstance(payload, dict) or
                    set(payload) != fields[action] | {"apply"} or
                    payload.get("apply") is not True):
                raise MigrationError("Backup setup requires a valid, confirmed step.")
            if (self._public["status"] == "running" or
                    self._public["phase"] not in phases[action]):
                raise MigrationError("Finish the current backup setup step first.")
            if action == "enable_schedule" and (
                    self._pending_upload is not None or
                    self._last_backup is None or
                    self._last_backup["receipt"]["source_coverage"] != "complete" or
                    self._last_backup["receipt"]["at_risk_threads"] != 0):
                raise MigrationError("Review incomplete backup coverage before enabling automatic backups.")
            values = {name: payload[name] for name in fields[action]}
            if action == "abandon_upload" and (
                    values["confirm_abandon"] is not True or
                    not isinstance(values["reservation_id"], str) or
                    not re.fullmatch(_UUID, values["reservation_id"]) or
                    self._pending_upload is None or
                    self._pending_upload["can_abandon"] is not True or
                    values["reservation_id"] != self._pending_upload["reservation_id"]):
                raise MigrationError("Review and confirm this exact unpublished upload first.")
            if action == "send_code":
                values["purchase_link"] = purchase_token(values["purchase_link"])
            if action == "pair":
                if not isinstance(values["code"], str) or not _CODE.fullmatch(values["code"]):
                    raise MigrationError("Enter the setup code from your purchase email.")
            if action == "confirm_key":
                if (not isinstance(values["recovery_key"], str) or
                        not re.fullmatch(r"CV1-[A-Za-z0-9_-]{43}", values["recovery_key"])):
                    raise MigrationError("Enter the recovery key from your saved copy.")
            self._public.update(status="running", step=action, error=None)

        def run():
            try:
                self._perform(action, values)
                self._update(status="ready", error=None)
            except Exception:
                # Provider and native exceptions may contain private proofs.
                self._update(status="failed", error=(
                    "Hosted backup could not be confirmed. Keep the pending state and "
                    "retry with this same connection and key. Previously verified snapshots "
                    "are kept. Automatic protection is not active; contact "
                    "joshua@segeren.com if needed." if action == "first_backup" else
                    "Upload status or cleanup could not be confirmed. Keep its pending state. "
                    "Use Check upload status before trying again; previously verified backups "
                    "are kept. Contact joshua@segeren.com if needed."
                    if action in ("check_upload", "abandon_upload") else
                    "The schedule change could not be confirmed. Check background status "
                    "before retrying. Existing backups are kept; contact joshua@segeren.com."
                    if action in ("enable_schedule", "disable_schedule") else
                    "Backup setup could not be confirmed. Existing backups are kept. "
                    "No new subscription was started. Check setup status before continuing, "
                    "or contact joshua@segeren.com."))
            finally:
                values.clear()
                if self.snapshot()["phase"] in ("pairing_uncertain", "paired"):
                    self._proof.clear()
                if self.snapshot()["phase"] in ("key_ready", "backup_ready"):
                    self._recovery_key = None
        return run

    def _save(self):
        self.registry.update(hosted_setup_device=dict(self._binding))
        self.registry.sync_recovery_checkpoint()

    def _accept(self, result):
        identity = _identity(result, self._binding["deviceId"])
        if ("accountId" in self._binding and identity != self._binding):
            raise MigrationError("The saved backup connection changed identity.")
        # Keep the observed identity even if durable saving fails. A retry must
        # verify the same account and Vault, not accept a changed server answer.
        key_confirmed = self._keys.confirmed(identity)
        self._binding = dict(identity)
        self._save()
        self._proof.clear()
        self._update(phase=("backup_ready" if self._last_backup is not None else
                           "key_ready") if key_confirmed else "paired")

    def _claim(self, client):
        if self._claim_attempted:
            try:
                identity = client.resolve(self._binding["deviceId"])
            except MigrationError:
                # Only fresh, explicitly submitted email proof reaches this
                # path. The server refuses a replayed or conflicting claim.
                pass
            else:
                self._accept(identity)
                return
        self._claim_attempted = True
        self._accept(client.claim(self._proof["purchase"], self._proof["code"],
                                  self._binding["deviceId"], apply=True))

    def _perform(self, action, values):
        if action == "leave_upload_review":
            # Leave the view, not the durable upload. No journal, reservation,
            # published backup or schedule is removed by this navigation step.
            self._update(phase="backup_ready" if self._last_backup else "key_ready")
            return
        if action in ("check_upload", "abandon_upload"):
            if self.source_home is None:
                raise MigrationError("The backup source has not been configured.")
            path, key_id = self._keys.backup_metadata(self._binding)
            anchor = {**self._binding, "keyId": key_id}
            if action == "check_upload":
                result = pending_hosted_upload(self.source_home, self._binding["deviceId"],
                    str(path), expected_binding=anchor)
                # The transport boundary returns only this fixed public shape.
                if not isinstance(result, dict):
                    raise MigrationError("The pending-upload status is invalid.")
                fields = {"pending", "automatic_protection_verified"}
                if result.get("pending") is True:
                    fields |= {"reservation_id", "snapshot_id", "local_phase", "remote_status", "can_abandon"}
                if (set(result) != fields or
                        type(result["pending"]) is not bool or result["automatic_protection_verified"] is not False or
                        result["pending"] and (
                            any(not isinstance(result[k], str) or not re.fullmatch(_UUID, result[k])
                                for k in ("reservation_id", "snapshot_id")) or
                            result["local_phase"] not in ("reserving", "active", "cleanup_pending") or
                            result["remote_status"] not in ("active", "cleanup_pending", "released", "published") or
                            type(result["can_abandon"]) is not bool or
                            result["can_abandon"] != (result["remote_status"] != "published"))):
                    raise MigrationError("The pending-upload status is invalid.")
                with self._lock:
                    self._pending_upload = dict(result) if result["pending"] else None
                    self._public["phase"] = ("pending_upload" if result["pending"] else
                        "backup_ready" if self._last_backup else "key_ready")
                return
            result = abandon_hosted_upload(self.source_home, self._binding["deviceId"],
                str(path), expected_binding=anchor, reservation_id=values["reservation_id"], apply=True)
            if (not isinstance(result, dict) or set(result) != {
                    "applied", "reservation_id", "status", "automatic_protection_verified"} or
                    result["applied"] is not True or result["reservation_id"] != values["reservation_id"] or
                    result["status"] not in ("cleanup_pending", "released") or
                    result["automatic_protection_verified"] is not False):
                raise MigrationError("The upload cleanup receipt is invalid.")
            with self._lock:
                if result["status"] == "released":
                    self._pending_upload = None
                    self._public["phase"] = "backup_ready" if self._last_backup else "key_ready"
                else:
                    self._pending_upload = {**self._pending_upload,
                        "remote_status": "cleanup_pending", "local_phase": "cleanup_pending"}
            return
        if action in ("enable_schedule", "disable_schedule"):
            if self.source_home is None:
                raise MigrationError("The backup source has not been configured.")
            anchor = self._keys.confirmed_binding(self._binding)
            if anchor is None:
                raise MigrationError("Confirm your saved recovery key before changing background backup.")
            if action == "enable_schedule":
                path, key_id = self._keys.backup_metadata(self._binding)
                if key_id != anchor["keyId"]:
                    raise MigrationError("The hosted backup key changed identity.")
                install_hosted_schedule(self.source_home, self._binding["deviceId"],
                    _safe_json(path), expected_binding=anchor, apply=True)
            else:
                remove_hosted_schedule(self.source_home, expected_binding=anchor, apply=True)
            return
        if action == "first_backup":
            if self.source_home is None:
                raise MigrationError("The backup source has not been configured.")
            path, key_id = self._keys.backup_metadata(self._binding)
            receipt = _backup_receipt(back_up_hosted_history(
                self.source_home, self._binding["deviceId"], str(path),
                expected_binding={**self._binding, "keyId": key_id}, apply=True))
            saved = {"binding": dict(self._binding), "key_id": key_id,
                     "receipt": receipt,
                     "checked_at": datetime.now(timezone.utc).isoformat()}
            self.registry.update(hosted_setup_backup=saved)
            self.registry.sync_recovery_checkpoint()
            with self._lock:
                self._last_backup = saved
                self._pending_upload = None
                self._public["phase"] = "backup_ready"
            return
        if action == "prepare_key":
            self._recovery_key = self._keys.prepare(self._binding)
            self._update(phase="key_save")
            return
        if action == "confirm_key":
            self._keys.confirm(self._binding, values["recovery_key"])
            self._update(phase="key_ready")
            return
        client = HostedEnrollmentClient(SERVICE_ORIGIN)
        if action == "send_code":
            client.begin(values["purchase_link"], apply=True)
            self._proof = {"purchase": values["purchase_link"]}
            self._update(phase="email")
        elif action == "pair":
            self._proof["code"] = values["code"]
            if self._binding is None:
                self._binding = {"deviceId": client.create_device(apply=True)}
            # Validate before saving even if the native client's implementation
            # changes. No claim can run with an ambiguous local device reference.
            if (not isinstance(self._binding["deviceId"], str) or
                    not re.fullmatch(_UUID, self._binding["deviceId"])):
                raise MigrationError("The backup device reference is invalid.")
            self._update(phase="pairing_checkpoint")
            self._save()
            self._update(phase="pairing_uncertain")
            self._claim(client)
        elif action == "retry_save":
            self._save()
            self._update(phase="pairing_uncertain")
            self._claim(client)
        elif action == "resolve":
            self._update(phase="pairing_uncertain")
            anchor = (self._keys.confirmed_binding(self._binding)
                      if self.source_home is not None else None)
            if anchor is None:
                self._accept(client.resolve(self._binding["deviceId"]))
            else:
                with _update_lock(self.source_home, nonblocking=True) as marker:
                    if _pending_update(marker) is not None:
                        raise MigrationError("Wait for the app update before checking backup.")
                    current = active_binding(self.source_home, anchor)
                    identity = _identity(client.resolve(current["deviceId"]), current["deviceId"])
                    if identity != {field: current[field] for field in self._binding}:
                        raise MigrationError("The saved backup connection changed identity.")
                # Keep original pairing/key/receipt provenance immutable. Only
                # the shared non-secret journal follows credential renewal.
                self._proof.clear()
                self._update(phase="backup_ready" if self._last_backup else "key_ready")
        elif action == "reauthorize":
            # Retain the saved device. A new purchase proof must resolve it
            # before any one-off claim, never create a second credential.
            self._proof.clear()
            self._update(phase="start")
