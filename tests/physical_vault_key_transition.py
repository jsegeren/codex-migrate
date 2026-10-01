"""Opt-in physical legacy-to-Data-Protection Keychain acceptance.

Use only with an old notarized legacy helper and a newly provisioned, signed
release helper on the same logged-in Mac. All Vault data and keys are synthetic.
Never print helper JSON, recovery keys, transcripts, or Keychain contents.
"""

import json
import os
from pathlib import Path
import platform
import plistlib
import subprocess
import sys
import tempfile

from codex_migrate.errors import MigrationError
from codex_migrate.vault_backup import backup
from codex_migrate.vault_recovery import verify_snapshot


EXPECTED_GROUP = "P9J3JK79KQ.com.segeren.codex-migrate.vault-crypto"


def call(helper, *arguments):
    return subprocess.run([str(helper), *arguments], capture_output=True,
                          timeout=30, check=False)


def claims(helper):
    result = subprocess.run(["codesign", "-d", "--entitlements", ":-", str(helper)],
                            capture_output=True, timeout=15, check=False)
    if result.returncode:
        raise AssertionError("new Vault helper has no readable entitlements")
    return plistlib.loads(result.stdout)


def clean_key(old_helper, new_helper, key_id):
    failures = []
    for helper in (new_helper, old_helper):
        result = call(helper, "delete-key", "--key-id", key_id)
        if result.returncode:
            failures.append(helper.name)
    if failures:
        raise AssertionError("disposable Keychain cleanup requires review")


def main():
    if (platform.system() != "Darwin" or
            os.environ.get("CODEX_VAULT_DP_ACCEPTANCE") != "yes" or
            len(sys.argv) != 3):
        raise SystemExit("Opt in with CODEX_VAULT_DP_ACCEPTANCE=yes and OLD_HELPER NEW_HELPER")
    old_helper, new_helper = (Path(argument).resolve() for argument in sys.argv[1:])
    if not all(helper.is_file() and os.access(helper, os.X_OK)
               for helper in (old_helper, new_helper)):
        raise SystemExit("both helpers must be executable regular files")
    signed = subprocess.run(["codesign", "--verify", "--strict", str(new_helper)],
                            capture_output=True, timeout=15, check=False)
    if signed.returncode:
        raise SystemExit("new Vault helper signature did not verify")
    entitlement = claims(new_helper)
    if (entitlement.get("com.apple.application-identifier") != EXPECTED_GROUP or
            entitlement.get("keychain-access-groups") != [EXPECTED_GROUP]):
        raise SystemExit("new Vault helper is not provisioned for the expected Keychain group")

    with tempfile.TemporaryDirectory(prefix="codex-vault-key-transition-") as temporary:
        root = Path(temporary)
        source = root / "source/.codex/sessions/2026/09/25"
        source.mkdir(parents=True)
        (source / "synthetic.jsonl").write_text(
            json.dumps({"type": "session_meta", "payload": {
                "id": "11111111-1111-4111-8111-111111111111"}}) + "\n", encoding="utf-8")
        vault = root / "vault"
        key_id = None
        try:
            created = backup(str(root / "source"), str(vault), crypto_helper=str(old_helper))
            key_id = created.key_id
            if created.transcript_files != 1 or not created.recovery_key:
                raise AssertionError("old helper did not create a verified synthetic Vault")
            prior = verify_snapshot(str(vault), crypto_helper=str(old_helper))
            old_access = call(old_helper, "export-key", "--key-id", key_id)
            if old_access.returncode:
                raise AssertionError("legacy Keychain copy was unavailable before transition")
            migrated = verify_snapshot(str(vault), crypto_helper=str(new_helper))
            if prior.snapshot_id != migrated.snapshot_id or migrated.transcript_files != 1:
                raise AssertionError("snapshot changed during Keychain transition")
            old_access = call(old_helper, "export-key", "--key-id", key_id)
            if old_access.returncode == 0:
                raise AssertionError("legacy Keychain copy remained readable")
            new_access = call(new_helper, "export-key", "--key-id", key_id)
            if new_access.returncode:
                raise AssertionError("new protected Keychain copy is unavailable")
            if json.loads(new_access.stdout)["recovery_key"] != created.recovery_key:
                raise AssertionError("Keychain transition changed the recovery key")
            verify_snapshot(str(vault), crypto_helper=str(new_helper))
        except MigrationError as error:
            raise AssertionError("physical key transition failed closed") from error
        finally:
            if key_id:
                clean_key(old_helper, new_helper, key_id)
    print("Synthetic legacy-to-device-only Vault transition passed on this Mac")


if __name__ == "__main__":
    main()
