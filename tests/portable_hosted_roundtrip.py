"""Synthetic staged-object recovery on two independent macOS CI runners.

The artifact has ciphertext, a content-free claim, and a disposable recovery
key. It does not contact R2 or claim that a hosted service published a backup.
Never print the key, helper output, or ciphertext.
"""

import json
import os
from pathlib import Path
import re
import sys

from codex_migrate.errors import MigrationError
from codex_migrate.vault_backup import backup
from codex_migrate.vault_recovery import (
    import_recovery_key, restore_snapshot, verify_snapshot,
)
from codex_migrate.vault_remote_recovery import download_encrypted_snapshot
from codex_migrate.vault_remote_transfer import stage_encrypted_snapshot
from portable_vault_roundtrip import TRANSCRIPT, RELATIVE, delete_test_key


_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
_KEY = re.compile(
    rf"(?:metadata/{_UUID}\.json|manifests/{_UUID}\.cvmanifest|"
    rf"refs/{_UUID}\.json|objects/[0-9a-f]{{2}}/[0-9a-f]{{62}}\.cvchunk)\Z")


class SyntheticObjectStore:
    def __init__(self, root: Path):
        self.root = root

    def _path(self, key: str) -> Path:
        if not isinstance(key, str) or not _KEY.fullmatch(key):
            raise AssertionError("Unexpected synthetic object key")
        return self.root / key

    def open_read(self, key: str):
        path = self._path(key)
        try:
            return path.open("rb")
        except FileNotFoundError:
            return None

    def put_if_absent(self, key: str, source, length: int) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as output:
            data = source.read(length + 1)
            if len(data) != length:
                raise AssertionError("Synthetic upload changed length")
            output.write(data)
            output.flush()
            os.fsync(output.fileno())


def produce(bundle: Path, helper: Path) -> None:
    if bundle.exists():
        raise AssertionError("Synthetic artifact must start absent")
    bundle.mkdir(mode=0o700)
    source = bundle.parent / "hosted-portability-synthetic-source"
    local_vault = bundle.parent / "hosted-portability-synthetic-local-vault"
    transcript = source / ".codex" / RELATIVE
    transcript.parent.mkdir(parents=True, exist_ok=False)
    transcript.write_bytes(TRANSCRIPT)
    (source / ".codex" / "auth.json").write_text("NEVER-COPY-AUTH", encoding="utf-8")
    store = SyntheticObjectStore(bundle / "encrypted-objects")
    key_id = None
    try:
        saved = backup(str(source), str(local_vault), crypto_helper=str(helper))
        key_id = saved.key_id
        staged = stage_encrypted_snapshot(str(local_vault), store,
                                          crypto_helper=str(helper))
        if staged.snapshot_id != saved.snapshot_id or staged.uploaded_files < 3:
            raise AssertionError("Synthetic encrypted staging was incomplete")
        (bundle / "staged-receipt.json").write_text(
            json.dumps(staged.receipt(), sort_keys=True), encoding="utf-8")
        key_file = os.open(bundle / "recovery-key.txt",
                           os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(key_file, "w", encoding="utf-8") as output:
            output.write(saved.recovery_key + "\n")
        if any(b"NEVER-COPY-AUTH" in path.read_bytes()
               for path in store.root.rglob("*") if path.is_file()):
            raise AssertionError("Synthetic authentication material entered ciphertext artifact")
        print("Synthetic encrypted objects staged; local Vault excluded from artifact")
    finally:
        if key_id:
            delete_test_key(helper, key_id)


def consume(bundle: Path, helper: Path) -> None:
    store = SyntheticObjectStore(bundle / "encrypted-objects")
    receipt = json.loads((bundle / "staged-receipt.json").read_text(encoding="utf-8"))
    recovery_key = (bundle / "recovery-key.txt").read_text(encoding="utf-8").strip()
    if not recovery_key.startswith("CV1-"):
        raise AssertionError("Synthetic recovery key is invalid")
    empty_home = bundle.parent / "hosted-portability-synthetic-empty-home"
    empty_home.mkdir(mode=0o700, exist_ok=False)
    recovered = bundle.parent / "hosted-portability-synthetic-recovered-vault"
    restored = bundle.parent / "hosted-portability-synthetic-restored"
    try:
        download_encrypted_snapshot(str(empty_home), str(recovered), store, receipt,
                                    max_bytes=1024 * 1024, crypto_helper=str(helper))
    except MigrationError:
        if (recovered / "latest.json").exists():
            raise AssertionError("Unkeyed remote snapshot was marked protected")
    else:
        raise AssertionError("Remote snapshot decrypted without its recovery key")
    key_id = None
    try:
        key_id = import_recovery_key(str(recovered), recovery_key,
                                     crypto_helper=str(helper))
        result = download_encrypted_snapshot(
            str(empty_home), str(recovered), store, receipt,
            max_bytes=1024 * 1024, crypto_helper=str(helper))
        verified = verify_snapshot(str(recovered), crypto_helper=str(helper))
        restored_result = restore_snapshot(
            str(empty_home), str(recovered), str(restored), crypto_helper=str(helper))
        if (result.snapshot_id != receipt["snapshot_id"] or
                verified.snapshot_id != result.snapshot_id or
                restored_result.snapshot_id != result.snapshot_id or
                (restored / RELATIVE).read_bytes() != TRANSCRIPT or
                (restored / "auth.json").exists()):
            raise AssertionError("Independent-Mac hosted-style recovery failed")
        print("Synthetic remote objects decrypted and restored in consumer environment")
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
        raise SystemExit("Unknown synthetic portability mode")
