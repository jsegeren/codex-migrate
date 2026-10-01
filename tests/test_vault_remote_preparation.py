"""Metadata-only recovery must not imply decryption or download history."""

import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from codex_migrate.errors import MigrationError
from codex_migrate.vault_remote_recovery import (
    download_encrypted_snapshot, import_encrypted_recovery_key, prepare_encrypted_recovery,
)


SNAPSHOT = "11111111-1111-4111-8111-111111111111"
KEY = "22222222-2222-4222-8222-222222222222"


class RemotePreparationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.home = root / "home"
        self.home.mkdir()
        self.output = root / "recovery"
        self.values = {
            "metadata/" + SNAPSHOT + ".json": json.dumps({
                "format": "codex-vault", "version": 1, "key_id": KEY,
                "created_at": "2026-09-30T00:00:00+00:00"}).encode(),
            "manifests/" + SNAPSHOT + ".cvmanifest": b"synthetic encrypted manifest",
            "refs/" + SNAPSHOT + ".json": b"synthetic reference",
        }
        self.receipt = {"version": 1, "snapshot_id": SNAPSHOT,
            "remote_bytes_checked": sum(map(len, self.values.values())),
            "objects": [{"key": key, "bytes": len(value),
                         "sha256": hashlib.sha256(value).hexdigest()}
                        for key, value in self.values.items()]}
        self.reads = []

    def open_read(self, key):
        self.reads.append(key)
        value = self.values.get(key)
        return io.BytesIO(value) if value is not None else None

    def prepare(self):
        return prepare_encrypted_recovery(str(self.home), str(self.output),
            self, self.receipt, max_bytes=1024 * 1024)

    def test_only_metadata_is_read_and_resume_is_not_marked_complete(self):
        with patch("codex_migrate.vault_remote_recovery.verify_snapshot") as verify:
            result = self.prepare()
            self.assertEqual(self.prepare(), result)
            verify.assert_not_called()
        self.assertEqual(self.reads, ["metadata/" + SNAPSHOT + ".json"])
        self.assertEqual(result["status"], "awaiting_recovery_key")
        self.assertEqual(result["key_id"], KEY)
        self.assertEqual(result["encrypted_bytes_expected"],
                         self.receipt["remote_bytes_checked"])
        self.assertEqual({path.name for path in self.output.iterdir()},
                         {"vault.json", ".hosted-recovery.json"})
        self.assertEqual(self.output.stat().st_mode & 0o077, 0)
        self.assertFalse((self.home / ".codex").exists())

    def test_corrupted_or_missing_metadata_cannot_prepare_key_import(self):
        name = next(iter(self.values))
        for corrupted in (b"wrong bytes", None):
            with self.subTest(corrupted=corrupted):
                self.values[name] = corrupted
                with self.assertRaises(MigrationError):
                    self.prepare()
                self.assertFalse((self.output / "vault.json").exists())
                self.assertFalse((self.output / "latest.json").exists())

    def test_receipt_bound_bytes_still_need_valid_metadata_structure(self):
        name = next(iter(self.values))
        self.values[name] = b'{"format":"not-a-vault"}'
        item = self.receipt["objects"][0]
        old_size = item["bytes"]
        item.update(bytes=len(self.values[name]),
                    sha256=hashlib.sha256(self.values[name]).hexdigest())
        self.receipt["remote_bytes_checked"] += item["bytes"] - old_size
        with self.assertRaises(MigrationError):
            self.prepare()
        self.assertFalse((self.output / "latest.json").exists())
        self.assertEqual(len(self.reads), 1)

    def test_size_bound_refuses_before_any_download(self):
        with self.assertRaises(MigrationError):
            prepare_encrypted_recovery(str(self.home), str(self.output),
                self, self.receipt, max_bytes=1)
        self.assertEqual(self.reads, [])
        self.assertFalse(self.output.exists())

    def test_invalid_native_manifest_confirmation_refuses_remaining_objects(self):
        expected = {"snapshot_id": SNAPSHOT, "plaintext_sha256": "a" * 64,
                    "ciphertext_sha256": self.receipt["objects"][-2]["sha256"]}
        replies = [None, {}, {**expected, "snapshot_id": KEY},
                   {**expected, "plaintext_sha256": "not-a-digest"},
                   {**expected, "ciphertext_sha256": "a" * 64},
                   {**expected, "unrecognized": True}]
        for index, reply in enumerate(replies):
            with self.subTest(reply=index):
                output = self.output.with_name("invalid-" + str(index))
                self.reads.clear()
                with patch("codex_migrate.vault_remote_recovery._helper_path",
                           return_value=Path("/synthetic/helper")), patch(
                        "codex_migrate.vault_remote_recovery._run_helper",
                        side_effect=MigrationError("missing recovery key") if reply is None
                        else None, return_value=reply), patch(
                        "codex_migrate.vault_remote_recovery.verify_snapshot") as verify:
                    with self.assertRaises(MigrationError):
                        download_encrypted_snapshot(str(self.home), str(output), self,
                            self.receipt, max_bytes=1024 * 1024)
                    verify.assert_not_called()
                self.assertEqual(self.reads, [self.receipt["objects"][0]["key"],
                                             self.receipt["objects"][-2]["key"]])
                self.assertFalse((output / "latest.json").exists())
                self.assertTrue((output / ".hosted-recovery.json").exists())

    def test_verified_key_import_uses_private_stdin_and_fetches_no_chunks(self):
        secret = "CV1-" + "A" * 43
        with patch("codex_migrate.vault_remote_recovery._helper_path",
                   return_value=Path("/synthetic/helper")), patch(
                "codex_migrate.vault_remote_recovery._run_helper",
                return_value={"key_id": KEY, "imported": True}) as helper:
            result = import_encrypted_recovery_key(str(self.home), str(self.output),
                self, self.receipt, secret, max_bytes=1024 * 1024)
        self.assertEqual(helper.call_args.kwargs, {"input_data": (secret + "\n").encode()})
        arguments = helper.call_args.args[1]
        self.assertEqual(arguments[0], "import-key-verified")
        self.assertNotIn(secret, arguments)
        self.assertEqual(arguments[-1], self.receipt["objects"][-2]["sha256"])
        self.assertNotIn(secret, json.dumps(result))
        self.assertEqual(result["status"], "ready_to_download")
        self.assertEqual(self.reads, [self.receipt["objects"][0]["key"],
                                     self.receipt["objects"][-2]["key"]])
        self.assertFalse((self.output / "latest.json").exists())

    def test_bad_key_syntax_refuses_before_any_fetch_or_folder_creation(self):
        for secret in (None, "", "CV1-wrong", "CV1-" + "A" * 44, "CV1-" + "A" * 43 + "\n"):
            with self.subTest(secret_type=type(secret).__name__):
                with self.assertRaises(MigrationError):
                    import_encrypted_recovery_key(str(self.home), str(self.output),
                        self, self.receipt, secret, max_bytes=1024 * 1024)
        self.assertEqual(self.reads, [])
        self.assertFalse(self.output.exists())

    def test_unconfirmed_key_import_keeps_recovery_incomplete(self):
        with patch("codex_migrate.vault_remote_recovery._helper_path",
                   return_value=Path("/synthetic/helper")), patch(
                "codex_migrate.vault_remote_recovery._run_helper", return_value={}):
            with self.assertRaises(MigrationError):
                import_encrypted_recovery_key(str(self.home), str(self.output), self,
                    self.receipt, "CV1-" + "A" * 43, max_bytes=1024 * 1024)
        self.assertFalse((self.output / "latest.json").exists())
        self.assertTrue((self.output / ".hosted-recovery.json").exists())


if __name__ == "__main__":
    unittest.main()
