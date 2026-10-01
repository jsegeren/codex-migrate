"""Published-source hints may save reads but must not become backup authority."""

from pathlib import Path
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch

from codex_migrate.errors import MigrationError
from codex_migrate.vault_hosted_chunk_journal import HostedChunkJournal
from codex_migrate.vault_hosted_source_index import (
    promote_source_facts, published_source_facts, record_source_facts,
)


ACCOUNT = "11111111-1111-4111-8111-111111111111"
VAULT = "22222222-2222-4222-8222-222222222222"
KEY = "33333333-3333-4333-8333-333333333333"
FIRST = "44444444-4444-4444-8444-444444444444"
SECOND = "55555555-5555-4555-8555-555555555555"
RESERVATION = "66666666-6666-4666-8666-666666666666"
THIRD = "77777777-7777-4777-8777-777777777777"
FOURTH = "88888888-8888-4888-8888-888888888888"
FACTS = {("active", "2026/09/29/thread.jsonl"): (1, 2, 3, 4, 5)}
PAGINATED = ((6, 7, 8, 9, 10), None, None)


class HostedSourceIndexTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "runs"
        self.root.mkdir(mode=0o700)
        def fake_auth(value, *_):
            unsigned = {key: item for key, item in value.items() if key != "mac"}
            return hashlib.sha256(json.dumps(unsigned, sort_keys=True).encode()).hexdigest()
        signer = patch("codex_migrate.vault_hosted_source_index._authenticate",
                       side_effect=fake_auth)
        signer.start()
        self.addCleanup(signer.stop)

    def journal(self, snapshot, base):
        path = self.root / ("snapshot-" + snapshot)
        path.mkdir(mode=0o700, exist_ok=True)
        return HostedChunkJournal(
            path, account_id=ACCOUNT, vault_id=VAULT,
            reservation_id=RESERVATION, snapshot_id=snapshot,
            key_id=KEY, base_snapshot_id=base)

    @staticmethod
    def state(snapshot):
        return {"accountId": ACCOUNT, "vaultId": VAULT,
                "keyId": KEY, "snapshotId": snapshot}

    def test_candidate_is_not_authority_until_publication_then_exact_base_reuses(self):
        with self.journal(FIRST, None) as first:
            record_source_facts(first, FACTS, crypto_helper="/unused")
            record_source_facts(first, FACTS, crypto_helper="/unused")  # exact retry
        with self.journal(SECOND, FIRST) as second:
            self.assertEqual(published_source_facts(second, crypto_helper="/unused"), {})
            promote_source_facts(self.root, self.state(FIRST))
            self.assertEqual(published_source_facts(second, crypto_helper="/unused"), FACTS)
        self.assertTrue((self.root / "source-index.json").is_file())

    def test_paginated_hint_is_authenticated_and_old_index_cannot_skip_attachment_scan(self):
        with self.journal(FIRST, None) as first:
            record_source_facts(first, FACTS, crypto_helper="/unused",
                                paginated=PAGINATED)
        promote_source_facts(self.root, self.state(FIRST))
        with self.journal(SECOND, FIRST) as second:
            self.assertEqual(published_source_facts(
                second, crypto_helper="/unused", include_paginated=True),
                (FACTS, PAGINATED))
        hint = self.root / "source-index.json"
        changed = json.loads(hint.read_text())
        changed["paginated"][0][-1] += 1
        hint.write_text(json.dumps(changed))
        with self.journal(SECOND, FIRST) as second:
            self.assertEqual(published_source_facts(
                second, crypto_helper="/unused", include_paginated=True),
                ({}, None))
        changed["version"] = 3
        unsigned = {key: item for key, item in changed.items() if key != "mac"}
        changed["mac"] = hashlib.sha256(
            json.dumps(unsigned, sort_keys=True).encode()).hexdigest()
        hint.write_text(json.dumps(changed))
        with self.journal(SECOND, FIRST) as second:
            self.assertEqual(published_source_facts(
                second, crypto_helper="/unused", include_paginated=True),
                ({}, None))
        changed["version"] = 1
        del changed["paginated"]
        del changed["attachments_covered"]
        unsigned = {key: item for key, item in changed.items() if key != "mac"}
        changed["mac"] = hashlib.sha256(
            json.dumps(unsigned, sort_keys=True).encode()).hexdigest()
        hint.write_text(json.dumps(changed))
        with self.journal(SECOND, FIRST) as second:
            self.assertEqual(published_source_facts(
                second, crypto_helper="/unused", include_paginated=True),
                ({}, None))

    def test_stale_base_key_or_vault_never_reuses_a_hint(self):
        with self.journal(FIRST, None) as first:
            record_source_facts(first, FACTS, crypto_helper="/unused")
        promote_source_facts(self.root, self.state(FIRST))
        with self.journal(SECOND, None) as no_base:
            self.assertEqual(published_source_facts(no_base, crypto_helper="/unused"), {})
        with self.journal(THIRD, SECOND) as stale:
            self.assertEqual(published_source_facts(stale, crypto_helper="/unused"), {})
        with self.journal(FOURTH, FIRST) as exact:
            self.assertEqual(published_source_facts(exact, crypto_helper="/unused"), FACTS)

    def test_conflicting_retry_and_foreign_promotion_fail_closed(self):
        with self.journal(FIRST, None) as first:
            record_source_facts(first, FACTS, crypto_helper="/unused")
            with self.assertRaisesRegex(MigrationError, "changed on snapshot retry"):
                record_source_facts(first, {("active", "other.jsonl"): (1, 2, 3, 4, 5)},
                                    crypto_helper="/unused")
        with self.assertRaisesRegex(MigrationError, "belongs to another backup"):
            promote_source_facts(self.root, {**self.state(FIRST), "vaultId": SECOND})
        self.assertFalse((self.root / "source-index.json").exists())

    def test_linked_or_world_readable_hint_does_not_silently_fall_back(self):
        with self.journal(FIRST, None) as first:
            record_source_facts(first, FACTS, crypto_helper="/unused")
        promote_source_facts(self.root, self.state(FIRST))
        hint = self.root / "source-index.json"
        hint.chmod(0o644)
        with self.journal(SECOND, FIRST) as second:
            with self.assertRaisesRegex(MigrationError, "unsafe"):
                published_source_facts(second, crypto_helper="/unused")
        hint.chmod(0o600)
        hint.unlink()
        hint.symlink_to(self.root / ("snapshot-" + FIRST) /
                        "source-index-candidate.json")
        with self.journal(SECOND, FIRST) as second:
            with self.assertRaises(MigrationError):
                published_source_facts(second, crypto_helper="/unused")

    def test_a_modified_valid_hint_forces_a_full_source_read(self):
        with self.journal(FIRST, None) as first:
            record_source_facts(first, FACTS, crypto_helper="/unused")
        promote_source_facts(self.root, self.state(FIRST))
        hint = self.root / "source-index.json"
        changed = json.loads(hint.read_text())
        changed["files"][0][-1] += 1
        hint.write_text(json.dumps(changed))
        with self.journal(SECOND, FIRST) as second:
            self.assertEqual(published_source_facts(second, crypto_helper="/unused"), {})

    def test_corrupt_hint_falls_back_without_blocking_the_backup(self):
        with self.journal(FIRST, None) as first:
            record_source_facts(first, FACTS, crypto_helper="/unused")
        promote_source_facts(self.root, self.state(FIRST))
        (self.root / "source-index.json").write_text("{broken")
        with self.journal(SECOND, FIRST) as second:
            self.assertEqual(published_source_facts(second, crypto_helper="/unused"), {})

    def test_corrupt_candidate_is_rebuilt_on_exact_retry(self):
        with self.journal(FIRST, None) as first:
            record_source_facts(first, FACTS, crypto_helper="/unused")
            candidate = first.directory / "source-index-candidate.json"
            candidate.write_text("{broken")
            record_source_facts(first, FACTS, crypto_helper="/unused")
        promote_source_facts(self.root, self.state(FIRST))
        with self.journal(SECOND, FIRST) as second:
            self.assertEqual(published_source_facts(second, crypto_helper="/unused"), FACTS)


if __name__ == "__main__":
    unittest.main()
