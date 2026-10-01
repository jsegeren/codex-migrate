"""Acceptance-gated first-device pairing, separate from billing and backup.

Persist the Keychain device reference before claiming a purchase. A lost reply
must resolve that same device; purchase links and email proofs stay in memory.
This controller does not create a trial, encryption key, snapshot or schedule.
"""

from __future__ import annotations

import copy
import re
import threading

from codex_migrate.errors import MigrationError
from codex_migrate.vault_hosted_enrollment_client import (
    HostedEnrollmentClient, _CODE, _UUID, _identity,
)
from codex_migrate.vault_hosted_recovery_flow import purchase_token
from codex_migrate.vault_hosted_schedule import SERVICE_ORIGIN


class HostedSetupFlow:
    def __init__(self, registry):
        self.registry = registry
        self._lock = threading.Lock()
        self._proof = {}
        self._binding = registry.read().get("hosted_setup_device")
        if self._binding is not None:
            if (not isinstance(self._binding, dict) or
                    set(self._binding) not in ({"deviceId"},
                        {"deviceId", "accountId", "vaultId"}) or
                    any(not isinstance(value, str) or not re.fullmatch(_UUID, value)
                        for value in self._binding.values())):
                raise MigrationError("Saved backup setup needs support; it was not replaced.")
            self._binding = dict(self._binding)
        self._claim_attempted = self._binding is not None
        self._public = {
            "enabled": True, "status": "idle",
            "phase": "pairing_uncertain" if self._binding else "start",
            "upload_authorized": False, "automatic_protection_verified": False,
        }

    def snapshot(self):
        with self._lock:
            return copy.deepcopy(self._public)

    def _update(self, **changes):
        with self._lock:
            self._public.update(changes)

    def stage(self, action, payload):
        fields = {"send_code": {"purchase_link"}, "pair": {"code"},
                  "retry_save": set(), "resolve": set(), "reauthorize": set()}
        phases = {"send_code": {"start", "email"}, "pair": {"email"},
                  "retry_save": {"pairing_checkpoint"},
                  "resolve": {"pairing_uncertain", "paired"},
                  "reauthorize": {"pairing_uncertain"}}
        with self._lock:
            if (action not in fields or not isinstance(payload, dict) or
                    set(payload) != fields[action] | {"apply"} or
                    payload.get("apply") is not True):
                raise MigrationError("Backup setup requires a valid, confirmed step.")
            if (self._public["status"] == "running" or
                    self._public["phase"] not in phases[action]):
                raise MigrationError("Finish the current backup setup step first.")
            values = {name: payload[name] for name in fields[action]}
            if action == "send_code":
                values["purchase_link"] = purchase_token(values["purchase_link"])
            if action == "pair":
                if not isinstance(values["code"], str) or not _CODE.fullmatch(values["code"]):
                    raise MigrationError("Enter the setup code from your purchase email.")
            self._public.update(status="running", step=action, error=None)

        def run():
            try:
                self._perform(action, values)
                self._update(status="ready", error=None)
            except Exception:
                # Provider and native exceptions may contain private proofs.
                self._update(status="failed", error=(
                    "Backup setup could not be confirmed. No backup or subscription "
                    "was started. Retry the current step or contact joshua@segeren.com."))
            finally:
                values.clear()
                if self.snapshot()["phase"] in ("pairing_uncertain", "paired"):
                    self._proof.clear()
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
        self._binding = dict(identity)
        self._save()
        self._proof.clear()
        self._update(phase="paired")

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
            self._accept(client.resolve(self._binding["deviceId"]))
        elif action == "reauthorize":
            # Retain the saved device. A new purchase proof must resolve it
            # before any one-off claim, never create a second credential.
            self._proof.clear()
            self._update(phase="start")
