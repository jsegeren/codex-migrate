"""Synthetic staged-object recovery on two independent macOS CI runners.

The artifact has ciphertext, a content-free claim, and a disposable recovery
key. It exercises interrupted staging and a corrupt newer object without
losing the prior snapshot. It does not contact R2 or claim that a hosted
service published a backup.
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
NEW_TRANSCRIPT = TRANSCRIPT + b'{"type":"response_item","payload":{"content":"later synthetic work"}}\n'


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


class InterruptOnceStore(SyntheticObjectStore):
    """Drop a second new PUT so the retry must reuse the first new object."""

    def __init__(self, root: Path):
        super().__init__(root)
        self.uploaded = 0
        self.uploaded_key = None

    def put_if_absent(self, key: str, source, length: int) -> None:
        if self.uploaded == 1:
            raise InterruptedError("Synthetic staging interruption")
        super().put_if_absent(key, source, length)
        self.uploaded += 1
        self.uploaded_key = key


class RecordingObjectStore(SyntheticObjectStore):
    def __init__(self, root: Path):
        super().__init__(root)
        self.uploaded_keys = set()

    def put_if_absent(self, key: str, source, length: int) -> None:
        super().put_if_absent(key, source, length)
        self.uploaded_keys.add(key)


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
        first = stage_encrypted_snapshot(str(local_vault), store,
                                         crypto_helper=str(helper))
        if first.snapshot_id != saved.snapshot_id or first.uploaded_files < 3:
            raise AssertionError("Synthetic encrypted staging was incomplete")
        (bundle / "staged-receipt.json").write_text(
            json.dumps(first.receipt(), sort_keys=True), encoding="utf-8")

        transcript.write_bytes(NEW_TRANSCRIPT)
        newer = backup(str(source), str(local_vault), crypto_helper=str(helper))
        if newer.snapshot_id == saved.snapshot_id or newer.key_id != saved.key_id:
            raise AssertionError("Synthetic scheduled snapshot was not distinct")
        interrupted = InterruptOnceStore(store.root)
        try:
            stage_encrypted_snapshot(str(local_vault), interrupted,
                                     crypto_helper=str(helper))
        except InterruptedError:
            if interrupted.uploaded != 1:
                raise AssertionError("Synthetic staging did not interrupt after a PUT")
        else:
            raise AssertionError("Synthetic staging was not interrupted")
        retry_store = RecordingObjectStore(store.root)
        second = stage_encrypted_snapshot(str(local_vault), retry_store,
                                          crypto_helper=str(helper))
        if (second.snapshot_id != newer.snapshot_id or second.uploaded_files < 1
                or interrupted.uploaded_key is None
                or interrupted.uploaded_key not in {item.key for item in second.objects}
                or interrupted.uploaded_key in retry_store.uploaded_keys):
            raise AssertionError(
                "Synthetic interrupted staging did not resume: "
                f"matching_snapshot={second.snapshot_id == newer.snapshot_id} "
                f"uploaded={second.uploaded_files} reused={second.reused_files}"
            )
        (bundle / "newer-receipt.json").write_text(
            json.dumps(second.receipt(), sort_keys=True), encoding="utf-8")
        key_file = os.open(bundle / "recovery-key.txt",
                           os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(key_file, "w", encoding="utf-8") as output:
            output.write(saved.recovery_key + "\n")
        if any(b"NEVER-COPY-AUTH" in path.read_bytes()
               for path in store.root.rglob("*") if path.is_file()):
            raise AssertionError("Synthetic authentication material entered ciphertext artifact")
        print("Two synthetic snapshots staged after interruption; local Vault excluded")
    finally:
        if key_id:
            delete_test_key(helper, key_id)


def consume(bundle: Path, helper: Path) -> None:
    store = SyntheticObjectStore(bundle / "encrypted-objects")
    receipt = json.loads((bundle / "staged-receipt.json").read_text(encoding="utf-8"))
    newer_receipt = json.loads((bundle / "newer-receipt.json").read_text(encoding="utf-8"))
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

        newer_manifest = store._path("manifests/" + newer_receipt["snapshot_id"] + ".cvmanifest")
        original = newer_manifest.read_bytes()
        if not original:
            raise AssertionError("Newer synthetic manifest is empty")
        damaged = bytes([original[0] ^ 1]) + original[1:]
        newer_manifest.write_bytes(damaged)
        newer_vault = bundle.parent / "hosted-portability-synthetic-newer-vault"
        try:
            try:
                download_encrypted_snapshot(
                    str(empty_home), str(newer_vault), store, newer_receipt,
                    max_bytes=1024 * 1024, crypto_helper=str(helper))
            except MigrationError:
                if (newer_vault / "latest.json").exists():
                    raise AssertionError("Corrupt newer object was marked protected")
            else:
                raise AssertionError("Corrupt newer object was accepted")
            if verify_snapshot(str(recovered), crypto_helper=str(helper)).snapshot_id != receipt["snapshot_id"]:
                raise AssertionError("Prior good snapshot changed after corrupt newer object")
        finally:
            newer_manifest.write_bytes(original)

        newer_result = download_encrypted_snapshot(
            str(empty_home), str(newer_vault), store, newer_receipt,
            max_bytes=1024 * 1024, crypto_helper=str(helper))
        newer_restored = bundle.parent / "hosted-portability-synthetic-newer-restored"
        restore_snapshot(str(empty_home), str(newer_vault), str(newer_restored),
                         crypto_helper=str(helper))
        if (newer_result.snapshot_id != newer_receipt["snapshot_id"] or
                (newer_restored / RELATIVE).read_bytes() != NEW_TRANSCRIPT or
                (restored / RELATIVE).read_bytes() != TRANSCRIPT):
            raise AssertionError("Independent-Mac retry or prior snapshot changed")
        print("Prior and newer synthetic snapshots recovered independently after corruption")
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
