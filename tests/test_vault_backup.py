import hashlib
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from codex_migrate.errors import MigrationError
from codex_migrate import vault_backup
from codex_migrate.vault_backup import backup, plan
from codex_migrate.vault_identity import TranscriptChanged
from codex_migrate.vault_recovery import (
    export_recovery_key, import_recovery_key, list_snapshots, restore_snapshot,
    vault_storage_usage, verify_snapshot,
)
from codex_migrate import vault_remote_inventory
from codex_migrate import vault_remote_recovery
from codex_migrate import vault_remote_transfer


class MemoryObjectStore:
    def __init__(self):
        self.objects = {}
        self.writes = 0
        self.fail_on_write = None

    def open_read(self, key):
        value = self.objects.get(key)
        return None if value is None else io.BytesIO(value)

    def put_if_absent(self, key, source, length):
        self.writes += 1
        if self.writes == self.fail_on_write:
            raise OSError("disposable upload interruption")
        if key in self.objects:
            raise AssertionError("immutable remote object was replaced")
        value = source.read(length)
        if len(value) != length:
            raise AssertionError("short local upload")
        self.objects[key] = value


class MetadataObjectStore(MemoryObjectStore):
    def open_read(self, key):
        raise AssertionError("metadata staging must not download ciphertext")

    def checked_metadata(self, key):
        value = self.objects.get(key)
        return None if value is None else (len(value), hashlib.sha256(value).hexdigest())


