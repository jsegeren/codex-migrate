"""Exercise Vault's real Keychain round trip on an ephemeral macOS CI runner.

Never print the recovery key, helper output, or runner Keychain contents.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid


def invoke(helper, command, *args, input_text=None):
    return subprocess.run(
        [helper, command, *args],
        input=input_text,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )


def require_success(result, operation):
    if result.returncode != 0:
        raise AssertionError("Vault Keychain {} failed (exit {})".format(
            operation, result.returncode))
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise AssertionError("Vault Keychain {} returned invalid JSON".format(
            operation)) from error


def main():
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise SystemExit("This Keychain smoke test is restricted to disposable GitHub runners")
    if len(sys.argv) != 2:
        raise SystemExit("Usage: keychain_ci_smoke.py /absolute/path/to/helper")

    helper = sys.argv[1]
    key_id = None
    prepared_id = None
    business_id = None
    try:
        created = require_success(invoke(helper, "create-key"), "create")
        key_id = created["key_id"]
        recovery_key = created["recovery_key"]
        assert recovery_key.startswith("CV1-")
        exported = require_success(invoke(helper, "export-key", "--key-id", key_id), "export")
        assert exported["recovery_key"] == recovery_key

        prepared_id = str(uuid.uuid4())
        first = require_success(invoke(helper, "prepare-key", "--key-id", prepared_id),
                                "checkpointed prepare")
        retried = require_success(invoke(helper, "prepare-key", "--key-id", prepared_id),
                                  "checkpointed retry")
        assert first == retried and first["key_id"] == prepared_id
        checked = require_success(invoke(helper, "check-recovery-key", "--key-id", prepared_id,
                                         input_text=first["recovery_key"] + "\n"),
                                  "saved-copy check")
        assert checked == {"key_id": prepared_id, "verified": True}
        assert invoke(helper, "check-recovery-key", "--key-id", prepared_id,
                      input_text=recovery_key + "\n").returncode != 0
        after_wrong = require_success(invoke(helper, "export-key", "--key-id", prepared_id),
                                      "saved-copy rejection preservation")
        assert after_wrong == first, "wrong saved copy changed the encryption key"

        require_success(invoke(helper, "delete-key", "--key-id", key_id), "delete")
        missing = invoke(helper, "export-key", "--key-id", key_id)
        assert missing.returncode != 0, "deleted key remained accessible"

        require_success(invoke(helper, "import-key", "--key-id", key_id,
                               input_text=recovery_key + "\n"), "import")
        recovered = require_success(invoke(helper, "export-key", "--key-id", key_id),
                                    "recovered export")
        assert recovered["recovery_key"] == recovery_key

        business = require_success(invoke(helper, "business-key-create"),
                                   "business create")
        business_id = business["key_id"]
        worker = business["worker_recovery_key"]
        company = business["company_recovery_key"]
        assert worker.startswith("CVB1-") and company.startswith("CVB1-")
        assert worker != company
        assert business["worker_envelope"]["role"] == "worker"
        assert business["company_envelope"]["role"] == "company"
        assert invoke(helper, "export-key", "--key-id", business_id).returncode != 0, (
            "business master key was exposed through personal export")
        assert invoke(helper, "prepare-key", "--key-id", business_id).returncode != 0, (
            "personal prepare accepted a business key")
        with tempfile.TemporaryDirectory(prefix="vault-business-key-smoke-") as temporary:
            snapshot_id = str(uuid.uuid4())
            manifest = Path(temporary) / "synthetic.cvmanifest"
            plaintext = json.dumps({"format": "codex-vault-snapshot", "version": 1,
                                    "snapshot_id": snapshot_id,
                                    "created_at": "2026-09-30T00:00:00Z", "files": []})
            require_success(invoke(helper, "seal-manifest", "--key-id", business_id,
                                   "--snapshot-id", snapshot_id, "--output", str(manifest),
                                   input_text=plaintext), "business manifest seal")
            original = require_success(invoke(
                helper, "manifest-fingerprint", "--key-id", business_id,
                "--snapshot-id", snapshot_id, "--manifest", str(manifest)),
                "business manifest open")
            for role, credential in (("worker", worker), ("company", company)):
                envelope = business[role + "_envelope"]
                require_success(invoke(helper, "delete-key", "--key-id", business_id),
                                "business key delete")
                wrong = company if role == "worker" else worker
                rejected = invoke(helper, "business-key-import", "--key-id", business_id,
                                  input_text=json.dumps({"recovery_key": wrong,
                                                         "envelope": envelope}))
                assert rejected.returncode != 0, "wrong custodian credential opened the Vault"
                swapped = {**envelope, "role": "company" if role == "worker" else "worker"}
                rejected = invoke(helper, "business-key-import", "--key-id", business_id,
                                  input_text=json.dumps({"recovery_key": credential,
                                                         "envelope": swapped}))
                assert rejected.returncode != 0, "swapped custodian role opened the Vault"
                require_success(invoke(helper, "business-key-import", "--key-id", business_id,
                                       input_text=json.dumps({"recovery_key": credential,
                                                              "envelope": envelope})),
                                role + " import")
                opened = require_success(invoke(
                    helper, "manifest-fingerprint", "--key-id", business_id,
                    "--snapshot-id", snapshot_id, "--manifest", str(manifest)),
                    role + " manifest open")
                assert opened == original, role + " could not reopen the encrypted snapshot"
                assert invoke(helper, "export-key", "--key-id", business_id).returncode != 0, (
                    "imported business master key was exposed through personal export")
        print("Vault personal and business recovery round trips passed on disposable CI")
    finally:
        if prepared_id is not None:
            if invoke(helper, "delete-key", "--key-id", prepared_id).returncode != 0:
                raise AssertionError("Vault prepared Keychain test key cleanup failed")
        if key_id is not None:
            deleted = invoke(helper, "delete-key", "--key-id", key_id)
            if deleted.returncode != 0:
                raise AssertionError("Vault Keychain test key cleanup failed")
        if business_id is not None:
            deleted = invoke(helper, "delete-key", "--key-id", business_id)
            if deleted.returncode != 0:
                raise AssertionError("Vault business Keychain test key cleanup failed")


if __name__ == "__main__":
    main()
