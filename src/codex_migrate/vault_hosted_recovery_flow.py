"""Acceptance-gated recovery wizard; credentials never enter public state.

The dashboard runs one step at a time off its HTTP thread. Only the opaque
device/Vault IDs survive restart; email proofs and recovery keys do not.
Downloaded ciphertext stays separate from live Codex history.
"""

from __future__ import annotations

import copy
from pathlib import Path
import re
import threading
from urllib.parse import urlsplit

from codex_migrate.errors import MigrationError
from codex_migrate.vault_hosted_disaster_recovery import (
    hosted_recovery_options, import_hosted_recovery_key,
    prepare_hosted_recovery, recover_hosted_snapshot,
)
from codex_migrate.vault_hosted_enrollment_client import (
    HostedEnrollmentClient, _CODE, _PURCHASE, _UUID,
)
from codex_migrate.vault_hosted_schedule import SERVICE_ORIGIN


def purchase_token(value: object) -> str:
    if not isinstance(value, str) or len(value) > 1024:
        raise MigrationError("Enter the private purchase link from your receipt.")
    value = value.strip()
    if value.startswith("https://"):
        url = urlsplit(value)
        if (url.scheme != "https" or url.netloc not in (
                "codexbackup.segeren.com", "migrate.segeren.com") or
                url.path != "/purchase" or url.query):
            raise MigrationError("Enter the private purchase link from your receipt.")
        value = url.fragment
    if not _PURCHASE.fullmatch(value) or len(value) > 330:
        raise MigrationError("Enter the private purchase link from your receipt.")
    return value


