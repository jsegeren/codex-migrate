import hashlib
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
from codex_migrate.vault_recovery import (
    export_recovery_key, import_recovery_key, list_snapshots, restore_snapshot,
    vault_storage_usage, verify_snapshot,
)


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
                rewritten = False

                def rewrite_after_chunk_store(helper, arguments, **kwargs):
                    nonlocal rewritten
                    result = original_run_helper(helper, arguments, **kwargs)
                    input_file = kwargs.get("input_file")
                    if (arguments[0] == "store-chunks" and input_file is not None
                            and os.fstat(input_file.fileno()).st_ino == transcript.stat().st_ino
                            and not rewritten):
                        transcript.write_text(
                            transcript.read_text(encoding="utf-8")
                            + json.dumps({"type": "response_item", "payload": "later"}) + "\n",
                            encoding="utf-8",
                        )
                        rewritten = True
                    return result

                with patch.object(vault_backup, "_run_helper", side_effect=rewrite_after_chunk_store):
                    with self.assertRaisesRegex(MigrationError, "changed during backup"):
                        backup(str(source), str(destination), crypto_helper=str(self.helper))
                self.assertTrue(rewritten)
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
