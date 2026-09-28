"""A hosted publication claim must cover the manifest's exact ciphertext."""

from copy import deepcopy
import unittest

from codex_migrate.errors import MigrationError
from codex_migrate.vault_hosted_snapshot_assembly import staged_snapshot_objects
from codex_migrate.vault_remote_transfer import StagedObject
from codex_migrate.vault_remote_writer import StagedRemoteFile


SNAPSHOT = "11111111-1111-4111-8111-111111111111"
THREAD = "22222222-2222-4222-8222-222222222222"
A = "a" * 64
B = "b" * 64


def chunk(identifier, size=10):
    return {"id": identifier, "size": size}


def object_for(identifier, digest="c" * 64):
    return StagedObject("objects/" + identifier[:2] + "/" +
                        identifier[2:] + ".cvchunk", 38, digest)


def file_record(path, stage):
    return {
        "collection": "active", "path": path, "size": stage.size,
        "mtime_ns": 1, "sha256": stage.sha256,
        "chunks": list(stage.chunks), "thread_id": THREAD,
        "identity_state": "verified", "titles": ["Synthetic"],
        "records": 1, "assistant_messages": 0, "user_messages": 1,
        "at_risk": False,
    }


class HostedSnapshotAssemblyTests(unittest.TestCase):
    def setUp(self):
        self.metadata = StagedObject("metadata/" + SNAPSHOT + ".json", 100, "1" * 64)
        self.sealed_manifest = StagedObject(
            "manifests/" + SNAPSHOT + ".cvmanifest", 200, "2" * 64)
        self.reference = StagedObject("refs/" + SNAPSHOT + ".json", 90, "3" * 64)
        first = StagedRemoteFile("4" * 64, 20, (chunk(A), chunk(B)),
                                 (object_for(A), object_for(B)))
        second = StagedRemoteFile("5" * 64, 10, (chunk(A),), (object_for(A),))
        self.stages = {("active", "first.jsonl"): first,
                       ("active", "second.jsonl"): second}
        self.manifest = {
            "format": "codex-vault-snapshot", "version": 2,
            "snapshot_id": SNAPSHOT, "created_at": "2026-09-28T00:00:00Z",
            "files": [file_record("first.jsonl", first),
                      file_record("second.jsonl", second)],
        }

    def assemble(self, manifest=None, stages=None, **changes):
        return staged_snapshot_objects(
            SNAPSHOT, self.manifest if manifest is None else manifest,
            self.stages if stages is None else stages,
            changes.get("metadata", self.metadata),
            changes.get("sealed_manifest", self.sealed_manifest),
            changes.get("reference", self.reference))

    def test_shared_chunk_is_listed_once_with_metadata_and_reference(self):
        self.assertEqual(self.assemble(),
                         (self.metadata, object_for(A), object_for(B),
                          self.sealed_manifest, self.reference))

    def test_missing_extra_or_conflicting_chunk_is_refused(self):
        for objects, reason in (
            ((object_for(A),), "missing or extra"),
            ((object_for(A), object_for(B), object_for("d" * 64)), "missing or extra"),
            ((object_for(A), object_for(B, "e" * 64)), "conflicting"),
        ):
            stages = dict(self.stages)
            first = stages[("active", "first.jsonl")]
            if reason == "conflicting":
                second = stages[("active", "second.jsonl")]
                stages[("active", "second.jsonl")] = StagedRemoteFile(
                    second.sha256, second.size, second.chunks,
                    (object_for(A, "e" * 64),))
            else:
                stages[("active", "first.jsonl")] = StagedRemoteFile(
                    first.sha256, first.size, first.chunks, objects)
            with self.subTest(reason=reason), self.assertRaisesRegex(MigrationError, reason):
                self.assemble(stages=stages)

    def test_manifest_content_and_identity_must_match_stage(self):
        for change, reason in (
            (lambda m: m["files"][0].update(sha256="6" * 64), "does not match"),
            (lambda m: m["files"][0].update(size=21), "does not match"),
            (lambda m: m["files"][0].update(chunks=[chunk(A)]), "does not match"),
            (lambda m: m["files"][0].update(identity_state="verified", thread_id=None),
             "identity metadata"),
            (lambda m: m["files"][0].update(path="../escape"), "unsafe transcript path"),
        ):
            manifest = deepcopy(self.manifest)
            change(manifest)
            with self.subTest(reason=reason), self.assertRaisesRegex(MigrationError, reason):
                self.assemble(manifest=manifest)

    def test_duplicate_path_or_unstated_file_is_refused(self):
        manifest = deepcopy(self.manifest)
        manifest["files"][1]["path"] = "first.jsonl"
        with self.assertRaisesRegex(MigrationError, "duplicate transcript path"):
            self.assemble(manifest=manifest)
        stages = dict(self.stages)
        stages[("archived", "extra.jsonl")] = self.stages[("active", "second.jsonl")]
        with self.assertRaisesRegex(MigrationError, "unstated staged transcripts"):
            self.assemble(stages=stages)

    def test_wrong_tail_key_or_missing_plaintext_chunk_is_refused(self):
        with self.assertRaisesRegex(MigrationError, "invalid verified facts"):
            self.assemble(metadata=StagedObject("metadata/other.json", 100, "1" * 64))
        stages = dict(self.stages)
        first = stages[("active", "first.jsonl")]
        stages[("active", "first.jsonl")] = StagedRemoteFile(
            first.sha256, first.size, (chunk(A, 5), chunk(B, 5)), first.objects)
        manifest = deepcopy(self.manifest)
        manifest["files"][0]["chunks"] = [chunk(A, 5), chunk(B, 5)]
        with self.assertRaisesRegex(MigrationError, "missing plaintext chunks"):
            self.assemble(manifest=manifest, stages=stages)

    def test_shared_id_cannot_claim_two_plaintext_sizes(self):
        stages = dict(self.stages)
        second = stages[("active", "second.jsonl")]
        stages[("active", "second.jsonl")] = StagedRemoteFile(
            second.sha256, 11, (chunk(A, 11),), second.objects)
        manifest = deepcopy(self.manifest)
        manifest["files"][1].update(size=11, chunks=[chunk(A, 11)])
        with self.assertRaisesRegex(MigrationError, "conflicting plaintext metadata"):
            self.assemble(manifest=manifest, stages=stages)

    def test_paginated_history_requires_v3_and_exact_verified_thread_identity(self):
        stage = StagedRemoteFile("5" * 64, 10, (chunk(A),), (object_for(A),))
        entry = file_record(THREAD + ".jsonl", stage)
        entry.update(collection="paginated", mtime_ns=0)
        manifest = {**self.manifest, "version": 3, "files": [entry]}
        stages = {("paginated", THREAD + ".jsonl"): stage}
        self.assertEqual(self.assemble(manifest=manifest, stages=stages),
                         (self.metadata, object_for(A),
                          self.sealed_manifest, self.reference))
        for change in (
            lambda m: m.update(version=2),
            lambda m: m["files"][0].update(path="renamed.jsonl"),
            lambda m: m["files"][0].update(identity_state="unverified"),
            lambda m: m["files"][0].update(mtime_ns=1),
            lambda m: m["files"][0].update(records=0),
        ):
            invalid = deepcopy(manifest)
            change(invalid)
            with self.subTest(invalid=invalid), self.assertRaisesRegex(
                    MigrationError, "invalid paginated history"):
                self.assemble(manifest=invalid, stages=stages)


if __name__ == "__main__":
    unittest.main()