class HostedRecoveryFlow:
    def __init__(self, home: str, registry):
        self.home, self.registry = home, registry
        self._lock = threading.Lock()
        self._public = {"enabled": True, "status": "idle", "phase": "start"}
        self._proof = {}
        self._plan = None
        self._device = registry.read().get("hosted_recovery_device")
        self._claim_attempted = self._device is not None
        if self._device is not None:
            if (not isinstance(self._device, dict) or
                    set(self._device) != {"deviceId", "vaultId"} or
                    any(not isinstance(value, str) or not re.fullmatch(_UUID, value)
                        for value in self._device.values())):
                raise MigrationError("Saved recovery pairing needs support; it was not replaced.")
            self._public["phase"] = "pairing_uncertain"

    def snapshot(self):
        with self._lock:
            return copy.deepcopy(self._public)

    def _update(self, **changes):
        with self._lock:
            self._public.update(changes)

    def stage(self, action: str, payload: dict):
        """Validate synchronously, then return a single-use worker operation."""
        fields = {
            "send_code": {"purchase_link"}, "list_vaults": {"code"},
            "pair": {"vault_id"}, "resolve": set(), "versions": set(),
            "prepare": {"snapshot_id", "output"}, "import_key": {"recovery_key"},
            "download": set(),
            "reauthorize": set(),
        }
        allowed_phases = {
            "send_code": {"start", "email"}, "list_vaults": {"email"},
            "pair": {"vaults", "pairing_checkpoint"},
            "resolve": {"pairing_uncertain", "paired"},
            "versions": {"paired", "versions"}, "prepare": {"versions"},
            "import_key": {"prepared"}, "download": {"key_verified"},
            "reauthorize": {"pairing_uncertain"},
        }
        state = self.snapshot()
        if (action not in fields or not isinstance(payload, dict) or
                set(payload) != fields[action] | {"apply"} or
                payload.get("apply") is not True):
            raise MigrationError("Recovery requires an explicit, valid step confirmation.")
        if state["status"] == "running" or state["phase"] not in allowed_phases[action]:
            raise MigrationError("Finish the current recovery step before continuing.")
        values = {key: payload[key] for key in fields[action]}
        if action == "send_code":
            values["purchase_link"] = purchase_token(values["purchase_link"])
        if action == "list_vaults":
            if not isinstance(values["code"], str) or not _CODE.fullmatch(values["code"]):
                raise MigrationError("Enter the recovery code from the email.")
        if action == "pair":
            if values["vault_id"] not in {item["vaultId"] for item in state.get("vaults", [])}:
                raise MigrationError("Choose one of your listed backups.")
            if self._device is not None and (state["phase"] not in ("vaults", "pairing_checkpoint") or
                    values["vault_id"] != self._device["vaultId"]):
                raise MigrationError("Resume the saved pairing; do not create another device.")
        if action == "prepare":
            selected = next((item for item in state.get("versions", [])
                             if item["snapshotId"] == values["snapshot_id"]), None)
            output = values["output"]
            if (selected is None or not isinstance(output, str) or not output or
                    len(output) > 4096 or not Path(output).is_absolute()):
                raise MigrationError("Choose a listed version and an empty recovery folder.")
            values["selected"] = selected
        if action == "import_key":
            if (not isinstance(values["recovery_key"], str) or
                    not re.fullmatch(r"CV1-[A-Za-z0-9_-]{43}", values["recovery_key"])):
                raise MigrationError("Enter the separately saved CV1 recovery key.")
        self._update(status="running", step=action, error=None)

        def run():
            try:
                self._perform(action, values)
                self._update(status="ready", error=None)
            except Exception:
                # Provider/native exceptions can contain secrets and paths.
                self._update(status="failed", error=(
                    "This recovery step could not be confirmed. Your live Codex data "
                    "was not changed. Retry this step or contact joshua@segeren.com."))
            finally:
                values.clear()
        return run

    def _perform(self, action, values):
        client = HostedEnrollmentClient(SERVICE_ORIGIN)
        if action == "send_code":
            client.begin_recovery(values["purchase_link"], apply=True)
            self._proof = {"purchase": values["purchase_link"]}
            self._update(phase="email")
        elif action == "list_vaults":
            vaults = client.list_recovery_vaults(self._proof["purchase"], values["code"])
            if self._device is not None:
                vaults = [item for item in vaults if item["vaultId"] == self._device["vaultId"]]
                if not vaults:
                    raise MigrationError("The saved backup is not authorized by this receipt.")
            self._proof["code"] = values["code"]
            self._update(phase="vaults", vaults=vaults)
        elif action == "pair":
            device = self._device
            if device is None:
                device = {"deviceId": client.create_device(apply=True),
                          "vaultId": values["vault_id"]}
            # Save the opaque identity BEFORE the one-off server claim. An
            # ambiguous reply/restart must resolve this exact Keychain item.
            self._device = device
            self._update(phase="pairing_checkpoint", selected_vault_id=device["vaultId"])
            self.registry.update(hosted_recovery_device=device)
            self.registry.sync_recovery_checkpoint()
            self._update(phase="pairing_uncertain")
            identity = None
            if self._claim_attempted:
                try:
                    identity = client.resolve(device["deviceId"])
                except MigrationError:
                    # Only an explicit fresh email proof can reach this path.
                    # Reuse the saved credential; the server's unique token
                    # constraint refuses an existing or conflicting binding.
                    pass
            if identity is None:
                self._claim_attempted = True
                identity = client.claim_recovery(self._proof["purchase"], self._proof["code"],
                    device["vaultId"], device["deviceId"], apply=True)
            if identity["vaultId"] != device["vaultId"]:
                raise MigrationError("Recovery pairing changed authority.")
            self._proof.clear()
            self._update(phase="paired", vaults=[])
        elif action == "reauthorize":
            # Restart before the first claim is indistinguishable from a lost
            # reply. Never discard the identity: obtain fresh email authority,
            # then resolve again before trying that exact binding.
            self._proof.clear()
            self._update(phase="start", vaults=[], error=None)
        elif action == "resolve":
            identity = client.resolve(self._device["deviceId"])
            if identity["vaultId"] != self._device["vaultId"]:
                raise MigrationError("Recovery pairing changed authority.")
            self._proof.clear()
            self._update(phase="paired", vaults=[])
        elif action == "versions":
            options = hosted_recovery_options(self._device["deviceId"])
            versions = []
            for item in (options["latest"], options["latest_source_complete"]):
                if item is not None and item not in versions:
                    versions.append(item)
            if not versions:
                raise MigrationError("No published recovery version is available.")
            self._update(phase="versions", versions=versions)
        elif action == "prepare":
            selected = values["selected"]
            plan = {"output": values["output"], "snapshot_id": selected["snapshotId"],
                    "max_bytes": selected["totalBytes"]}
            result = prepare_hosted_recovery(self.home, device_id=self._device["deviceId"],
                                            **plan, apply=True)
            if (result["snapshot_id"] != plan["snapshot_id"] or
                    result["status"] != "awaiting_recovery_key"):
                raise MigrationError("Recovery preparation changed version.")
            self._plan = plan
            self._update(phase="prepared", vault=result["vault"],
                         snapshot_id=plan["snapshot_id"])
        elif action == "import_key":
            result = import_hosted_recovery_key(self.home, device_id=self._device["deviceId"],
                recovery_key=values["recovery_key"], **self._plan, apply=True)
            if (result["snapshot_id"] != self._plan["snapshot_id"] or
                    result["status"] != "ready_to_download"):
                raise MigrationError("Recovery key confirmation changed version.")
            self._update(phase="key_verified")
        elif action == "download":
            result = recover_hosted_snapshot(self.home, device_id=self._device["deviceId"],
                                            **self._plan, apply=True)
            if result["snapshot_id"] != self._plan["snapshot_id"]:
                raise MigrationError("Recovered backup changed version.")
            self._update(phase="verified", vault=result["vault"],
                         snapshot_id=result["snapshot_id"],
                         needs_attention=result["needs_attention"],
                         source_coverage=result["source_coverage"],
                         at_risk_sources=result["at_risk_sources"])
