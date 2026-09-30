"""Business recovery kits must be durable, private, and never overwrite."""

import json
from pathlib import Path
import tempfile
import unittest
import uuid

from codex_migrate.errors import MigrationError
from codex_migrate.vault_backup import BusinessRecoverySetup, STORAGE_CODEC
from codex_migrate.vault_business_kits import save_business_recovery_kits


class BusinessKitTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        (self.source / ".codex").mkdir(parents=True, mode=0o700)
        self.vault = self.root / "vault"
        self.vault.mkdir(mode=0o700)
        self.kits = self.root / "kits"
        self.kits.mkdir(mode=0o700)
        key_id = str(uuid.uuid4())
        (self.vault / "vault.json").write_text(json.dumps({
            "format": "codex-vault", "version": 1, "storage_codec": STORAGE_CODEC,
            "recovery_mode": "business-v1", "key_id": key_id,
            "created_at": "2026-09-30T00:00:00+00:00",
        }))
        self.setup = BusinessRecoverySetup(key_id, {
            "recovery_key": "CVB1-worker-fixture",
            "envelope": {"version": 1, "key_id": key_id,
                         "role": "worker", "wrapped_key": "cipher-worker"},
        }, {
            "recovery_key": "CVB1-company-fixture",
            "envelope": {"version": 1, "key_id": key_id,
                         "role": "company", "wrapped_key": "cipher-company"},
        })
        self.worker = self.kits / "worker.json"
        self.company = self.kits / "company.json"

    def save(self, worker=None, company=None, setup=None):
        return save_business_recovery_kits(
            str(self.source), str(self.vault), setup or self.setup,
            str(worker or self.worker), str(company or self.company))

    def test_separate_private_nonoverwriting_kits(self):
        result = self.save()
        self.assertEqual(result, {"worker_kit": str(self.worker.resolve()),
                                  "company_kit": str(self.company.resolve())})
        self.assertNotIn("CVB1-", repr(result))
        for role, path in (("worker", self.worker), ("company", self.company)):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(path.read_text())["envelope"]["role"], role)
        original = self.worker.read_bytes()
        with self.assertRaisesRegex(MigrationError, "did not finish"):
            self.save()
        self.assertEqual(self.worker.read_bytes(), original)

    def test_existing_second_kit_prevents_any_secret_write(self):
        self.company.write_text("untouched")
        with self.assertRaisesRegex(MigrationError, "did not finish"):
            self.save()
        self.assertFalse(self.worker.exists())
        self.assertEqual(self.company.read_text(), "untouched")

    def test_rejects_codex_vault_links_public_parent_and_wrong_role(self):
        with self.assertRaisesRegex(MigrationError, "outside Codex"):
            self.save(worker=self.source / ".codex" / "kit.json")
        with self.assertRaisesRegex(MigrationError, "outside Codex"):
            self.save(worker=self.vault / "kit.json")
        linked = self.kits / "linked.json"
        linked.symlink_to(self.worker)
        with self.assertRaises(MigrationError):
            self.save(worker=linked)
        public = self.root / "public"
        public.mkdir(mode=0o777)
        public.chmod(0o755)
        with self.assertRaisesRegex(MigrationError, "private"):
            self.save(worker=public / "kit.json")
        wrong = BusinessRecoverySetup(
            self.setup.key_id, self.setup.company_credential,
            self.setup.worker_credential)
        with self.assertRaisesRegex(MigrationError, "invalid"):
            self.save(setup=wrong)
        self.assertFalse(self.worker.exists())


if __name__ == "__main__":
    unittest.main()
