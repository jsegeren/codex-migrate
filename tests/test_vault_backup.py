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
from codex_migrate.vault_hosted_chunk_journal import HostedChunkJournal
from codex_migrate.vault_hosted_manifest import stage_hosted_manifest
from codex_migrate.vault_hosted_snapshot_tail import stage_hosted_snapshot_tail
from codex_migrate.vault_hosted_snapshot_stage import stage_hosted_snapshot
from codex_migrate.vault_backup import backup, plan
from codex_migrate.vault_identity import TranscriptChanged
from codex_migrate.vault_recovery import (
    export_recovery_key, import_recovery_key, list_snapshots, restore_snapshot,
    vault_storage_usage, verify_snapshot,
)
from codex_migrate import vault_remote_inventory
from codex_migrate import vault_remote_recovery
from codex_migrate import vault_remote_transfer
from codex_migrate import vault_hosted_snapshot_stage
from codex_migrate.vault_remote_writer import (
    prepare_remote_aware_file, stage_prepared_file,
    stage_remote_aware_file_windowed,
)


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

    def test_manifest_fingerprint_authenticates_exact_sealed_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            created = subprocess.run(
                [str(self.helper), "create-key"], check=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            key_id = json.loads(created.stdout)["key_id"]
            snapshot_id = str(uuid.uuid4())
            manifest = json.dumps({
                "format": "codex-vault-snapshot", "version": 2,
                "snapshot_id": snapshot_id,
                "created_at": "2026-09-27T00:00:00+00:00", "files": [],
            }, sort_keys=True).encode("utf-8")
            sealed = root / "snapshot.cvmanifest"
            try:
                subprocess.run([
                    str(self.helper), "seal-manifest", "--key-id", key_id,
                    "--snapshot-id", snapshot_id, "--output", str(sealed),
                ], input=manifest, check=True, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE)
                fingerprint = subprocess.run([
                    str(self.helper), "manifest-fingerprint", "--key-id", key_id,
                    "--snapshot-id", snapshot_id, "--manifest", str(sealed),
                ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                facts = json.loads(fingerprint.stdout)
                self.assertEqual(facts, {
                    "snapshot_id": snapshot_id,
                    "plaintext_sha256": hashlib.sha256(manifest).hexdigest(),
                    "ciphertext_sha256": hashlib.sha256(sealed.read_bytes()).hexdigest(),
                })
                damaged = root / "damaged.cvmanifest"
                ciphertext = bytearray(sealed.read_bytes())
                ciphertext[-1] ^= 1
                damaged.write_bytes(ciphertext)
                rejected = subprocess.run([
                    str(self.helper), "manifest-fingerprint", "--key-id", key_id,
                    "--snapshot-id", snapshot_id, "--manifest", str(damaged),
                ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.assertNotEqual(rejected.returncode, 0)
            finally:
                subprocess.run([str(self.helper), "delete-key", "--key-id", key_id],
                               check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def test_hosted_manifest_retry_reuses_exact_ciphertext_and_refuses_reseal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            created = subprocess.run(
                [str(self.helper), "create-key"], check=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            key_id = json.loads(created.stdout)["key_id"]
            snapshot_id = str(uuid.uuid4())
            manifest = {
                "format": "codex-vault-snapshot", "version": 2,
                "snapshot_id": snapshot_id,
                "created_at": "2026-09-27T00:00:00+00:00", "files": [],
            }
            directory = root / "journal"
            directory.mkdir(mode=0o700)
            identity = {
                "account_id": str(uuid.uuid4()), "vault_id": str(uuid.uuid4()),
                "reservation_id": str(uuid.uuid4()), "snapshot_id": snapshot_id,
                "key_id": key_id,
            }

            class Client:
                def __init__(self):
                    self.store = MetadataObjectStore()

                def object_store(self, reservation_id, expected, *, apply=False):
                    self.assertion(reservation_id == identity["reservation_id"] and apply)
                    return self.store

                @staticmethod
                def assertion(condition):
                    if not condition:
                        raise AssertionError("wrong hosted reservation")

            client = Client()
            sealed = directory / "manifests" / (snapshot_id + ".cvmanifest")
            try:
                with HostedChunkJournal(directory, **identity) as journal:
                    first = stage_hosted_manifest(manifest, journal, client,
                                                  crypto_helper=str(self.helper), apply=True)
                    self.assertEqual(first.key, "manifests/" + snapshot_id + ".cvmanifest")
                    ciphertext = sealed.read_bytes()
                    self.assertEqual(client.store.writes, 1)
                with HostedChunkJournal(directory, **identity) as journal:
                    second = stage_hosted_manifest(manifest, journal, client,
                                                   crypto_helper=str(self.helper), apply=True)
                    self.assertEqual(second, first)
                    self.assertEqual(sealed.read_bytes(), ciphertext)
                    self.assertEqual(client.store.writes, 1)
                    client.store.objects[first.key] = b"damaged ciphertext"
                    with self.assertRaisesRegex(MigrationError, "differs"):
                        stage_hosted_manifest(manifest, journal, client,
                                              crypto_helper=str(self.helper), apply=True)
                    client.store.objects[first.key] = ciphertext
                    changed = {**manifest, "created_at": "2026-09-28T00:00:00+00:00"}
                    with self.assertRaisesRegex(MigrationError, "does not match"):
                        stage_hosted_manifest(changed, journal, client,
                                              crypto_helper=str(self.helper), apply=True)
                    sealed.unlink()
                    with self.assertRaisesRegex(MigrationError, "missing"):
                        stage_hosted_manifest(manifest, journal, client,
                                              crypto_helper=str(self.helper), apply=True)
            finally:
                subprocess.run([str(self.helper), "delete-key", "--key-id", key_id],
                               check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def test_hosted_snapshot_tail_stages_exact_three_object_graph(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            created = subprocess.run(
                [str(self.helper), "create-key"], check=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            key_id = json.loads(created.stdout)["key_id"]
            snapshot_id = str(uuid.uuid4())
            created_at = "2026-09-27T00:00:00+00:00"
            metadata = {"format": "codex-vault", "version": 1,
                        "key_id": key_id, "created_at": created_at}
            manifest = {"format": "codex-vault-snapshot", "version": 2,
                        "snapshot_id": snapshot_id, "created_at": created_at,
                        "files": []}
            directory = root / "journal"
            directory.mkdir(mode=0o700)
            identity = {
                "account_id": str(uuid.uuid4()), "vault_id": str(uuid.uuid4()),
                "reservation_id": str(uuid.uuid4()), "snapshot_id": snapshot_id,
                "key_id": key_id,
            }

            class Client:
                def __init__(self):
                    self.store = MetadataObjectStore()

                def object_store(self, reservation_id, expected, *, apply=False):
                    if reservation_id != identity["reservation_id"] or apply is not True:
                        raise AssertionError("wrong hosted reservation")
                    return self.store

            client = Client()
            try:
                with HostedChunkJournal(directory, **identity) as journal:
                    objects = stage_hosted_snapshot_tail(
                        metadata, manifest, {}, journal, client,
                        crypto_helper=str(self.helper), apply=True)
                    self.assertEqual([item.key for item in objects], [
                        "metadata/" + snapshot_id + ".json",
                        "manifests/" + snapshot_id + ".cvmanifest",
                        "refs/" + snapshot_id + ".json",
                    ])
                    self.assertEqual(client.store.writes, 3)
                with HostedChunkJournal(directory, **identity) as journal:
                    self.assertEqual(stage_hosted_snapshot_tail(
                        metadata, manifest, {}, journal, client,
                        crypto_helper=str(self.helper), apply=True), objects)
                    self.assertEqual(client.store.writes, 3)
                    changed = {**metadata, "created_at": "2026-09-28T00:00:00+00:00"}
                    with self.assertRaisesRegex(MigrationError, "changed on retry"):
                        stage_hosted_snapshot_tail(
                            changed, manifest, {}, journal, client,
                            crypto_helper=str(self.helper), apply=True)
                    client.store.objects[objects[-1].key] = b"damaged reference"
                    with self.assertRaisesRegex(MigrationError, "differs"):
                        stage_hosted_snapshot_tail(
                            metadata, manifest, {}, journal, client,
                            crypto_helper=str(self.helper), apply=True)
            finally:
                subprocess.run([str(self.helper), "delete-key", "--key-id", key_id],
                               check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def test_hosted_whole_snapshot_stages_without_full_local_vault(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir(mode=0o700)
            self.fixture(source)
            created = subprocess.run(
                [str(self.helper), "create-key"], check=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            key_id = json.loads(created.stdout)["key_id"]
            snapshot_id = str(uuid.uuid4())
            metadata = {"format": "codex-vault", "version": 1,
                        "key_id": key_id,
                        "created_at": "2026-09-27T00:00:00+00:00"}
            directory = root / "journal"
            directory.mkdir(mode=0o700)
            identity = {
                "account_id": str(uuid.uuid4()), "vault_id": str(uuid.uuid4()),
                "reservation_id": str(uuid.uuid4()), "snapshot_id": snapshot_id,
                "key_id": key_id,
            }

            class Client:
                def __init__(self):
                    self.store = MetadataObjectStore()

                def published_chunks(self, ids):
                    return {}

                def object_store(self, reservation_id, expected, *, apply=False):
                    if reservation_id != identity["reservation_id"] or apply is not True:
                        raise AssertionError("wrong hosted reservation")
                    return self.store

            client = Client()
            try:
                with HostedChunkJournal(directory, **identity) as journal:
                    first = stage_hosted_snapshot(
                        str(source), metadata, [], journal, client,
                        crypto_helper=str(self.helper), chunk_size=64 * 1024,
                        window_bytes=64 * 1024, apply=True)
                    self.assertEqual(first.snapshot_id, snapshot_id)
                    self.assertEqual(first.transcript_files, 2)
                    self.assertEqual(len(first.objects), 5)
                    self.assertEqual(client.store.writes, 5)
                    self.assertFalse(list((directory / "scratch").rglob("*.cvchunk")))
                    combined = b"".join(client.store.objects.values())
                    self.assertNotIn(b"PRIVATE-ACTIVE-CONTENT", combined)
                    self.assertNotIn(b"PRIVATE-ARCHIVED-CONTENT", combined)
                    self.assertNotIn(b"NEVER-COPY-AUTH", combined)
                    self.assertNotIn(b"NEVER-COPY-ID", combined)
                with HostedChunkJournal(directory, **identity) as journal:
                    second = stage_hosted_snapshot(
                        str(source), metadata, [], journal, client,
                        crypto_helper=str(self.helper), chunk_size=64 * 1024,
                        window_bytes=64 * 1024, apply=True)
                    self.assertEqual(second, first)
                    self.assertEqual(client.store.writes, 5)
                    original_stage = vault_hosted_snapshot_stage.stage_remote_aware_file_windowed
                    staged_count = 0

                    def mutate_prior_transcript(*args, **kwargs):
                        nonlocal staged_count
                        result = original_stage(*args, **kwargs)
                        staged_count += 1
                        if staged_count == 2:
                            prior = source / ".codex/archived_sessions/archived.jsonl"
                            with prior.open("a", encoding="utf-8") as handle:
                                handle.write(json.dumps({"type": "response_item",
                                                         "payload": {"role": "user"}}) + "\n")
                        return result

                    with patch.object(vault_hosted_snapshot_stage,
                                      "stage_remote_aware_file_windowed",
                                      side_effect=mutate_prior_transcript):
                        with self.assertRaisesRegex(MigrationError,
                                                    "changed after hosted staging"):
                            stage_hosted_snapshot(
                                str(source), metadata, [], journal, client,
                                crypto_helper=str(self.helper), chunk_size=64 * 1024,
                                window_bytes=64 * 1024, apply=True)
            finally:
                subprocess.run([str(self.helper), "delete-key", "--key-id", key_id],
                               check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

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

    def test_recreated_local_ciphertext_cannot_replace_remote_chunk(self):
        """Hosted-only cleanup needs remote-aware reuse, not local re-encryption."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            first_vault = root / "first-vault"
            recreated_vault = root / "recreated-vault"
            self.fixture(source)
            try:
                first = backup(str(source), str(first_vault),
                               crypto_helper=str(self.helper))
                store = MemoryObjectStore()
                vault_remote_transfer.stage_encrypted_snapshot(
                    str(first_vault), store, snapshot=first.snapshot_id,
                    crypto_helper=str(self.helper))

                # Preserve the same encryption key, but deliberately remove
                # the local ciphertext cache as a naive hosted-only flow might.
                recreated_vault.mkdir(mode=0o700)
                metadata = recreated_vault / "vault.json"
                metadata.write_bytes((first_vault / "vault.json").read_bytes())
                metadata.chmod(0o600)
                second = backup(str(source), str(recreated_vault),
                                crypto_helper=str(self.helper))
                first_chunks = vault_remote_inventory.encrypted_snapshot_inventory(
                    str(first_vault), snapshot=first.snapshot_id,
                    crypto_helper=str(self.helper)).files[1:-2]
                second_chunks = vault_remote_inventory.encrypted_snapshot_inventory(
                    str(recreated_vault), snapshot=second.snapshot_id,
                    crypto_helper=str(self.helper)).files[1:-2]
                self.assertEqual([item.remote_key for item in first_chunks],
                                 [item.remote_key for item in second_chunks])
                self.assertNotEqual([item.sha256 for item in first_chunks],
                                    [item.sha256 for item in second_chunks])
                with self.assertRaisesRegex(MigrationError, "remote Vault object.*differs"):
                    vault_remote_transfer.stage_encrypted_snapshot(
                        str(recreated_vault), store, snapshot=second.snapshot_id,
                        crypto_helper=str(self.helper))
                self.assertIn(f"refs/{first.snapshot_id}.json", store.objects)
            finally:
                self.delete_key(first_vault)

    def test_native_remote_planner_matches_stored_chunk_candidates_without_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            vault = root / "vault"
            self.fixture(source)
            try:
                backup(str(source), str(vault), crypto_helper=str(self.helper))
                key_id = json.loads((vault / "vault.json").read_text())["key_id"]
                sample = root / "sample"
                content = b"A" * 65536 + b"B" * 65536
                sample.write_bytes(content)
                objects = root / "planned-objects"
                with sample.open("rb") as stream:
                    planned = subprocess.run([
                        str(self.helper), "plan-chunks", "--key-id", key_id,
                        "--chunk-size", "65536",
                    ], stdin=stream, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, check=True)
                self.assertFalse(objects.exists())
                self.assertNotIn(content[:64], planned.stdout)
                plan = json.loads(planned.stdout)
                self.assertEqual(plan["sha256"], hashlib.sha256(content).hexdigest())
                self.assertEqual(plan["size"], len(content))
                self.assertEqual(len(plan["chunks"]), 2)
                self.assertTrue(all(item["compressed_id"] is not None
                                    for item in plan["chunks"]))
                objects.mkdir(mode=0o700)
                with sample.open("rb") as stream:
                    stored = subprocess.run([
                        str(self.helper), "store-chunks", "--key-id", key_id,
                        "--object-dir", str(objects), "--chunk-size", "65536",
                    ], stdin=stream, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, check=True)
                actual = json.loads(stored.stdout)
                self.assertEqual(actual["sha256"], plan["sha256"])
                for candidate, chunk in zip(plan["chunks"], actual["chunks"]):
                    self.assertEqual(candidate["size"], chunk["size"])
                    self.assertIn(chunk["id"],
                                  (candidate["raw_id"], candidate["compressed_id"]))
            finally:
                self.delete_key(vault)

    def test_native_remote_writer_reuses_published_candidates_without_local_copies(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            vault = root / "vault"
            self.fixture(source)
            try:
                backup(str(source), str(vault), crypto_helper=str(self.helper))
                key_id = json.loads((vault / "vault.json").read_text())["key_id"]
                content = b"A" * 65536 + b"B" * 65536 + b"C" * 65536
                planned = subprocess.run([
                    str(self.helper), "plan-chunks", "--key-id", key_id,
                    "--chunk-size", "65536",
                ], input=content, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    check=True)
                plan = json.loads(planned.stdout)
                first, second, third = plan["chunks"]
                self.assertIsNotNone(second["compressed_id"])
                lookup = root / "known.json"
                lookup.write_text(json.dumps({
                    "version": 1,
                    "ids": [first["raw_id"], second["compressed_id"]],
                }))
                lookup.chmod(0o600)
                objects = root / "remote-writer-objects"
                objects.mkdir(mode=0o700)
                command = [
                    str(self.helper), "store-chunks-with-known", "--key-id", key_id,
                    "--chunk-size", "65536", "--object-dir", str(objects),
                    "--known-ids-file", str(lookup),
                    "--expected-sha256", plan["sha256"],
                    "--expected-size", str(plan["size"]),
                ]
                written = subprocess.run(command, input=content,
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                         check=True)
                result = json.loads(written.stdout)
                self.assertEqual(result["sha256"], plan["sha256"])
                self.assertEqual(result["remote_ids"],
                                 [first["raw_id"], second["compressed_id"]])
                self.assertEqual([item["id"] for item in result["chunks"][:2]],
                                 result["remote_ids"])
                self.assertEqual(len(result["local_ids"]), 1)
                self.assertIn(result["chunks"][2]["id"],
                              [third["raw_id"], third["compressed_id"]])
                self.assertEqual(result["local_ids"], [result["chunks"][2]["id"]])
                self.assertEqual(len(list(objects.rglob("*.cvchunk"))), 1)
                self.assertFalse((objects / first["raw_id"][:2] /
                                  (first["raw_id"][2:] + ".cvchunk")).exists())

                changed = subprocess.run(command, input=content[:-1] + b"D",
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.assertNotEqual(changed.returncode, 0)
                self.assertEqual(changed.stdout, b"")

                lookup.chmod(0o644)
                exposed = subprocess.run(command, input=content,
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.assertNotEqual(exposed.returncode, 0)
                self.assertEqual(exposed.stdout, b"")
            finally:
                self.delete_key(vault)

    def test_remote_writer_plans_published_lookup_and_refuses_source_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            vault = root / "vault"
            self.fixture(source)
            try:
                backup(str(source), str(vault), crypto_helper=str(self.helper))
                key_id = json.loads((vault / "vault.json").read_text())["key_id"]
                transcript = root / "synthetic.jsonl"
                transcript.write_bytes(b"A" * 65536 + b"B" * 65536 + b"C" * 65536)
                planned = subprocess.run([
                    str(self.helper), "plan-chunks", "--key-id", key_id,
                    "--chunk-size", "65536",
                ], input=transcript.read_bytes(), stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, check=True)
                candidates = json.loads(planned.stdout)["chunks"]
                known = {candidates[0]["raw_id"]: (65564, "d" * 64),
                         candidates[1]["compressed_id"]: (123, "e" * 64)}

                class Lookup:
                    def __init__(self):
                        self.queries = []

                    def published_chunks(self, ids):
                        self.queries.append(ids)
                        return {item: known[item] for item in ids if item in known}

                scratch = root / "scratch"
                scratch.mkdir(mode=0o700)
                lookup = Lookup()
                with self.assertRaisesRegex(MigrationError, "explicit confirmation"):
                    prepare_remote_aware_file(
                        transcript, scratch, key_id, lookup,
                        crypto_helper=str(self.helper), chunk_size=65536)
                result = prepare_remote_aware_file(
                    transcript, scratch, key_id, lookup,
                    crypto_helper=str(self.helper), chunk_size=65536, apply=True)
                self.assertEqual(set(result.remote_objects), set(known))
                self.assertEqual(result.remote_objects, known)
                self.assertEqual(len(result.local_ids), 1)
                self.assertEqual(len(list(scratch.rglob("*.cvchunk"))), 1)
                self.assertEqual(len(lookup.queries), 1)
                self.assertEqual(len(lookup.queries[0]), 6)

                class ChangingLookup:
                    def published_chunks(self, ids):
                        transcript.write_bytes(b"Z" * (3 * 65536))
                        return {}

                changed_scratch = root / "changed-scratch"
                changed_scratch.mkdir(mode=0o700)
                with self.assertRaisesRegex(MigrationError, "changed during hosted planning"):
                    prepare_remote_aware_file(
                        transcript, changed_scratch, key_id, ChangingLookup(),
                        crypto_helper=str(self.helper), chunk_size=65536, apply=True)
                self.assertEqual(list(changed_scratch.rglob("*.cvchunk")), [])
            finally:
                self.delete_key(vault)

    def test_published_ciphertext_wins_over_valid_but_different_scratch_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            vault = root / "vault"
            self.fixture(source)
            try:
                backup(str(source), str(vault), crypto_helper=str(self.helper))
                key_id = json.loads((vault / "vault.json").read_text())["key_id"]
                content = b"A" * 65536
                objects = root / "scratch"
                objects.mkdir(mode=0o700)
                locally_written = subprocess.run([
                    str(self.helper), "store-chunks", "--key-id", key_id,
                    "--chunk-size", "65536", "--object-dir", str(objects),
                ], input=content, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    check=True)
                selected_id = json.loads(locally_written.stdout)["chunks"][0]["id"]
                lookup = root / "known.json"
                lookup.write_text(json.dumps({"version": 1, "ids": [selected_id]}))
                lookup.chmod(0o600)
                result = subprocess.run([
                    str(self.helper), "store-chunks-with-known", "--key-id", key_id,
                    "--chunk-size", "65536", "--object-dir", str(objects),
                    "--known-ids-file", str(lookup),
                    "--expected-sha256", hashlib.sha256(content).hexdigest(),
                    "--expected-size", str(len(content)),
                ], input=content, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    check=True)
                written = json.loads(result.stdout)
                self.assertEqual(written["remote_ids"], [selected_id])
                self.assertEqual(written["local_ids"], [])
                self.assertEqual(len(list(objects.rglob("*.cvchunk"))), 1)
            finally:
                self.delete_key(vault)

    def test_remote_aware_file_stages_published_and_new_chunks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            vault = root / "vault"
            self.fixture(source)
            try:
                backup(str(source), str(vault), crypto_helper=str(self.helper))
                key_id = json.loads((vault / "vault.json").read_text())["key_id"]
                old_objects = root / "old-objects"
                old_objects.mkdir(mode=0o700)
                old = subprocess.run([
                    str(self.helper), "store-chunks", "--key-id", key_id,
                    "--chunk-size", "65536", "--object-dir", str(old_objects),
                ], input=b"A" * 65536 + b"B" * 65536,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
                published = {}
                store = MetadataObjectStore()
                for chunk in json.loads(old.stdout)["chunks"]:
                    identifier = chunk["id"]
                    key = "objects/" + identifier[:2] + "/" + identifier[2:] + ".cvchunk"
                    ciphertext = (old_objects / identifier[:2] /
                                  (identifier[2:] + ".cvchunk")).read_bytes()
                    store.objects[key] = ciphertext
                    published[identifier] = (len(ciphertext),
                                             hashlib.sha256(ciphertext).hexdigest())

                class Client:
                    def published_chunks(self, ids):
                        return {item: published[item] for item in ids if item in published}

                    def object_store(self, reservation_id, expected, *, apply=False):
                        self_assert = reservation_id == reservation and apply is True
                        if not self_assert or len(expected) != 1:
                            raise AssertionError("unscoped test upload")
                        return store

                transcript = root / "synthetic.jsonl"
                transcript.write_bytes(b"A" * 65536 + b"B" * 65536 + b"C" * 65536)
                scratch = root / "scratch"
                scratch.mkdir(mode=0o700)
                reservation = "44444444-4444-4444-8444-444444444444"
                journal_dir = root / "journal"
                journal_dir.mkdir(mode=0o700)
                client = Client()
                prepared = prepare_remote_aware_file(
                    transcript, scratch, key_id, client,
                    crypto_helper=str(self.helper), chunk_size=65536, apply=True)
                self.assertEqual(set(prepared.remote_objects), set(published))
                self.assertEqual(len(prepared.local_ids), 1)
                with HostedChunkJournal(
                    journal_dir,
                    account_id="11111111-1111-4111-8111-111111111111",
                    vault_id="22222222-2222-4222-8222-222222222222",
                    reservation_id=reservation,
                    snapshot_id="33333333-3333-4333-8333-333333333333",
                    key_id=key_id,
                ) as journal:
                    staged = stage_prepared_file(prepared, scratch, client,
                                                 reservation, journal=journal,
                                                 apply=True)
                    self.assertEqual(len(staged), 3)
                    self.assertEqual(store.writes, 1)
                    self.assertEqual({item.key for item in staged}, set(store.objects))
                    self.assertEqual(set(journal.records), set(prepared.local_ids))
                    staged_again = stage_prepared_file(prepared, scratch, client,
                                                       reservation, journal=journal,
                                                       apply=True)
                    self.assertEqual(staged_again, staged)
                    self.assertEqual(store.writes, 1)
                    broken = next(iter(published))
                    key = "objects/" + broken[:2] + "/" + broken[2:] + ".cvchunk"
                    original = store.objects[key]
                    store.objects[key] = original[:-1] + b"X"
                    with self.assertRaisesRegex(MigrationError, "missing remotely"):
                        stage_prepared_file(prepared, scratch, client,
                                            reservation, journal=journal, apply=True)
                    store.objects[key] = original
                    # A crash-safe retry may reuse a staged chunk without
                    # retaining its local scratch ciphertext.
                    new_id = prepared.local_ids[0]
                    (scratch / new_id[:2] / (new_id[2:] + ".cvchunk")).unlink()
                    retry = prepare_remote_aware_file(
                        transcript, scratch, key_id, client,
                        crypto_helper=str(self.helper), chunk_size=65536,
                        journal=journal, reservation_id=reservation, apply=True)
                    self.assertEqual(retry.local_ids, ())
                    self.assertEqual(set(retry.remote_objects),
                                     {row["id"] for row in retry.chunks})
                    self.assertEqual(stage_prepared_file(
                        retry, scratch, client, reservation, journal=journal,
                        apply=True), staged)
                    self.assertEqual(store.writes, 1)
                    staged_key = "objects/" + new_id[:2] + "/" + new_id[2:] + ".cvchunk"
                    store.objects.pop(staged_key)
                    with self.assertRaisesRegex(MigrationError, "missing or changed remotely"):
                        prepare_remote_aware_file(
                            transcript, scratch, key_id, client,
                            crypto_helper=str(self.helper), chunk_size=65536,
                            journal=journal, reservation_id=reservation, apply=True)
            finally:
                self.delete_key(vault)

    def test_windowed_hosted_stage_bounds_scratch_and_retries_interruption(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            vault = root / "vault"
            self.fixture(source)
            try:
                backup(str(source), str(vault), crypto_helper=str(self.helper))
                key_id = json.loads((vault / "vault.json").read_text())["key_id"]
                transcript = root / "synthetic.jsonl"
                payload = (b"A" * 65536 + b"B" * 65536 +
                           b"C" * 65536 + b"A" * 65536 + b"D" * 65536)
                transcript.write_bytes(payload)
                journal_dir = root / "journal"
                journal_dir.mkdir(mode=0o700)

                class TrackingStore(MetadataObjectStore):
                    def __init__(self):
                        super().__init__()
                        self.peak_scratch_files = 0

                    def put_if_absent(self, key, source_file, length):
                        scratch = journal_dir / "scratch"
                        self.peak_scratch_files = max(
                            self.peak_scratch_files,
                            len(list(scratch.rglob("*.cvchunk"))))
                        return super().put_if_absent(key, source_file, length)

                store = TrackingStore()
                reservation = "44444444-4444-4444-8444-444444444444"

                class Client:
                    def published_chunks(self, ids):
                        return {}

                    def object_store(self, reservation_id, expected, *, apply=False):
                        if reservation_id != reservation or apply is not True:
                            raise AssertionError("unscoped window upload")
                        return store

                client = Client()
                with HostedChunkJournal(
                    journal_dir,
                    account_id="11111111-1111-4111-8111-111111111111",
                    vault_id="22222222-2222-4222-8222-222222222222",
                    reservation_id=reservation,
                    snapshot_id="33333333-3333-4333-8333-333333333333",
                    key_id=key_id,
                ) as journal:
                    with self.assertRaisesRegex(MigrationError, "explicit confirmation"):
                        stage_remote_aware_file_windowed(
                            transcript, key_id, client, reservation, journal,
                            crypto_helper=str(self.helper), chunk_size=65536,
                            window_bytes=2 * 65536)
                    store.fail_on_write = 2
                    with self.assertRaisesRegex(OSError, "interruption"):
                        stage_remote_aware_file_windowed(
                            transcript, key_id, client, reservation, journal,
                            crypto_helper=str(self.helper), chunk_size=65536,
                            window_bytes=2 * 65536, apply=True)
                    self.assertEqual(len(journal.records), 1)
                    self.assertEqual(len(list((journal_dir / "scratch").rglob("*.cvchunk"))), 2)
                    store.fail_on_write = None
                    result = stage_remote_aware_file_windowed(
                        transcript, key_id, client, reservation, journal,
                        crypto_helper=str(self.helper), chunk_size=65536,
                        window_bytes=2 * 65536, apply=True)
                    self.assertEqual(result.sha256, hashlib.sha256(payload).hexdigest())
                    self.assertEqual(result.size, len(payload))
                    self.assertEqual(len(result.chunks), 5)
                    self.assertEqual(len(result.objects), 4)
                    self.assertEqual(len(store.objects), 4)
                    self.assertEqual(len(journal.records), 4)
                    self.assertEqual(list((journal_dir / "scratch").rglob("*.cvchunk")), [])
                    self.assertLessEqual(store.peak_scratch_files, 2)
                    self.assertEqual(store.writes, 5)

                    class ChangingClient(Client):
                        lookups = 0

                        def published_chunks(self, ids):
                            self.lookups += 1
                            if self.lookups == 2:
                                transcript.write_bytes(payload[:2 * 65536] +
                                                       b"Z" + payload[2 * 65536 + 1:])
                            return {}

                    remote_before = dict(store.objects)
                    with self.assertRaises(MigrationError):
                        stage_remote_aware_file_windowed(
                            transcript, key_id, ChangingClient(), reservation, journal,
                            crypto_helper=str(self.helper), chunk_size=65536,
                            window_bytes=2 * 65536, apply=True)
                    self.assertEqual(store.objects, remote_before)
            finally:
                self.delete_key(vault)

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

    def test_one_object_staging_reuses_exact_remote_and_detects_local_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, destination = root / "source", root / "vault"
            self.fixture(source)
            try:
                backup(str(source), str(destination), crypto_helper=str(self.helper))
                inventory = vault_remote_inventory.encrypted_snapshot_inventory(
                    str(destination), crypto_helper=str(self.helper))
                item = next(item for item in inventory.files
                            if item.relative_path.startswith("objects/"))
                store = MemoryObjectStore()
                staged, uploaded = vault_remote_transfer.stage_encrypted_object(
                    destination.resolve(), item, store)
                self.assertTrue(uploaded)
                self.assertEqual(staged.key, item.remote_key)
                self.assertEqual(staged.sha256, item.sha256)
                self.assertEqual(len(store.objects), 1)
                staged_again, uploaded_again = vault_remote_transfer.stage_encrypted_object(
                    destination.resolve(), item, store)
                self.assertFalse(uploaded_again)
                self.assertEqual(staged_again, staged)

                class ReplacingStore(MemoryObjectStore):
                    def put_if_absent(self, key, stream, length):
                        super().put_if_absent(key, stream, length)
                        path = destination / item.relative_path
                        replacement = path.with_name("replacement.cvchunk")
                        replacement.write_bytes(path.read_bytes())
                        replacement.chmod(0o600)
                        os.replace(replacement, path)

                with self.assertRaisesRegex(MigrationError, "changed during remote staging"):
                    vault_remote_transfer.stage_encrypted_object(
                        destination.resolve(), item, ReplacingStore())

                class MutatingStore(MemoryObjectStore):
                    def put_if_absent(self, key, stream, length):
                        super().put_if_absent(key, stream, length)
                        path = destination / item.relative_path
                        original = path.read_bytes()
                        path.write_bytes(original[::-1])

                with self.assertRaisesRegex(MigrationError, "changed during remote staging"):
                    vault_remote_transfer.stage_encrypted_object(
                        destination.resolve(), item, MutatingStore())
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
