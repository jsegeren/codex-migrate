"""Native hosted enrollment token stays in Keychain before server claim."""

import hashlib
import json
from pathlib import Path
import platform
import subprocess
import tempfile
import unittest


@unittest.skipUnless(platform.system() == "Darwin", "macOS Keychain required")
class HostedDeviceKeychainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory()
        cls.helper = Path(cls.build.name) / "CodexVaultCrypto"
        subprocess.run([
            "xcrun", "swiftc", "-parse-as-library", "-O", "-D",
            "CODEX_VAULT_TEST_LEGACY_KEYCHAIN", "-target",
            platform.machine() + "-apple-macos13.0",
            "desktop/CodexVaultCrypto.swift", "-o", str(cls.helper),
        ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def command(self, *args, check=True):
        result = subprocess.run([str(self.helper), *args], check=check,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return result, json.loads(result.stdout) if result.returncode == 0 else None

    def test_token_is_saved_before_claim_and_only_its_digest_is_returned(self):
        device_id = None
        try:
            _, created = self.command("hosted-device-create")
            device_id = created["device_id"]
            self.assertNotIn("token", created)
            self.assertRegex(created["token_hash"], r"^[0-9a-f]{64}$")

            _, read = self.command("hosted-device-read", "--device-id", device_id)
            token = read["token"]
            self.assertRegex(token, r"^hv1_[A-Za-z0-9_-]{43}$")
            digest = hashlib.sha256(b"codex-vault-hosted-session-v1\0" +
                                    token.encode("ascii")).hexdigest()
            self.assertEqual(created["token_hash"], digest)
            self.assertEqual(read["token_hash"], digest)
            self.assertNotEqual(token, created["token_hash"])
            _, listed = self.command("hosted-device-list")
            self.assertIn(created, listed["devices"])
            self.assertTrue(all("token" not in item for item in listed["devices"]))
        finally:
            if device_id is not None:
                _, deleted = self.command("hosted-device-delete", "--device-id", device_id)
                self.assertTrue(deleted["deleted"])
        failed, _ = self.command("hosted-device-read", "--device-id", device_id,
                                 check=False)
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(failed.stdout, b"")
        _, listed = self.command("hosted-device-list")
        self.assertFalse(any(item["device_id"] == device_id
                             for item in listed["devices"]))

    def test_business_device_uses_independent_keychain_service_and_digest(self):
        business_id = None
        personal_id = None
        try:
            _, business = self.command("hosted-business-device-create")
            business_id = business["device_id"]
            self.assertNotIn("token", business)
            _, personal = self.command("hosted-device-create")
            personal_id = personal["device_id"]
            _, read = self.command("hosted-business-device-read", "--device-id",
                                   business_id)
            token = read["token"]
            self.assertRegex(token, r"^hvb1_[A-Za-z0-9_-]{43}$")
            digest = hashlib.sha256(b"codex-backup-business-device-v1\0" +
                                    token.encode("ascii")).hexdigest()
            self.assertEqual(business["token_hash"], digest)
            self.assertEqual(read["token_hash"], digest)
            _, listed_business = self.command("hosted-business-device-list")
            _, listed_personal = self.command("hosted-device-list")
            self.assertIn(business, listed_business["devices"])
            self.assertIn(personal, listed_personal["devices"])
            self.assertNotIn(business, listed_personal["devices"])
            self.assertNotIn(personal, listed_business["devices"])
            denied, _ = self.command("hosted-device-read", "--device-id",
                                     business_id, check=False)
            self.assertNotEqual(denied.returncode, 0)
            self.assertEqual(denied.stdout, b"")
            denied, _ = self.command("hosted-business-device-read", "--device-id",
                                     personal_id, check=False)
            self.assertNotEqual(denied.returncode, 0)
            self.assertEqual(denied.stdout, b"")
        finally:
            if business_id is not None:
                self.command("hosted-business-device-delete", "--device-id",
                             business_id)
            if personal_id is not None:
                self.command("hosted-device-delete", "--device-id", personal_id)


if __name__ == "__main__":
    unittest.main()
