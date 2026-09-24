"""One-off synthetic Vault recovery proof across two independent macOS runners.

The artifact contains only a disposable test key and synthetic ciphertext. Never
print the recovery key, helper output, or Keychain contents.
"""

import os
from pathlib import Path
import subprocess
import sys

from codex_migrate.errors import MigrationError
from codex_migrate.vault_backup import backup
from codex_migrate.vault_recovery import (
    import_recovery_key, restore_snapshot, verify_snapshot,
)


TRANSCRIPT = b'{"type":"response_item","payload":{"content":"portable synthetic work"}}\n'
RELATIVE = Path("sessions/2026/09/24/portable.jsonl")


def delete_test_key(helper: Path, key_id: str) -> None:
    result = subprocess.run(
        [str(helper), "delete-key", "--key-id", key_id],
        capture_output=True, timeout=15,
    )
    if result.returncode:
        raise AssertionError("Disposable Vault Keychain cleanup failed")


def produce(bundle: Path, helper: Path) -> None:
    if bundle.exists():
        raise AssertionError("The test bundle must start absent")
    source = bundle.parent / "vault-portability-synthetic-source"
    transcript = source / ".codex" / RELATIVE
    transcript.parent.mkdir(parents=True, exist_ok=False)
    transcript.write_bytes(TRANSCRIPT)
    bundle.mkdir(mode=0o700)
    vault = bundle / "vault"
    key_id = None
    try:
        result = backup(str(source), str(vault), crypto_helper=str(helper))
        key_id = result.key_id
        if result.transcript_files != 1 or not result.recovery_key:
            raise AssertionError("Synthetic snapshot was not created")
        receipt = verify_snapshot(str(vault), crypto_helper=str(helper))
        if receipt.snapshot_id != result.snapshot_id:
            raise AssertionError("Producer snapshot verification failed")
        descriptor = os.open(bundle / "recovery-key.txt", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(result.recovery_key + "\n")
        print("Synthetic encrypted snapshot verified on producer Mac")
    finally:
        if key_id:
            delete_test_key(helper, key_id)


def consume(bundle: Path, helper: Path) -> None:
    vault = bundle / "vault"
    key_file = bundle / "recovery-key.txt"
    if not vault.is_dir() or not key_file.is_file():
        raise AssertionError("Synthetic portability artifact is incomplete")
    recovery_key = key_file.read_text(encoding="utf-8").strip()
    if not recovery_key.startswith("CV1-"):
        raise AssertionError("Synthetic recovery key is invalid")
    try:
        verify_snapshot(str(vault), crypto_helper=str(helper))
    except MigrationError:
        pass
    else:
        raise AssertionError("The second Mac unexpectedly already has the producer's Keychain key")
    key_id = None
    try:
        key_id = import_recovery_key(str(vault), recovery_key, crypto_helper=str(helper))
        verified = verify_snapshot(str(vault), crypto_helper=str(helper))
        if verified.transcript_files != 1:
            raise AssertionError("Imported snapshot file count changed")
        empty_home = bundle.parent / "vault-portability-synthetic-empty-home"
        empty_home.mkdir(mode=0o700, exist_ok=False)
        restored = bundle.parent / "vault-portability-synthetic-restored"
        result = restore_snapshot(
            str(empty_home), str(vault), str(restored), crypto_helper=str(helper),
        )
        if result.snapshot_id != verified.snapshot_id or (restored / RELATIVE).read_bytes() != TRANSCRIPT:
            raise AssertionError("Cross-Mac synthetic recovery content mismatch")
        print("Synthetic snapshot decrypted and restored on independent Mac")
    finally:
        if key_id:
            delete_test_key(helper, key_id)


if __name__ == "__main__":
    if os.environ.get("GITHUB_ACTIONS") != "true" or len(sys.argv) != 4:
        raise SystemExit("Run only on disposable macOS CI: produce|consume BUNDLE HELPER")
    mode, bundle_arg, helper_arg = sys.argv[1:]
    bundle = Path(bundle_arg).resolve()
    helper = Path(helper_arg).resolve()
    if mode == "produce":
        produce(bundle, helper)
    elif mode == "consume":
        consume(bundle, helper)
    else:
        raise SystemExit("Unknown synthetic portability test mode")
