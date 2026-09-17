import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile
import unittest

from codex_migrate.errors import MigrationError
from codex_migrate.vault_backup import backup, plan


@unittest.skipUnless(platform.system() == "Darwin", "CryptoKit backup helper requires macOS")
class VaultBackupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory()
        cls.helper = Path(cls.build.name) / "CodexVaultCrypto"
        subprocess.run([
            "xcrun", "swiftc", "-parse-as-library", "-O",
            "-target", platform.machine() + "-apple-macos13.0",
            "desktop/CodexVaultCrypto.swift", "-o", str(cls.helper),
        ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    @classmethod
    def tearDownClass(cls):
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

                stored = b"".join(
                    path.read_bytes() for path in destination.rglob("*") if path.is_file())
                self.assertNotIn(b"PRIVATE-ACTIVE-CONTENT", stored)
                self.assertNotIn(b"PRIVATE-ARCHIVED-CONTENT", stored)
                self.assertNotIn(b"NEVER-COPY-AUTH", stored)
                self.assertNotIn(b"NEVER-COPY-ID", stored)
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
