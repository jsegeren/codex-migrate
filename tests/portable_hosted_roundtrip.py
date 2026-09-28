"""Synthetic staged-object recovery on two independent macOS CI runners.

The artifact has ciphertext, a content-free claim, and a disposable recovery
key. It exercises interrupted staging and a corrupt newer object without
losing the prior snapshot. It does not contact R2 or claim that a hosted
service published a backup.
Never print the key, helper output, or ciphertext.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import uuid

from codex_migrate.errors import MigrationError
from codex_migrate.vault_backup import backup
from codex_migrate.vault_hosted_chunk_journal import HostedChunkJournal
from codex_migrate.vault_hosted_snapshot_stage import stage_hosted_snapshot
from codex_migrate.vault_recovery import (
    import_recovery_key, restore_snapshot, snapshot_catalog, verify_snapshot,
)
from codex_migrate.vault import search
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

    def checked_metadata(self, key: str):
        path = self._path(key)
        try:
            value = path.read_bytes()
        except FileNotFoundError:
            return None
        return len(value), hashlib.sha256(value).hexdigest()

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


LIVE_THREAD = "44444444-4444-4444-8444-444444444444"
LIVE_MARKER = "SYNTHETIC-HOSTED-LIVE-PAGINATED"


def produce_live_paginated(bundle: Path, helper: Path, store: SyntheticObjectStore) -> None:
    """Stage the low-local-storage v3 path, not the older local-Vault mirror."""
    source = bundle.parent / "hosted-portability-live-source"
    codex = source / ".codex"
    codex.mkdir(parents=True)
    database = codex / "thread_history_1.sqlite"
    item = {"id": "item-1", "type": "userMessage", "text": LIVE_MARKER}
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE thread_items (thread_id TEXT, turn_id TEXT, "
                           "item_id TEXT, rollout_ordinal INTEGER, created_at_ms INTEGER, "
                           "item_json TEXT, item_type TEXT, updated_at_ordinal INTEGER)")
        connection.execute("CREATE TABLE thread_history_projection_state ("
                           "thread_id TEXT, next_rollout_byte_offset INTEGER, "
                           "next_rollout_ordinal INTEGER)")
        connection.execute("INSERT INTO thread_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (LIVE_THREAD, "turn-1", "item-1", 1, 100,
                            json.dumps(item), "userMessage", 1))
    original = database.read_bytes()
    created = subprocess.run([str(helper), "create-key"], check=True,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    key = json.loads(created.stdout)
    key_id = key["key_id"]
    snapshot_id, reservation_id = str(uuid.uuid4()), str(uuid.uuid4())
    metadata = {"format": "codex-vault", "version": 1, "key_id": key_id,
                "created_at": "2026-09-28T00:00:00+00:00"}

    class Client:
        def published_chunks(self, ids):
            result = {}
            for identifier in ids:
                key_name = ("objects/" + identifier[:2] + "/" +
                            identifier[2:] + ".cvchunk")
                facts = store.checked_metadata(key_name)
                if facts is not None:
                    result[identifier] = facts
            return result

        def object_store(self, requested, expected, *, apply=False):
            if requested != reservation_id or apply is not True:
                raise AssertionError("Wrong synthetic hosted reservation")
            return store

    journal_dir = bundle.parent / "hosted-portability-live-journal"
    journal_dir.mkdir(mode=0o700)
    try:
        with HostedChunkJournal(
                journal_dir, account_id=str(uuid.uuid4()), vault_id=str(uuid.uuid4()),
                reservation_id=reservation_id, snapshot_id=snapshot_id,
                key_id=key_id) as journal:
            staged = stage_hosted_snapshot(
                str(source), metadata, [], journal, Client(),
                crypto_helper=str(helper), chunk_size=64 * 1024,
                window_bytes=64 * 1024, apply=True)
            if staged.transcript_files != 1 or database.read_bytes() != original:
                raise AssertionError("Synthetic database history was not staged exactly")
        (bundle / "live-receipt.json").write_text(
            json.dumps(staged.upload_claim().receipt(), sort_keys=True), encoding="utf-8")
        key_file = os.open(bundle / "live-recovery-key.txt",
                           os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(key_file, "w", encoding="utf-8") as output:
            output.write(key["recovery_key"] + "\n")
        if any(LIVE_MARKER.encode() in path.read_bytes()
               for path in store.root.rglob("*") if path.is_file()):
            raise AssertionError("Synthetic paginated plaintext entered remote objects")
    finally:
        delete_test_key(helper, key_id)


def consume_live_paginated(bundle: Path, helper: Path, store: SyntheticObjectStore) -> None:
    receipt = json.loads((bundle / "live-receipt.json").read_text(encoding="utf-8"))
    recovery_key = (bundle / "live-recovery-key.txt").read_text(encoding="utf-8").strip()
    home = bundle.parent / "hosted-portability-live-empty-home"
    home.mkdir(mode=0o700)
    vault = bundle.parent / "hosted-portability-live-recovered-vault"
    key_id = None
    try:
        try:
            download_encrypted_snapshot(str(home), str(vault), store, receipt,
                                        max_bytes=1024 * 1024, crypto_helper=str(helper))
        except MigrationError:
            if (vault / "latest.json").exists():
                raise AssertionError("Unkeyed paginated history was marked protected")
        else:
            raise AssertionError("Paginated history decrypted without its recovery key")
        key_id = import_recovery_key(str(vault), recovery_key,
                                     crypto_helper=str(helper))
        downloaded = download_encrypted_snapshot(
            str(home), str(vault), store, receipt,
            max_bytes=1024 * 1024, crypto_helper=str(helper))
        if verify_snapshot(str(vault), crypto_helper=str(helper)).snapshot_id != downloaded.snapshot_id:
            raise AssertionError("Synthetic hosted paginated snapshot did not verify")
        browse = bundle.parent / "hosted-portability-live-browse"
        browse.mkdir(mode=0o700)
        restored = browse / ".codex"
        restore_snapshot(str(home), str(vault), str(restored),
                         crypto_helper=str(helper))
        lines = (restored / "paginated_history" /
                 (LIVE_THREAD + ".jsonl")).read_text(encoding="utf-8").splitlines()
        if len(lines) != 1 or json.loads(json.loads(lines[0])["item_json"])["text"] != LIVE_MARKER:
            raise AssertionError("Independent-Mac paginated history changed during recovery")
        catalog = snapshot_catalog(str(vault), crypto_helper=str(helper))
        if not list(search(str(browse), LIVE_MARKER, catalog=catalog)):
            raise AssertionError("Independent-Mac paginated history was not searchable")
    finally:
        if key_id:
            delete_test_key(helper, key_id)


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
        produce_live_paginated(bundle, helper, store)
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
        consume_live_paginated(bundle, helper, store)
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
