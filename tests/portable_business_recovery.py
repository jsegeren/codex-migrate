"""Disposable business Vault recovery across independent macOS CI runners.

The artifact contains synthetic work and one-time test credentials only. Never
print credentials, helper output, or recovered conversation content.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

from codex_migrate.errors import MigrationError
from codex_migrate.vault_backup import backup
from codex_migrate.vault_recovery import restore_snapshot, verify_snapshot


THREAD_ID = "77777777-7777-4777-8777-777777777777"
RELATIVE = Path("sessions/2026/09/30/rollout-" + THREAD_ID + ".jsonl")
TRANSCRIPT = (
    '{"type":"session_meta","payload":{"id":"' + THREAD_ID + '"}}\n'
    '{"type":"response_item","payload":{"role":"user",'
    '"content":"SYNTHETIC-BUSINESS-RECOVERY"}}\n'
).encode()


def helper_call(helper: Path, command: str, *arguments: str, input_bytes: bytes = b"") -> dict:
    result = subprocess.run(
        [str(helper), command, *arguments], input=input_bytes,
        capture_output=True, timeout=30, check=False,
    )
    if result.returncode:
        raise AssertionError("Business recovery helper operation failed: " + command)
    try:
        return json.loads(result.stdout)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise AssertionError("Business recovery helper result was invalid") from error


def private_json(path: Path, value: dict) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(value, output, sort_keys=True)


def produce(bundle: Path, helper: Path) -> None:
    if bundle.exists():
        raise AssertionError("Business recovery artifact must start absent")
    source = bundle.parent / "business-portability-source"
    transcript = source / ".codex" / RELATIVE
    transcript.parent.mkdir(parents=True, mode=0o700)
    transcript.write_bytes(TRANSCRIPT)
    bundle.mkdir(mode=0o700)
    vault = bundle / "vault"
    vault.mkdir(mode=0o700)
    key_id = None
    try:
        created = helper_call(helper, "business-key-create")
        key_id = created["key_id"]
        private_json(vault / "vault.json", {
            "format": "codex-vault", "version": 1, "storage_codec": "lzfse-v1",
            "key_id": key_id, "created_at": "2026-09-30T00:00:00+00:00",
        })
        result = backup(str(source), str(vault), crypto_helper=str(helper),
                        require_existing_key_id=key_id)
        if result.recovery_key is not None or result.transcript_files != 1:
            raise AssertionError("Business snapshot used the wrong key or source scope")
        verified = verify_snapshot(str(vault), crypto_helper=str(helper))
        if verified.snapshot_id != result.snapshot_id:
            raise AssertionError("Business snapshot did not verify on producer Mac")
        for role in ("worker", "company"):
            private_json(bundle / (role + "-credential.json"), {
                "recovery_key": created[role + "_recovery_key"],
                "envelope": created[role + "_envelope"],
            })
        print("Synthetic business Vault verified on producer Mac")
    finally:
        if key_id is not None:
            helper_call(helper, "delete-key", "--key-id", key_id)


def consume(bundle: Path, helper: Path) -> None:
    vault = bundle / "vault"
    if not vault.is_dir():
        raise AssertionError("Business recovery artifact is incomplete")
    metadata = json.loads((vault / "vault.json").read_text(encoding="utf-8"))
    key_id = metadata["key_id"]
    try:
        verify_snapshot(str(vault), crypto_helper=str(helper))
    except MigrationError:
        pass
    else:
        raise AssertionError("Independent Mac unexpectedly had the business Vault key")
    for role in ("company", "worker"):
        credential_path = bundle / (role + "-credential.json")
        credential = json.loads(credential_path.read_text(encoding="utf-8"))
        if credential["envelope"]["role"] != role:
            raise AssertionError("Business recovery custodian was switched")
        imported = False
        try:
            result = helper_call(helper, "business-key-import", "--key-id", key_id,
                                 input_bytes=json.dumps(credential).encode())
            imported = True
            if result != {"key_id": key_id, "imported": True}:
                raise AssertionError("Business recovery import changed key identity")
            verified = verify_snapshot(str(vault), crypto_helper=str(helper))
            empty_home = bundle.parent / ("business-empty-home-" + role)
            empty_home.mkdir(mode=0o700)
            output = bundle.parent / ("business-restored-" + role) / ".codex"
            output.parent.mkdir(mode=0o700)
            restored = restore_snapshot(str(empty_home), str(vault), str(output),
                                        crypto_helper=str(helper))
            if (restored.snapshot_id != verified.snapshot_id or
                    (output / RELATIVE).read_bytes() != TRANSCRIPT):
                raise AssertionError("Independent-Mac business conversation restore failed")
        finally:
            if imported:
                helper_call(helper, "delete-key", "--key-id", key_id)
    print("Both custodians restored the same synthetic Vault on independent Mac")


if __name__ == "__main__":
    if os.environ.get("GITHUB_ACTIONS") != "true" or len(sys.argv) != 4:
        raise SystemExit("Disposable GitHub macOS runner and mode/bundle/helper required")
    mode, bundle_name, helper_name = sys.argv[1:]
    if mode == "produce":
        produce(Path(bundle_name), Path(helper_name))
    elif mode == "consume":
        consume(Path(bundle_name), Path(helper_name))
    else:
        raise SystemExit("Unsupported business portability mode")
