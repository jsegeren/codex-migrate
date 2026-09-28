"""Crash and ownership boundaries for opaque hosted upload receipts."""

import json
import hashlib
import os
from pathlib import Path
import tempfile
import unittest

from codex_migrate.errors import MigrationError
from codex_migrate.vault_hosted_chunk_journal import HostedChunkJournal
from codex_migrate.vault_remote_writer import PreparedRemoteFile, stage_prepared_file


IDENTITY = {
    "account_id": "11111111-1111-4111-8111-111111111111",
    "vault_id": "22222222-2222-4222-8222-222222222222",
    "reservation_id": "33333333-3333-4333-8333-333333333333",
    "snapshot_id": "44444444-4444-4444-8444-444444444444",
    "key_id": "55555555-5555-4555-8555-555555555555",
}
CHUNK = "a" * 64
DIGEST = "b" * 64


class HostedChunkJournalTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name) / "journal"
        self.directory.mkdir(mode=0o700)

    def journal(self, **changes):
        return HostedChunkJournal(self.directory, **{**IDENTITY, **changes})

    def test_first_record_is_durable_private_and_reopens(self):
        with self.journal() as journal:
            self.assertEqual(journal.records, {})
            journal.record(CHUNK, 1024, DIGEST)
            journal.record(CHUNK, 1024, DIGEST)
            self.assertEqual(journal.records, {CHUNK: (1024, DIGEST)})
        self.assertEqual((self.directory / "chunks.jsonl").stat().st_mode & 0o077, 0)
        self.assertEqual((self.directory / "journal.json").stat().st_mode & 0o077, 0)
        self.assertEqual((self.directory / "journal.lock").stat().st_mode & 0o077, 0)
        log = (self.directory / "chunks.jsonl").read_bytes()
        self.assertEqual(len(log.splitlines()), 1)
        self.assertEqual(json.loads(log)["sha256"], DIGEST)
        self.assertNotIn(b"plaintext", log)
        with self.journal() as reopened:
            self.assertEqual(reopened.records, {CHUNK: (1024, DIGEST)})

    def test_conflicting_facts_refuse_without_appending(self):
        with self.journal() as journal:
            journal.record(CHUNK, 1024, DIGEST)
            with self.assertRaisesRegex(MigrationError, "conflicts"):
                journal.record(CHUNK, 1025, DIGEST)
        self.assertEqual(len((self.directory / "chunks.jsonl").read_bytes().splitlines()), 1)

    def test_binding_to_another_reservation_or_key_refuses(self):
        with self.journal() as journal:
            journal.record(CHUNK, 1024, DIGEST)
        for changed in (
            {"reservation_id": "66666666-6666-4666-8666-666666666666"},
            {"key_id": "77777777-7777-4777-8777-777777777777"},
        ):
            with self.subTest(changed=changed), self.assertRaisesRegex(
                    MigrationError, "another run"):
                with self.journal(**changed):
                    pass

    def test_second_open_fails_while_first_has_lock(self):
        with self.journal():
            with self.assertRaisesRegex(MigrationError, "busy or unavailable"):
                with self.journal():
                    pass
        with self.journal():
            pass

    def test_directory_replacement_is_refused_before_scratch_cleanup(self):
        moved = self.directory.with_name("moved-journal")
        with self.journal() as journal:
            self.directory.rename(moved)
            self.directory.mkdir(mode=0o700)
            try:
                with self.assertRaisesRegex(MigrationError, "folder changed"):
                    journal.ensure_private_directory()
            finally:
                self.directory.rmdir()
                moved.rename(self.directory)
            journal.ensure_private_directory()

    def test_incomplete_final_line_is_discarded_but_complete_records_survive(self):
        with self.journal() as journal:
            journal.record(CHUNK, 1024, DIGEST)
        with (self.directory / "chunks.jsonl").open("ab") as handle:
            handle.write(b'{"id":"partial"')
            handle.flush()
            os.fsync(handle.fileno())
        with self.journal() as reopened:
            self.assertEqual(reopened.records, {CHUNK: (1024, DIGEST)})
            reopened.record("c" * 64, 2048, "d" * 64)
        self.assertEqual(len((self.directory / "chunks.jsonl").read_bytes().splitlines()), 2)

    def test_complete_malformed_or_conflicting_lines_refuse(self):
        with self.journal() as journal:
            journal.record(CHUNK, 1024, DIGEST)
        log = self.directory / "chunks.jsonl"
        with log.open("ab") as handle:
            handle.write(b"not-json\n")
        with self.assertRaisesRegex(MigrationError, "log is invalid"):
            with self.journal():
                pass
        log.write_bytes(log.read_bytes().splitlines(keepends=True)[0] +
                        json.dumps({"id": CHUNK, "bytes": 1025,
                                    "sha256": DIGEST}).encode() + b"\n")
        with self.assertRaisesRegex(MigrationError, "conflicting ciphertext"):
            with self.journal():
                pass

    def test_exposed_folder_or_file_refuses(self):
        self.directory.chmod(0o755)
        with self.assertRaisesRegex(MigrationError, "folder is not private"):
            with self.journal():
                pass
        self.directory.chmod(0o700)
        with self.journal():
            pass
        (self.directory / "chunks.jsonl").chmod(0o644)
        with self.assertRaisesRegex(MigrationError, "log is unsafe"):
            with self.journal():
                pass

    def test_record_requires_open_journal_and_valid_facts(self):
        journal = self.journal()
        with self.assertRaisesRegex(MigrationError, "not locked"):
            journal.record(CHUNK, 1024, DIGEST)
        with journal:
            for identifier, size, digest in (("bad", 1024, DIGEST),
                                             (CHUNK, True, DIGEST),
                                             (CHUNK, 1024, "bad")):
                with self.assertRaisesRegex(MigrationError, "receipt is invalid"):
                    journal.record(identifier, size, digest)
            self.assertEqual(journal.records, {})

    def test_manifest_binding_is_private_stable_and_recoverable(self):
        with self.journal() as journal:
            journal.bind_manifest("a" * 64, "b" * 64, 123)
            journal.bind_manifest("a" * 64, "b" * 64, 123)
            with self.assertRaisesRegex(MigrationError, "conflicts"):
                journal.bind_manifest("c" * 64, "b" * 64, 123)
        binding = self.directory / "manifest-binding.json"
        self.assertEqual(binding.stat().st_mode & 0o077, 0)
        self.assertEqual(json.loads(binding.read_text())["snapshotId"],
                         IDENTITY["snapshot_id"])
        with self.journal() as reopened:
            self.assertEqual(reopened.manifest_binding["ciphertextSha256"], "b" * 64)
            reopened.bind_manifest("a" * 64, "b" * 64, 123)
            with self.assertRaisesRegex(MigrationError, "conflicts"):
                reopened.bind_manifest("a" * 64, "c" * 64, 123)

    def test_unsafe_or_corrupt_manifest_binding_refuses_open(self):
        with self.journal() as journal:
            journal.bind_manifest("a" * 64, "b" * 64, 123)
        binding = self.directory / "manifest-binding.json"
        binding.chmod(0o644)
        with self.assertRaisesRegex(MigrationError, "unsafe"):
            with self.journal():
                pass
        binding.chmod(0o600)
        binding.write_text("not-json")
        with self.assertRaisesRegex(MigrationError, "invalid"):
            with self.journal():
                pass

    def test_remote_stage_records_only_after_exact_readback(self):
        scratch = self.directory.parent / "scratch"
        item = scratch / CHUNK[:2] / (CHUNK[2:] + ".cvchunk")
        item.parent.mkdir(parents=True, mode=0o700)
        ciphertext = b"synthetic ciphertext"
        item.write_bytes(ciphertext)
        item.chmod(0o600)
        digest = hashlib.sha256(ciphertext).hexdigest()
        prepared = PreparedRemoteFile(
            "e" * 64, len(ciphertext), ({"id": CHUNK, "size": len(ciphertext)},),
            (CHUNK,), {})

        class Store:
            def __init__(self):
                self.data = None
                self.corrupt_readback = False

            def checked_metadata(self, key):
                if self.data is None:
                    return None
                return (len(self.data), "0" * 64 if self.corrupt_readback else
                        hashlib.sha256(self.data).hexdigest())

            def put_if_absent(self, key, source, length):
                self.data = source.read(length)

        class Client:
            def __init__(self, store):
                self.store = store

            def object_store(self, reservation_id, expected, *, apply=False):
                assert reservation_id == IDENTITY["reservation_id"] and apply is True
                assert expected == {"objects/" + CHUNK[:2] + "/" +
                                    CHUNK[2:] + ".cvchunk": (len(ciphertext), digest)}
                return self.store

        store = Store()
        client = Client(store)
        with self.journal() as journal:
            store.corrupt_readback = True
            with self.assertRaisesRegex(MigrationError, "differs"):
                stage_prepared_file(prepared, scratch, client,
                                    IDENTITY["reservation_id"], journal=journal,
                                    apply=True)
            self.assertEqual(journal.records, {})
            store.corrupt_readback = False
            result = stage_prepared_file(prepared, scratch, client,
                                         IDENTITY["reservation_id"], journal=journal,
                                         apply=True)
            self.assertEqual(result[0].sha256, digest)
            self.assertEqual(journal.records, {CHUNK: (len(ciphertext), digest)})
            with self.assertRaisesRegex(MigrationError, "does not match"):
                stage_prepared_file(prepared, scratch, client,
                                    "66666666-6666-4666-8666-666666666666",
                                    journal=journal, apply=True)
        self.assertEqual(item.read_bytes(), ciphertext)


if __name__ == "__main__":
    unittest.main()