@unittest.skipUnless(platform.system() == "Darwin", "CryptoKit backup helper requires macOS")
class VaultBackupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        packaged = os.environ.get("CODEX_MIGRATE_TEST_VAULT_HELPER")
        if packaged:
            cls.build = None
            cls.helper = Path(packaged)
            if not cls.helper.is_file():
                raise AssertionError("packaged Vault helper is missing")
            return
        cls.build = tempfile.TemporaryDirectory()
        cls.helper = Path(cls.build.name) / "CodexVaultCrypto"
        subprocess.run([
            "xcrun", "swiftc", "-parse-as-library", "-O", "-D", "CODEX_VAULT_TEST_LEGACY_KEYCHAIN",
            "-target", platform.machine() + "-apple-macos13.0",
            "desktop/CodexVaultCrypto.swift", "-o", str(cls.helper),
        ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    @classmethod
    def tearDownClass(cls):
        if cls.build is not None:
            cls.build.cleanup()

    def fixture(self, root: Path) -> None:
        active = root / ".codex/sessions/2026/09/17/active.jsonl"
        archived = root / ".codex/archived_sessions/archived.jsonl"
        active.parent.mkdir(parents=True)
        archived.parent.mkdir(parents=True)
        active.write_text(
            json.dumps({"payload": {"message": {"content": "PRIVATE-ACTIVE-CONTENT"}}}) + "\n",
            encoding="utf-8",
        )
        archived.write_text(
            json.dumps({"payload": {"text": "PRIVATE-ARCHIVED-CONTENT"}}) + "\n",
            encoding="utf-8",
        )
        (root / ".codex/auth.json").write_text("NEVER-COPY-AUTH", encoding="utf-8")
        (root / ".codex/installation_id").write_text("NEVER-COPY-ID", encoding="utf-8")

    def delete_key(self, vault: Path) -> None:
        metadata = vault / "vault.json"
        if not metadata.exists():
            return
        key_id = json.loads(metadata.read_text(encoding="utf-8"))["key_id"]
        subprocess.run(
            [str(self.helper), "delete-key", "--key-id", key_id],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

    def test_plan_is_read_only_and_does_not_require_crypto_helper(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "vault"
            self.fixture(source)
            result = plan(str(source), str(destination))
            self.assertFalse(result.applied)
            self.assertTrue(result.encrypted)
            self.assertEqual(result.transcript_files, 2)
            self.assertFalse(destination.exists())

    def test_backup_is_encrypted_versioned_verified_and_incremental(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "vault"
            self.fixture(source)
            try:
                first = backup(
                    str(source), str(destination), crypto_helper=str(self.helper),
                    chunk_size=64 * 1024,
                )
                self.assertIsNotNone(first.recovery_key)
                self.assertTrue(first.recovery_key.startswith("CV1-"))
                self.assertEqual(first.transcript_files, 2)
                self.assertEqual(first.chunks, 2)
                objects = sorted((destination / "objects").rglob("*.cvchunk"))
                self.assertEqual(len(objects), 2)
                first_object_names = [path.relative_to(destination).as_posix() for path in objects]

                second = backup(
                    str(source), str(destination), crypto_helper=str(self.helper),
                    chunk_size=64 * 1024,
                )
                self.assertIsNone(second.recovery_key)
                self.assertNotEqual(first.snapshot_id, second.snapshot_id)
                self.assertEqual(
                    [path.relative_to(destination).as_posix()
                     for path in sorted((destination / "objects").rglob("*.cvchunk"))],
                    first_object_names,
                )
                self.assertEqual(len(list((destination / "refs").glob("*.json"))), 2)
                latest = json.loads((destination / "latest.json").read_text(encoding="utf-8"))
                self.assertEqual(latest["snapshot_id"], second.snapshot_id)
                history = list_snapshots(str(destination))
                self.assertEqual(
                    [item.snapshot_id for item in history],
                    [second.snapshot_id, first.snapshot_id],
                )
                storage = vault_storage_usage(str(destination))
                self.assertEqual(storage["storage_bytes"], sum(
                    path.stat().st_size for path in destination.rglob("*") if path.is_file()))
                self.assertEqual(storage["storage_files"], sum(
                    path.is_file() for path in destination.rglob("*")))
                self.assertEqual([item.latest for item in history], [True, False])
                self.assertEqual(
                    [item.snapshot_id for item in list_snapshots(
                        str(destination), limit=1)],
                    [second.snapshot_id],
                )

                stored = b"".join(
                    path.read_bytes() for path in destination.rglob("*") if path.is_file())
                self.assertNotIn(b"PRIVATE-ACTIVE-CONTENT", stored)
                self.assertNotIn(b"PRIVATE-ARCHIVED-CONTENT", stored)
                self.assertNotIn(b"NEVER-COPY-AUTH", stored)
                self.assertNotIn(b"NEVER-COPY-ID", stored)
            finally:
                self.delete_key(destination)

    def test_remote_inventory_contains_only_verified_portable_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, destination = root / "source", root / "vault"
            self.fixture(source)
            try:
                result = backup(str(source), str(destination), crypto_helper=str(self.helper))
                inventory = vault_remote_inventory.encrypted_snapshot_inventory(
                    str(destination), crypto_helper=str(self.helper))
                paths = [item.relative_path for item in inventory.files]
                remote_keys = [item.remote_key for item in inventory.files]
                self.assertEqual(inventory.snapshot_id, result.snapshot_id)
                self.assertTrue(inventory.is_current_latest)
                self.assertEqual(paths[0], "vault.json")
                self.assertEqual(remote_keys[0],
                                 f"metadata/{result.snapshot_id}.json")
                self.assertEqual(paths[-2:], [
                    f"manifests/{result.snapshot_id}.cvmanifest",
                    f"refs/{result.snapshot_id}.json",
                ])
                self.assertEqual(len([path for path in paths if path.startswith("objects/")]), 2)
                self.assertEqual(inventory.transfer_bytes, sum(
                    (destination / path).stat().st_size for path in paths))
                self.assertEqual(
                    {item.relative_path: item.sha256 for item in inventory.files},
                    {path: hashlib.sha256((destination / path).read_bytes()).hexdigest()
                     for path in paths},
                )
                self.assertFalse(any("auth" in path or "installation" in path for path in paths))
                self.assertNotIn("latest.json", paths)  # publish only after remote verification
                historical = vault_remote_inventory.encrypted_snapshot_inventory(
                    str(destination), snapshot=result.snapshot_id,
                    crypto_helper=str(self.helper))
                self.assertFalse(historical.is_current_latest)
            finally:
                self.delete_key(destination)

    def test_remote_inventory_rejects_invalid_helper_ids_and_divergent_reference(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, destination = root / "source", root / "vault"
            self.fixture(source)
            try:
                result = backup(str(source), str(destination), crypto_helper=str(self.helper))
                with patch.object(vault_remote_inventory, "_run_helper", return_value={
                    "snapshot_id": result.snapshot_id, "chunk_ids": [4],
                }):
                    with self.assertRaisesRegex(MigrationError, "inventory is invalid"):
                        vault_remote_inventory.encrypted_snapshot_inventory(
                            str(destination), crypto_helper=str(self.helper))
                verified = vault_remote_inventory.encrypted_snapshot_inventory(
                    str(destination), crypto_helper=str(self.helper))
                identifiers = sorted(Path(item.relative_path).stem for item in verified.files
                                     if item.relative_path.startswith("objects/"))
                with patch.object(vault_remote_inventory, "_run_helper", return_value={
                    "snapshot_id": result.snapshot_id, "chunk_ids": identifiers,
                    "chunk_sha256": {},
                }):
                    with self.assertRaisesRegex(MigrationError, "inventory is invalid"):
                        vault_remote_inventory.encrypted_snapshot_inventory(
                            str(destination), crypto_helper=str(self.helper))
                reference_path = destination / "refs" / (result.snapshot_id + ".json")
                reference = json.loads(reference_path.read_text(encoding="utf-8"))
                reference["created_at"] = "2025-01-01T00:00:00+00:00"
                reference_path.write_text(json.dumps(reference), encoding="utf-8")
                with self.assertRaisesRegex(MigrationError, "disagrees"):
                    vault_remote_inventory.encrypted_snapshot_inventory(
                        str(destination), crypto_helper=str(self.helper))
            finally:
                self.delete_key(destination)

    def test_remote_inventory_refuses_corrupt_or_linked_chunk(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, destination = root / "source", root / "vault"
            self.fixture(source)
            try:
                backup(str(source), str(destination), crypto_helper=str(self.helper))
                chunk = next((destination / "objects").rglob("*.cvchunk"))
                original = chunk.read_bytes()
                chunk.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
                with self.assertRaises(MigrationError):
                    vault_remote_inventory.encrypted_snapshot_inventory(
                        str(destination), crypto_helper=str(self.helper))
                chunk.unlink()
                chunk.symlink_to(source / ".codex/auth.json")
                with self.assertRaises(MigrationError):
                    vault_remote_inventory.encrypted_snapshot_inventory(
                        str(destination), crypto_helper=str(self.helper))
            finally:
                self.delete_key(destination)

    def test_remote_staging_is_incremental_and_restorable_without_publishing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, destination, reconstructed = (
                root / "source", root / "vault", root / "remote-copy")
            self.fixture(source)
            store = MemoryObjectStore()
            try:
                first = backup(str(source), str(destination), crypto_helper=str(self.helper))
                staged = vault_remote_transfer.stage_encrypted_snapshot(
                    str(destination), store, crypto_helper=str(self.helper))
                self.assertEqual(staged.snapshot_id, first.snapshot_id)
                self.assertEqual(staged.uploaded_files, len(store.objects))
                self.assertEqual(staged.reused_files, 0)
                self.assertNotIn("latest.json", store.objects)
                self.assertNotIn("backup.lock", store.objects)
                self.assertEqual(staged.remote_bytes_checked,
                                 sum(len(value) for value in store.objects.values()))
                self.assertEqual(
                    {item.key: (item.bytes, item.sha256) for item in staged.objects},
                    {key: (len(value), hashlib.sha256(value).hexdigest())
                     for key, value in store.objects.items()},
                )
                self.assertEqual(staged.remote_bytes_checked,
                                 sum(item.bytes for item in staged.objects))
                self.assertEqual(len(staged.objects), staged.uploaded_files)
                claim = staged.receipt()
                self.assertEqual(set(claim), {
                    "version", "snapshot_id", "remote_bytes_checked", "objects"})
                self.assertEqual(claim["version"], 1)
                self.assertEqual(claim["snapshot_id"], first.snapshot_id)
                self.assertEqual(claim["objects"], [
                    {"key": item.key, "bytes": item.bytes, "sha256": item.sha256}
                    for item in staged.objects])
                self.assertNotIn("PRIVATE-ACTIVE-CONTENT", json.dumps(claim))
                self.assertNotIn("NEVER-COPY-AUTH", json.dumps(claim))

                repeated = vault_remote_transfer.stage_encrypted_snapshot(
                    str(destination), store, crypto_helper=str(self.helper))
                self.assertEqual(repeated.uploaded_files, 0)
                self.assertEqual(repeated.reused_files, len(store.objects))
                self.assertEqual(repeated.objects, staged.objects)

                for remote_key, value in store.objects.items():
                    relative = ("vault.json" if remote_key.startswith("metadata/")
                                else remote_key)
                    path = reconstructed / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(value)
                reference = store.objects[f"refs/{first.snapshot_id}.json"]
                (reconstructed / "latest.json").write_bytes(reference)
                verified = verify_snapshot(str(reconstructed), crypto_helper=str(self.helper))
                self.assertEqual(verified.snapshot_id, first.snapshot_id)
                self.assertEqual(verified.transcript_files, 2)

                second = backup(str(source), str(destination), crypto_helper=str(self.helper))
                next_staged = vault_remote_transfer.stage_encrypted_snapshot(
                    str(destination), store, crypto_helper=str(self.helper))
                self.assertEqual(next_staged.snapshot_id, second.snapshot_id)
                self.assertIn(f"metadata/{first.snapshot_id}.json", store.objects)
                self.assertIn(f"metadata/{second.snapshot_id}.json", store.objects)
                self.assertEqual(next_staged.uploaded_files, 3)
                self.assertEqual(next_staged.reused_files, 2)
            finally:
                self.delete_key(destination)

    def test_remote_staging_failure_never_replaces_or_publishes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, destination = root / "source", root / "vault"
            self.fixture(source)
            store = MemoryObjectStore()
            store.fail_on_write = 3
            try:
                backup(str(source), str(destination), crypto_helper=str(self.helper))
                with self.assertRaisesRegex(OSError, "interruption"):
                    vault_remote_transfer.stage_encrypted_snapshot(
                        str(destination), store, crypto_helper=str(self.helper))
                self.assertNotIn("latest.json", store.objects)
                before = dict(store.objects)
                store.fail_on_write = None
                retried = vault_remote_transfer.stage_encrypted_snapshot(
                    str(destination), store, crypto_helper=str(self.helper))
                self.assertEqual(retried.reused_files, len(before))
                self.assertNotIn("latest.json", store.objects)

                key = next(path for path in store.objects if path.startswith("objects/"))
                original = store.objects[key]
                store.objects[key] = original[:-1] + bytes([original[-1] ^ 1])
                with self.assertRaisesRegex(MigrationError, "differs"):
                    vault_remote_transfer.stage_encrypted_snapshot(
                        str(destination), store, crypto_helper=str(self.helper))
                self.assertNotIn("latest.json", store.objects)
            finally:
                self.delete_key(destination)

    def test_remote_staging_reuses_provider_checked_metadata_without_download(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, destination = root / "source", root / "vault"
            self.fixture(source)
            store = MetadataObjectStore()
            try:
                backup(str(source), str(destination), crypto_helper=str(self.helper))
                first = vault_remote_transfer.stage_encrypted_snapshot(
                    str(destination), store, crypto_helper=str(self.helper))
                self.assertEqual(first.uploaded_files, len(store.objects))
                repeated = vault_remote_transfer.stage_encrypted_snapshot(
                    str(destination), store, crypto_helper=str(self.helper))
                self.assertEqual(repeated.uploaded_files, 0)
                self.assertEqual(repeated.reused_files, len(store.objects))
                self.assertEqual(repeated.objects, first.objects)
                key = next(path for path in store.objects if path.startswith("objects/"))
                value = store.objects[key]
                store.objects[key] = value[:-1] + bytes([value[-1] ^ 1])
                with self.assertRaisesRegex(MigrationError, "differs"):
                    vault_remote_transfer.stage_encrypted_snapshot(
                        str(destination), store, crypto_helper=str(self.helper))
                store.checked_metadata = lambda _: ("wrong", "0" * 64)
                with self.assertRaisesRegex(MigrationError, "invalid verification metadata"):
                    vault_remote_transfer.stage_encrypted_snapshot(
                        str(destination), store, crypto_helper=str(self.helper))
            finally:
                self.delete_key(destination)

    def test_remote_staging_refuses_link_swapped_after_inventory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, destination = root / "source", root / "vault"
            self.fixture(source)
            store = MemoryObjectStore()
            try:
                backup(str(source), str(destination), crypto_helper=str(self.helper))
                inventory = vault_remote_inventory.encrypted_snapshot_inventory(
                    str(destination), crypto_helper=str(self.helper))
                chunk = next((destination / "objects").rglob("*.cvchunk"))
                chunk.unlink()
                chunk.symlink_to(source / ".codex/auth.json")
                with patch.object(vault_remote_transfer, "encrypted_snapshot_inventory",
                                  return_value=inventory):
                    with self.assertRaises(MigrationError):
                        vault_remote_transfer.stage_encrypted_snapshot(
                            str(destination), store, crypto_helper=str(self.helper))
                self.assertNotIn("latest.json", store.objects)
                self.assertFalse(any(b"NEVER-COPY-AUTH" in value
                                     for value in store.objects.values()))
            finally:
                self.delete_key(destination)

    def test_remote_staging_refuses_same_size_chunk_changed_after_verification(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, destination = root / "source", root / "vault"
            self.fixture(source)
            store = MemoryObjectStore()
            try:
                backup(str(source), str(destination), crypto_helper=str(self.helper))
                inventory = vault_remote_inventory.encrypted_snapshot_inventory(
                    str(destination), crypto_helper=str(self.helper))
                chunk = next((destination / "objects").rglob("*.cvchunk"))
                original = chunk.read_bytes()
                changed = b"SECRET-NOT-ENCRYPTED" + original[len(b"SECRET-NOT-ENCRYPTED"):]
                self.assertEqual(len(changed), len(original))
                chunk.write_bytes(changed)
                with patch.object(vault_remote_transfer, "encrypted_snapshot_inventory",
                                  return_value=inventory):
                    with self.assertRaisesRegex(MigrationError, "changed after"):
                        vault_remote_transfer.stage_encrypted_snapshot(
                            str(destination), store, crypto_helper=str(self.helper))
                self.assertFalse(any(b"SECRET-NOT-ENCRYPTED" in value
                                     for value in store.objects.values()))
            finally:
                self.delete_key(destination)

    def test_remote_staging_refuses_same_size_manifest_changed_after_verification(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, destination = root / "source", root / "vault"
            self.fixture(source)
            store = MemoryObjectStore()
            try:
                backup(str(source), str(destination), crypto_helper=str(self.helper))
                inventory = vault_remote_inventory.encrypted_snapshot_inventory(
                    str(destination), crypto_helper=str(self.helper))
                manifest = next((destination / "manifests").glob("*.cvmanifest"))
                original = manifest.read_bytes()
                marker = b"SECRET-NOT-ENCRYPTED"
                manifest.write_bytes(marker + original[len(marker):])
                with patch.object(vault_remote_transfer, "encrypted_snapshot_inventory",
                                  return_value=inventory):
                    with self.assertRaisesRegex(MigrationError, "changed after"):
                        vault_remote_transfer.stage_encrypted_snapshot(
                            str(destination), store, crypto_helper=str(self.helper))
                self.assertFalse(any(marker in value for value in store.objects.values()))
                self.assertFalse(any(key.startswith("manifests/") for key in store.objects))
            finally:
                self.delete_key(destination)

    def test_remote_staging_uploads_only_frozen_verified_ciphertext(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, destination = root / "source", root / "vault"
            self.fixture(source)
            try:
                backup(str(source), str(destination), crypto_helper=str(self.helper))
                chunk = next((destination / "objects").rglob("*.cvchunk"))
                chunk_key = chunk.relative_to(destination).as_posix()
                original = chunk.read_bytes()
                marker = b"SECRET-NOT-ENCRYPTED"

                class MutatingStore(MemoryObjectStore):
                    def put_if_absent(self, key, stream, length):
                        if key == chunk_key:
                            chunk.write_bytes(marker + original[len(marker):])
                        super().put_if_absent(key, stream, length)

                store = MutatingStore()
                with self.assertRaises(MigrationError):
                    vault_remote_transfer.stage_encrypted_snapshot(
                        str(destination), store, crypto_helper=str(self.helper))
                self.assertEqual(store.objects[chunk_key], original)
                self.assertFalse(any(marker in value for value in store.objects.values()))
            finally:
                self.delete_key(destination)

    def test_hosted_recovery_requires_reimported_key_then_resumes_without_live_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, destination = root / "source", root / "vault"
            recovered, transcripts = root / "hosted-recovery", root / "transcripts"
            self.fixture(source)
            store = MemoryObjectStore()
            try:
                saved = backup(str(source), str(destination), crypto_helper=str(self.helper))
                staged = vault_remote_transfer.stage_encrypted_snapshot(
                    str(destination), store, crypto_helper=str(self.helper))
                self.delete_key(destination)
                with self.assertRaises(MigrationError):
                    vault_remote_recovery.download_encrypted_snapshot(
                        str(source), str(recovered), store, staged.receipt(),
                        max_bytes=1024 * 1024, crypto_helper=str(self.helper))
                self.assertFalse((recovered / "latest.json").exists())
                self.assertTrue((recovered / "vault.json").is_file())
                (recovered / "vault.json.cvdownload").write_bytes(b"interrupted ciphertext")

                import_recovery_key(
                    str(recovered), saved.recovery_key, crypto_helper=str(self.helper))
                result = vault_remote_recovery.download_encrypted_snapshot(
                    str(source), str(recovered), store, staged.receipt(),
                    max_bytes=1024 * 1024, crypto_helper=str(self.helper))
                self.assertEqual(result.snapshot_id, saved.snapshot_id)
                self.assertEqual(result.downloaded_files, 0)
                self.assertEqual(result.reused_files, len(staged.objects))
                self.assertEqual(result.transcript_files, 2)
                self.assertFalse((recovered / ".hosted-recovery.json").exists())
                self.assertFalse((recovered / "vault.json.cvdownload").exists())
                self.assertEqual(verify_snapshot(str(recovered), crypto_helper=str(self.helper))
                                 .snapshot_id, saved.snapshot_id)
                restore_snapshot(str(source), str(recovered), str(transcripts),
                                 crypto_helper=str(self.helper))
                self.assertEqual(
                    (transcripts / "sessions/2026/09/17/active.jsonl").read_bytes(),
                    (source / ".codex/sessions/2026/09/17/active.jsonl").read_bytes())
                self.assertEqual(
                    (transcripts / "archived_sessions/archived.jsonl").read_bytes(),
                    (source / ".codex/archived_sessions/archived.jsonl").read_bytes())
                self.assertEqual((source / ".codex/auth.json").read_text(), "NEVER-COPY-AUTH")
                self.assertFalse((recovered / "auth.json").exists())
            finally:
                self.delete_key(destination)

    def test_hosted_recovery_retries_interrupted_read_and_rejects_corruption(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, destination = root / "source", root / "vault"
            recovered = root / "hosted-recovery"
            self.fixture(source)
            store = MemoryObjectStore()
            try:
                backup(str(source), str(destination), crypto_helper=str(self.helper))
                staged = vault_remote_transfer.stage_encrypted_snapshot(
                    str(destination), store, crypto_helper=str(self.helper))
                original_read = store.open_read
                reads = 0

                def interrupted(key):
                    nonlocal reads
                    reads += 1
                    if reads == 2:
                        raise OSError("disposable download interruption")
                    return original_read(key)

                store.open_read = interrupted
                with self.assertRaisesRegex(OSError, "interruption"):
                    vault_remote_recovery.download_encrypted_snapshot(
                        str(source), str(recovered), store, staged.receipt(),
                        max_bytes=1024 * 1024, crypto_helper=str(self.helper))
                self.assertFalse((recovered / "latest.json").exists())
                store.open_read = original_read
                damaged_key = next(key for key in store.objects if key.startswith("objects/"))
                original = store.objects[damaged_key]
                store.objects[damaged_key] = original[:-1] + bytes([original[-1] ^ 1])
                with self.assertRaisesRegex(MigrationError, "differs from its receipt"):
                    vault_remote_recovery.download_encrypted_snapshot(
                        str(source), str(recovered), store, staged.receipt(),
                        max_bytes=1024 * 1024, crypto_helper=str(self.helper))
                self.assertFalse((recovered / "latest.json").exists())
                store.objects[damaged_key] = original
                result = vault_remote_recovery.download_encrypted_snapshot(
                    str(source), str(recovered), store, staged.receipt(),
                    max_bytes=1024 * 1024, crypto_helper=str(self.helper))
                self.assertGreaterEqual(result.reused_files, 1)
                self.assertEqual(result.transcript_files, 2)
            finally:
                self.delete_key(destination)

    def test_hosted_recovery_rejects_unsafe_receipt_and_unrelated_destination(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, destination = root / "source", root / "vault"
            recovered = root / "hosted-recovery"
            self.fixture(source)
            store = MemoryObjectStore()
            try:
                backup(str(source), str(destination), crypto_helper=str(self.helper))
                staged = vault_remote_transfer.stage_encrypted_snapshot(
                    str(destination), store, crypto_helper=str(self.helper))
                receipt = staged.receipt()
                receipt["objects"][0]["key"] = "../auth.json"
                with self.assertRaisesRegex(MigrationError, "receipt is invalid"):
                    vault_remote_recovery.download_encrypted_snapshot(
                        str(source), str(recovered), store, receipt,
                        max_bytes=1024 * 1024, crypto_helper=str(self.helper))
                self.assertFalse(recovered.exists())
                with self.assertRaisesRegex(MigrationError, "size limit"):
                    vault_remote_recovery.download_encrypted_snapshot(
                        str(source), str(recovered), store, staged.receipt(),
                        max_bytes=1, crypto_helper=str(self.helper))
                self.assertFalse(recovered.exists())

                recovered.mkdir(mode=0o700)
                (recovered / "keep.txt").write_text("keep")
                with self.assertRaisesRegex(MigrationError, "not an interrupted"):
                    vault_remote_recovery.download_encrypted_snapshot(
                        str(source), str(recovered), store, staged.receipt(),
                        max_bytes=1024 * 1024, crypto_helper=str(self.helper))
                self.assertEqual((recovered / "keep.txt").read_text(), "keep")
                with self.assertRaisesRegex(MigrationError, "outside"):
                    vault_remote_recovery.download_encrypted_snapshot(
                        str(source), str(source / ".codex/recovered"), store,
                        staged.receipt(), max_bytes=1024 * 1024,
                        crypto_helper=str(self.helper))
                running_home = root / "running-home"
                (running_home / ".codex").mkdir(parents=True)
                with patch.object(vault_remote_recovery.Path, "home",
                                  return_value=running_home):
                    with self.assertRaisesRegex(MigrationError, "outside"):
                        vault_remote_recovery.download_encrypted_snapshot(
                            str(source), str(running_home / ".codex/recovered"), store,
                            staged.receipt(), max_bytes=1024 * 1024,
                            crypto_helper=str(self.helper))
            finally:
                self.delete_key(destination)

    def test_hosted_recovery_refuses_link_swapped_in_partial_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, destination = root / "source", root / "vault"
            recovered = root / "hosted-recovery"
            self.fixture(source)
            store = MemoryObjectStore()
            try:
                backup(str(source), str(destination), crypto_helper=str(self.helper))
                staged = vault_remote_transfer.stage_encrypted_snapshot(
                    str(destination), store, crypto_helper=str(self.helper))
                original_read = store.open_read

                def interrupt_after_metadata(key):
                    if key.startswith("objects/"):
                        raise OSError("disposable interruption")
                    return original_read(key)

                store.open_read = interrupt_after_metadata
                with self.assertRaisesRegex(OSError, "interruption"):
                    vault_remote_recovery.download_encrypted_snapshot(
                        str(source), str(recovered), store, staged.receipt(),
                        max_bytes=1024 * 1024, crypto_helper=str(self.helper))
                chunk_key = next(item.key for item in staged.objects
                                 if item.key.startswith("objects/"))
                prefix = recovered / "objects" / chunk_key.split("/")[1]
                prefix.rmdir()
                prefix.symlink_to(source / ".codex")
                store.open_read = original_read
                with self.assertRaises(MigrationError):
                    vault_remote_recovery.download_encrypted_snapshot(
                        str(source), str(recovered), store, staged.receipt(),
                        max_bytes=1024 * 1024, crypto_helper=str(self.helper))
                self.assertEqual((source / ".codex/auth.json").read_text(), "NEVER-COPY-AUTH")
                self.assertFalse((recovered / "latest.json").exists())
            finally:
                self.delete_key(destination)

    def test_hosted_manifest_limit_fails_before_upload(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, destination = root / "source", root / "vault"
            self.fixture(source)
            try:
                backup(str(source), str(destination), crypto_helper=str(self.helper))
                with patch.object(vault_remote_inventory,
                                  "MAX_ENCRYPTED_MANIFEST_BYTES", 10):
                    with self.assertRaisesRegex(MigrationError, "unsupported"):
                        vault_remote_inventory.encrypted_snapshot_inventory(
                            str(destination), crypto_helper=str(self.helper))
            finally:
                self.delete_key(destination)

    def test_storage_usage_refuses_linked_entries(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            vault = root / "vault"
            vault.mkdir()
            (vault / "regular").write_bytes(b"fixture")
            (vault / "linked").symlink_to(root / "outside")
            with self.assertRaisesRegex(MigrationError, "unsupported storage entry"):
                vault_storage_usage(str(vault))

    @unittest.skipUnless(
        os.environ.get("CODEX_MIGRATE_LARGE_HISTORY_PROBE") == "1",
        "opt-in physical large-history probe",
    )
    def test_large_history_incremental_backup_keeps_unchanged_chunks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "vault"
            sessions = source / ".codex/sessions/2026/09/24"
            sessions.mkdir(parents=True)
            for index in range(2048):
                (sessions / f"thread-{index:04d}.jsonl").write_text(
                    json.dumps({"thread": index, "text": f"synthetic-{index:04d}"}) + "\n",
                    encoding="utf-8",
                )
            try:
                first = backup(str(source), str(destination), crypto_helper=str(self.helper))
                self.assertEqual(first.transcript_files, 2048)
                self.assertEqual(
                    verify_snapshot(str(destination), crypto_helper=str(self.helper)).transcript_files,
                    2048,
                )
                first_objects = set((destination / "objects").rglob("*.cvchunk"))
                changed = sessions / "thread-1024.jsonl"
                changed.write_text(changed.read_text(encoding="utf-8") +
                                   json.dumps({"text": "later synthetic work"}) + "\n",
                                   encoding="utf-8")
                second = backup(str(source), str(destination), crypto_helper=str(self.helper))
                self.assertEqual(second.transcript_files, 2048)
                self.assertNotEqual(second.snapshot_id, first.snapshot_id)
                second_objects = set((destination / "objects").rglob("*.cvchunk"))
                self.assertEqual(len(second_objects - first_objects), 1)
                self.assertEqual(
                    verify_snapshot(str(destination), crypto_helper=str(self.helper)).snapshot_id,
                    second.snapshot_id,
                )
            finally:
                self.delete_key(destination)

    def test_tampered_chunk_fails_closed_without_new_reference(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "vault"
            self.fixture(source)
            try:
                first = backup(
                    str(source), str(destination), crypto_helper=str(self.helper),
                    chunk_size=64 * 1024,
                )
                chunk = next((destination / "objects").rglob("*.cvchunk"))
                content = bytearray(chunk.read_bytes())
                content[len(content) // 2] ^= 1
                chunk.write_bytes(content)
                with self.assertRaisesRegex(MigrationError, "no new snapshot"):
                    backup(
                        str(source), str(destination), crypto_helper=str(self.helper),
                        chunk_size=64 * 1024,
                    )
                references = list((destination / "refs").glob("*.json"))
                self.assertEqual(len(references), 1)
                latest = json.loads((destination / "latest.json").read_text(encoding="utf-8"))
                self.assertEqual(latest["snapshot_id"], first.snapshot_id)
            finally:
                self.delete_key(destination)

    def test_compressed_transcript_is_lossless_incremental_and_authenticated(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "vault"
            restored = root / "restored"
            self.fixture(source)
            transcript = source / ".codex/sessions/2026/09/17/active.jsonl"
            content = "".join(f"{index:08x}" + "A" * 65528 for index in range(16))
            transcript.write_text(json.dumps({"payload": {"message": {"content": content}}}) + "\n")
            try:
                first = backup(str(source), str(destination), crypto_helper=str(self.helper),
                               chunk_size=64 * 1024)
                objects = sorted((destination / "objects").rglob("*.cvchunk"))
                self.assertLess(sum(path.stat().st_size for path in objects),
                                transcript.stat().st_size // 2)
                self.assertEqual(json.loads((destination / "vault.json").read_text())
                                 ["storage_codec"], "lzfse-v1")
                second = backup(str(source), str(destination), crypto_helper=str(self.helper),
                                chunk_size=64 * 1024)
                self.assertNotEqual(first.snapshot_id, second.snapshot_id)
                self.assertEqual(objects, sorted((destination / "objects").rglob("*.cvchunk")))
                restore_snapshot(str(source), str(destination), str(restored),
                                 snapshot=first.snapshot_id, crypto_helper=str(self.helper))
                self.assertEqual((restored / "sessions/2026/09/17/active.jsonl").read_bytes(),
                                 transcript.read_bytes())
                compressed = min(objects, key=lambda path: path.stat().st_size)
                damaged = bytearray(compressed.read_bytes())
                damaged[len(damaged) // 2] ^= 1
                compressed.write_bytes(damaged)
                with self.assertRaises(MigrationError):
                    verify_snapshot(str(destination), snapshot=first.snapshot_id,
                                    crypto_helper=str(self.helper))
            finally:
                self.delete_key(destination)

    def test_incompressible_chunks_keep_raw_format(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "vault"
            self.fixture(source)
            try:
                backup(str(source), str(destination), crypto_helper=str(self.helper))
                key_id = json.loads((destination / "vault.json").read_text())["key_id"]
                random_bytes = hashlib.shake_256(b"vault-incompressible-fixture").digest(64 * 1024)
                stored = subprocess.run([
                    str(self.helper), "store-chunks", "--key-id", key_id,
                    "--object-dir", str(destination / "objects"),
                    "--chunk-size", str(64 * 1024),
                ], input=random_bytes, check=True, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE)
                chunks = json.loads(stored.stdout)["chunks"]
                self.assertEqual(len(chunks), 1)
                self.assertEqual(set(chunks[0]), {"id", "size"})
                self.assertEqual(chunks[0]["size"], len(random_bytes))
            finally:
                self.delete_key(destination)

    def test_legacy_vault_upgrades_only_after_new_snapshot_verifies(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "vault"
            restored = root / "restored"
            self.fixture(source)
            try:
                first = backup(str(source), str(destination), crypto_helper=str(self.helper))
                metadata_path = destination / "vault.json"
                legacy = json.loads(metadata_path.read_text())
                legacy.pop("storage_codec")
                metadata_path.write_text(json.dumps(legacy))
                self.assertEqual(verify_snapshot(str(destination), snapshot=first.snapshot_id,
                                                 crypto_helper=str(self.helper)).snapshot_id,
                                 first.snapshot_id)
                legacy_chunk = next((destination / "objects").rglob("*.cvchunk"))
                original_ciphertext = legacy_chunk.read_bytes()
                damaged = bytearray(original_ciphertext)
                damaged[len(damaged) // 2] ^= 1
                legacy_chunk.write_bytes(damaged)
                with self.assertRaises(MigrationError):
                    backup(str(source), str(destination), crypto_helper=str(self.helper))
                self.assertNotIn("storage_codec", json.loads(metadata_path.read_text()))
                self.assertEqual(json.loads((destination / "latest.json").read_text())
                                 ["snapshot_id"], first.snapshot_id)
                legacy_chunk.write_bytes(original_ciphertext)
                transcript = source / ".codex/sessions/2026/09/17/active.jsonl"
                transcript.write_text(json.dumps({"payload": {"text": "B" * 200_000}}) + "\n")
                second = backup(str(source), str(destination), crypto_helper=str(self.helper))
                self.assertEqual(json.loads(metadata_path.read_text())["storage_codec"],
                                 "lzfse-v1")
                self.assertEqual(verify_snapshot(str(destination), snapshot=first.snapshot_id,
                                                 crypto_helper=str(self.helper)).snapshot_id,
                                 first.snapshot_id)
                restore_snapshot(str(source), str(destination), str(restored),
                                 snapshot=second.snapshot_id, crypto_helper=str(self.helper))
                self.assertEqual((restored / "sessions/2026/09/17/active.jsonl").read_bytes(),
                                 transcript.read_bytes())
            finally:
                self.delete_key(destination)

    def test_transcript_append_once_during_backup_retries_and_verifies(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "vault"
            restored = root / "restored"
            self.fixture(source)
            transcript = source / ".codex/sessions/2026/09/17/active.jsonl"
            try:
                original_run_helper = vault_backup._run_helper
                stores = 0

                def append_after_first_store(helper, arguments, **kwargs):
                    nonlocal stores
                    result = original_run_helper(helper, arguments, **kwargs)
                    input_file = kwargs.get("input_file")
                    if (arguments[0] == "store-chunks" and input_file is not None
                            and os.fstat(input_file.fileno()).st_ino == transcript.stat().st_ino):
                        stores += 1
                        if stores == 1:
                            with transcript.open("a", encoding="utf-8") as handle:
                                handle.write(json.dumps({"type": "response_item", "payload": "later"}) + "\n")
                    return result

                with patch.object(vault_backup, "_run_helper", side_effect=append_after_first_store):
                    saved = backup(str(source), str(destination), crypto_helper=str(self.helper))
                self.assertEqual(stores, 2)
                self.assertEqual(verify_snapshot(str(destination), crypto_helper=str(self.helper))
                                 .snapshot_id, saved.snapshot_id)
                restore_snapshot(str(source), str(destination), str(restored),
                                 crypto_helper=str(self.helper))
                self.assertEqual((restored / "sessions/2026/09/17/active.jsonl").read_bytes(),
                                 transcript.read_bytes())
            finally:
                self.delete_key(destination)

    def test_transcript_change_during_identity_scan_retries(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "vault"
            self.fixture(source)
            try:
                original_scan = vault_backup.scan_transcript
                scans = 0

                def changed_once(path, relative, titles):
                    nonlocal scans
                    scans += 1
                    if scans == 1:
                        raise TranscriptChanged("A conversation changed during identity inspection.")
                    return original_scan(path, relative, titles)

                with patch.object(vault_backup, "scan_transcript", side_effect=changed_once):
                    saved = backup(str(source), str(destination), crypto_helper=str(self.helper))
                self.assertEqual(scans, saved.transcript_files + 1)
                self.assertEqual(verify_snapshot(str(destination), crypto_helper=str(self.helper))
                                 .snapshot_id, saved.snapshot_id)
            finally:
                self.delete_key(destination)

    def test_transcript_rewrite_during_backup_keeps_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "vault"
            self.fixture(source)
            transcript = source / ".codex/sessions/2026/09/17/active.jsonl"
            try:
                first = backup(str(source), str(destination), crypto_helper=str(self.helper))
                original_run_helper = vault_backup._run_helper
                rewrites = 0

                def rewrite_after_chunk_store(helper, arguments, **kwargs):
                    nonlocal rewrites
                    result = original_run_helper(helper, arguments, **kwargs)
                    input_file = kwargs.get("input_file")
                    if (arguments[0] == "store-chunks" and input_file is not None
                            and os.fstat(input_file.fileno()).st_ino == transcript.stat().st_ino
                            and rewrites < vault_backup.MAX_CHANGED_TRANSCRIPT_ATTEMPTS):
                        rewrites += 1
                        transcript.write_text(
                            transcript.read_text(encoding="utf-8")
                            + json.dumps({"type": "response_item", "payload": str(rewrites)}) + "\n",
                            encoding="utf-8",
                        )
                    return result

                with patch.object(vault_backup, "_run_helper", side_effect=rewrite_after_chunk_store):
                    with self.assertRaisesRegex(MigrationError, "changed during backup"):
                        backup(str(source), str(destination), crypto_helper=str(self.helper))
                self.assertEqual(rewrites, vault_backup.MAX_CHANGED_TRANSCRIPT_ATTEMPTS)
                latest = json.loads((destination / "latest.json").read_text(encoding="utf-8"))
                self.assertEqual(latest["snapshot_id"], first.snapshot_id)
                self.assertEqual(len(list((destination / "refs").glob("*.json"))), 1)
                self.assertEqual(
                    verify_snapshot(str(destination), crypto_helper=str(self.helper)).snapshot_id,
                    first.snapshot_id,
                )
            finally:
                self.delete_key(destination)

    def test_snapshot_can_be_verified_rekeyed_and_restored_to_staging(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "vault"
            restored = root / "restored"
            self.fixture(source)
            try:
                saved = backup(
                    str(source), str(destination), crypto_helper=str(self.helper),
                    chunk_size=64 * 1024,
                )
                checked = verify_snapshot(
                    str(destination), crypto_helper=str(self.helper))
                self.assertEqual(checked.snapshot_id, saved.snapshot_id)
                self.assertEqual(checked.transcript_files, 2)
                self.assertFalse(restored.exists())

                recovery_key = export_recovery_key(
                    str(destination), crypto_helper=str(self.helper))
                self.assertEqual(recovery_key, saved.recovery_key)
                self.delete_key(destination)
                with self.assertRaisesRegex(MigrationError, "no new snapshot"):
                    verify_snapshot(str(destination), crypto_helper=str(self.helper))
                import_recovery_key(
                    str(destination), recovery_key, crypto_helper=str(self.helper))

                result = restore_snapshot(
                    str(source), str(destination), str(restored),
                    crypto_helper=str(self.helper),
                )
                self.assertEqual(result.snapshot_id, saved.snapshot_id)
                self.assertEqual(
                    (restored / "sessions/2026/09/17/active.jsonl").read_text(
                        encoding="utf-8"),
                    (source / ".codex/sessions/2026/09/17/active.jsonl").read_text(
                        encoding="utf-8"),
                )
                self.assertEqual(
                    (restored / "archived_sessions/archived.jsonl").read_text(
                        encoding="utf-8"),
                    (source / ".codex/archived_sessions/archived.jsonl").read_text(
                        encoding="utf-8"),
                )
                self.assertFalse((restored / "auth.json").exists())
                self.assertFalse((restored / "installation_id").exists())
                receipt = json.loads(
                    (restored / "restore-receipt.json").read_text(encoding="utf-8"))
                self.assertEqual(receipt["snapshot_id"], saved.snapshot_id)
                self.assertEqual(receipt["files"], 2)
            finally:
                self.delete_key(destination)

    def test_v1_snapshot_remains_verifiable_and_restorable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "vault"
            restored = root / "restored"
            self.fixture(source)
            try:
                backup(str(source), str(destination), crypto_helper=str(self.helper))
                key_id = json.loads((destination / "vault.json").read_text())["key_id"]
                transcript = source / ".codex/sessions/2026/09/17/active.jsonl"
                stored = subprocess.run([
                    str(self.helper), "store-chunks", "--key-id", key_id,
                    "--object-dir", str(destination / "objects"),
                    "--chunk-size", str(64 * 1024),
                ], input=transcript.read_bytes(), check=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                file_info = json.loads(stored.stdout)
                snapshot_id = str(uuid.uuid4())
                created_at = datetime.now(timezone.utc).isoformat()
                manifest = {
                    "format": "codex-vault-snapshot", "version": 1,
                    "snapshot_id": snapshot_id, "created_at": created_at,
                    "files": [{
                        "collection": "active", "path": "2026/09/17/active.jsonl",
                        "size": file_info["size"], "mtime_ns": transcript.stat().st_mtime_ns,
                        "sha256": file_info["sha256"], "chunks": file_info["chunks"],
                    }],
                }
                sealed = destination / "manifests" / (snapshot_id + ".cvmanifest")
                subprocess.run([
                    str(self.helper), "seal-manifest", "--key-id", key_id,
                    "--snapshot-id", snapshot_id, "--output", str(sealed),
                ], input=json.dumps(manifest).encode(), check=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                reference = {
                    "format": "codex-vault-reference", "version": 1,
                    "snapshot_id": snapshot_id, "created_at": created_at,
                    "manifest": "manifests/" + sealed.name,
                }
                (destination / "refs" / (snapshot_id + ".json")).write_text(
                    json.dumps(reference), encoding="utf-8")
                (destination / "latest.json").write_text(
                    json.dumps(reference), encoding="utf-8")
                self.assertEqual(verify_snapshot(
                    str(destination), snapshot=snapshot_id,
                    crypto_helper=str(self.helper)).snapshot_id, snapshot_id)
                restore_snapshot(str(source), str(destination), str(restored),
                                 snapshot=snapshot_id, crypto_helper=str(self.helper))
                self.assertEqual((restored / "sessions/2026/09/17/active.jsonl").read_bytes(),
                                 transcript.read_bytes())
            finally:
                self.delete_key(destination)

    def test_restore_output_cannot_overlap_live_data_or_vault(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "vault"
            self.fixture(source)
            try:
                backup(
                    str(source), str(destination), crypto_helper=str(self.helper),
                    chunk_size=64 * 1024,
                )
                with self.assertRaisesRegex(MigrationError, "separate"):
                    restore_snapshot(
                        str(source), str(destination), str(source / ".codex/staged"),
                        crypto_helper=str(self.helper),
                    )
                with self.assertRaisesRegex(MigrationError, "separate"):
                    restore_snapshot(
                        str(source), str(destination), str(destination / "restored"),
                        crypto_helper=str(self.helper),
                    )
            finally:
                self.delete_key(destination)

    def test_destination_cannot_overlap_codex_data_or_follow_a_link(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            self.fixture(source)
            with self.assertRaisesRegex(MigrationError, "outside"):
                plan(str(source), str(source / ".codex/vault"))
            linked = root / "linked"
            linked.symlink_to(root / "real")
            with self.assertRaisesRegex(MigrationError, "linked"):
                plan(str(source), str(linked))


if __name__ == "__main__":
    unittest.main()
