from pathlib import Path
import tempfile
import unittest

from codex_migrate.vault_storage import classify_vault_storage


class VaultStorageTests(unittest.TestCase):
    def test_recognizes_current_file_provider_locations(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            for child, provider in (
                ("OneDrive-Personal", "OneDrive"),
                ("GoogleDrive-person@example.com", "Google Drive"),
                ("Dropbox", "Dropbox"),
                ("Box-Box", "Box"),
                ("FutureProvider-account", "a macOS cloud provider"),
            ):
                path = home / "Library/CloudStorage" / child / "Codex Vault"
                result = classify_vault_storage(str(path), str(home))
                self.assertEqual(result.kind, "cloud_sync")
                self.assertEqual(result.provider, provider)
                self.assertEqual(result.off_device_protection,
                                 "possible_unverified")
                self.assertIn("cannot confirm", result.detail)

    def test_recognizes_icloud_drive(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            path = home / "Library/Mobile Documents/com~apple~CloudDocs/Codex Vault"
            result = classify_vault_storage(str(path), str(home))
            self.assertEqual(result.provider, "iCloud Drive")
            self.assertEqual(result.kind, "cloud_sync")

    def test_local_folder_does_not_imply_off_device_protection(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            result = classify_vault_storage(
                str(home / "Documents/Codex Vault"), str(home))
            self.assertEqual(result.kind, "local")
            self.assertEqual(result.off_device_protection, "not_detected")
            self.assertIn("does not protect", result.detail)

    def test_external_volume_remains_unverified(self):
        result = classify_vault_storage(
            "/Volumes/Backup/Codex Vault", "/Users/example")
        self.assertEqual(result.kind, "external_or_network")
        self.assertEqual(result.off_device_protection, "unverified")


if __name__ == "__main__":
    unittest.main()
