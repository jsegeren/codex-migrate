import hashlib
import io
import json
import os
from pathlib import Path
import platform
import sqlite3
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from codex_migrate.errors import MigrationError
from codex_migrate import vault_backup
from codex_migrate.vault_attachments import read_pasted_text
from codex_migrate.vault_hosted_chunk_journal import HostedChunkJournal
from codex_migrate.vault_hosted_live_run import HostedLiveBackupRun
from codex_migrate.vault_hosted_manifest import stage_hosted_manifest
from codex_migrate.vault_hosted_recovery_client import HostedRecoveryClient
from codex_migrate.vault_hosted_snapshot_tail import stage_hosted_snapshot_tail
from codex_migrate.vault_hosted_snapshot_stage import stage_hosted_snapshot
from codex_migrate.vault_hosted_source_index import promote_source_facts
from codex_migrate.vault_hosted_upload_client import HostedUploadClient
from codex_migrate.vault import markdown_chunks, markdown_source_stamp, read_thread_page, search
from codex_migrate.vault_backup import backup, plan
from codex_migrate.vault_identity import TranscriptChanged
from codex_migrate.vault_install import plan_install
from codex_migrate.vault_paginated import restored_items
from codex_migrate.vault_recovery import (
    export_recovery_key, import_recovery_key, list_snapshots, restore_snapshot,
    snapshot_catalog, vault_storage_usage, verify_snapshot,
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


class BackupHelperDiagnosticTests(unittest.TestCase):
    def test_exact_keychain_approval_error_is_actionable(self):
        failure = SimpleNamespace(returncode=70, stdout=b"", stderr=(
            b"Codex Vault crypto: Vault could not access its key without interactive "
            b"Keychain approval. No backup was published. Contact support if this persists\n"))
        with patch.object(vault_backup.subprocess, "run", return_value=failure):
            with self.assertRaisesRegex(MigrationError, "interactive Keychain approval"):
                vault_backup._run_helper(Path("/synthetic/helper"), ["create-key"])

    def test_unrecognized_helper_error_never_reveals_stderr(self):
        failure = SimpleNamespace(returncode=70, stdout=b"", stderr=(
            b"Codex Vault crypto: private synthetic content CV1-DO-NOT-PRINT\n"))
        with patch.object(vault_backup.subprocess, "run", return_value=failure):
            with self.assertRaises(MigrationError) as caught:
                vault_backup._run_helper(Path("/synthetic/helper"), ["create-key"])
        self.assertEqual(str(caught.exception),
                         "Authenticated backup failed; no new snapshot was published.")


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

    def test_pasted_prompt_attachment_is_encrypted_and_restored(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "vault"
            self.fixture(source)
            attachment_id = str(uuid.uuid4())
            attachments = source / ".codex/attachments"
            prompt = attachments / attachment_id / "pasted-text.txt"
            prompt.parent.mkdir(parents=True)
            prompt.write_text("PRIVATE-ATTACHMENT-ONLY-PROMPT", encoding="utf-8")
            active = source / ".codex/sessions/2026/09/17/active.jsonl"
            with active.open("a", encoding="utf-8") as output:
                output.write(json.dumps({
                    "type": "response_item", "payload": {
                        "role": "user", "content": [{"type": "input_text", "text":
                            "# Files mentioned by the user:\n\n"
                            "## Pasted text.txt: /Users/old/.codex/attachments/" +
                            attachment_id + "/pasted-text.txt\n\n"
                            "## My request for Codex:\n"}]}}) + "\n")
            registry = attachments / "pasted-text-attachments.json"
            registry.write_text(json.dumps({"attachmentPaths": [str(prompt)]}),
                                encoding="utf-8")
            planned = plan(str(source), str(destination))
            self.assertEqual(planned.transcript_files, 2)
            self.assertEqual(planned.attachment_files, 2)
            result = None
            try:
                result = backup(str(source), str(destination),
                                crypto_helper=str(self.helper))
                self.assertEqual(result.transcript_files, 2)
                self.assertEqual(result.attachment_files, 2)
                catalog = snapshot_catalog(str(destination), crypto_helper=str(self.helper))
                self.assertEqual([item["path"] for item in catalog
                                  if item["collection"] == "attachments"],
                                 [attachment_id + "/pasted-text.txt",
                                  "pasted-text-attachments.json"])
                self.assertEqual(verify_snapshot(str(destination),
                                 crypto_helper=str(self.helper)).transcript_files, 4)
                ciphertext = b"".join(path.read_bytes() for path in
                                      (destination / "objects").rglob("*.cvchunk"))
                self.assertNotIn(b"PRIVATE-ATTACHMENT-ONLY-PROMPT", ciphertext)
                self.assertEqual(search(str(source), "PRIVATE-ATTACHMENT-ONLY-PROMPT")[0].collection,
                                 "active")
                browse = root / "browse"
                browse.mkdir()
                restored = browse / ".codex"
                restore_snapshot(str(source), str(destination), str(restored),
                                 crypto_helper=str(self.helper))
                self.assertEqual((restored / "attachments" / attachment_id /
                                  "pasted-text.txt").read_bytes(), prompt.read_bytes())
                self.assertEqual((restored / "attachments" /
                                  "pasted-text-attachments.json").read_bytes(),
                                 registry.read_bytes())
                matches = search(str(browse), "PRIVATE-ATTACHMENT-ONLY-PROMPT",
                                 catalog=catalog)
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0].collection, "active")
                exported = b"".join(markdown_chunks(
                    str(browse), "active", "2026/09/17/active.jsonl"))
                self.assertIn(b"PRIVATE-ATTACHMENT-ONLY-PROMPT", exported)
                with self.assertRaisesRegex(MigrationError, "cannot be installed"):
                    plan_install(str(source), str(destination),
                                 crypto_helper=str(self.helper))
                prompt.unlink()
                incomplete = backup(str(source), str(destination),
                                    crypto_helper=str(self.helper))
                self.assertTrue(incomplete.needs_attention)
                self.assertEqual(incomplete.at_risk_threads, 1)
                current_catalog = snapshot_catalog(str(destination),
                                                   crypto_helper=str(self.helper))
                self.assertTrue(next(item for item in current_catalog
                                     if item["collection"] == "active")["at_risk"])
                self.assertEqual((restored / "attachments" / attachment_id /
                                  "pasted-text.txt").read_text(encoding="utf-8"),
                                 "PRIVATE-ATTACHMENT-ONLY-PROMPT")
            finally:
                if result is not None:
                    self.delete_key(destination)

    def test_linked_attachment_is_not_silently_omitted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            self.fixture(source)
            attachments = source / ".codex/attachments"
            attachments.mkdir()
            outside = root / "outside.txt"
            outside.write_text("PRIVATE-OUTSIDE-FILE", encoding="utf-8")
            (attachments / "pasted-text.txt").symlink_to(outside)
            with self.assertRaisesRegex(MigrationError, "attachment file needs review"):
                plan(str(source), str(root / "vault"))

    def test_pasted_prompt_browse_refuses_linked_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            attachments = source / ".codex/attachments"
            attachments.mkdir(parents=True)
            attachment_id = str(uuid.uuid4())
            outside = root / "outside"
            outside.mkdir()
            (outside / "pasted-text.txt").write_text("outside", encoding="utf-8")
            (attachments / attachment_id).symlink_to(outside)
            with self.assertRaisesRegex(MigrationError, "opened or read safely"):
                read_pasted_text(str(source), attachment_id)

    def test_new_attachment_during_backup_does_not_publish_incomplete_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "vault"
            self.fixture(source)
            original = vault_backup._run_helper
            added = False

            def add_during_encryption(helper, arguments, **kwargs):
                nonlocal added
                result = original(helper, arguments, **kwargs)
                if arguments[0] == "store-chunks" and not added:
                    added = True
                    attachment = (source / ".codex/attachments" / str(uuid.uuid4()) /
                                  "pasted-text.txt")
                    attachment.parent.mkdir(parents=True)
                    attachment.write_text("NEW-UNPROTECTED-PROMPT", encoding="utf-8")
                return result

            try:
                with patch.object(vault_backup, "_run_helper",
                                  side_effect=add_during_encryption):
                    with self.assertRaisesRegex(MigrationError, "changed during backup"):
                        backup(str(source), str(destination),
                               crypto_helper=str(self.helper))
                self.assertFalse((destination / "latest.json").exists())
            finally:
                self.delete_key(destination)

    def test_hosted_snapshot_includes_attachment_only_prompt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            self.fixture(source)
            attachment_id = str(uuid.uuid4())
            prompt = (source / ".codex/attachments" / attachment_id /
                      "pasted-text.txt")
            prompt.parent.mkdir(parents=True)
            prompt.write_text("PRIVATE-HOSTED-ATTACHMENT-PROMPT", encoding="utf-8")
            active = source / ".codex/sessions/2026/09/17/active.jsonl"
            with active.open("a", encoding="utf-8") as output:
                output.write(json.dumps({"type": "response_item", "payload": {
                    "role": "user", "content": [{"type": "input_text", "text":
                        "/Users/old/.codex/attachments/" + attachment_id +
                        "/pasted-text.txt"}]}}) + "\n")
            key = json.loads(subprocess.run(
                [str(self.helper), "create-key"], check=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout)
            key_id = key["key_id"]
            snapshot_id = str(uuid.uuid4())
            directory = root / "journal"
            directory.mkdir(mode=0o700)
            identity = {"account_id": str(uuid.uuid4()),
                        "vault_id": str(uuid.uuid4()),
                        "reservation_id": str(uuid.uuid4()),
                        "snapshot_id": snapshot_id, "key_id": key_id}
            metadata = {"format": "codex-vault", "version": 1,
                        "key_id": key_id,
                        "created_at": "2026-09-29T00:00:00+00:00"}

            class Client:
                def __init__(self):
                    self.store = MemoryObjectStore()

                def published_chunks(self, ids):
                    return {}

                def object_store(self, reservation_id, expected, *, apply=False):
                    if reservation_id != identity["reservation_id"] or apply is not True:
                        raise AssertionError("wrong hosted reservation")
                    return self.store

            client = Client()
            try:
                with HostedChunkJournal(directory, **identity) as journal:
                    staged = stage_hosted_snapshot(
                        str(source), metadata, [], journal, client,
                        crypto_helper=str(self.helper), apply=True)
                self.assertEqual(staged.transcript_files, 3)
                self.assertNotIn(b"PRIVATE-HOSTED-ATTACHMENT-PROMPT",
                                 b"".join(client.store.objects.values()))
                subprocess.run([str(self.helper), "delete-key", "--key-id", key_id],
                               check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                key_id = None
                recovered = root / "recovered-vault"
                home = root / "recovery-home"
                home.mkdir(mode=0o700)
                with self.assertRaises(MigrationError):
                    vault_remote_recovery.download_encrypted_snapshot(
                        str(home), str(recovered), client.store,
                        staged.upload_claim().receipt(), max_bytes=5_000_000,
                        crypto_helper=str(self.helper))
                key_id = import_recovery_key(str(recovered), key["recovery_key"],
                                             crypto_helper=str(self.helper))
                vault_remote_recovery.download_encrypted_snapshot(
                    str(home), str(recovered), client.store,
                    staged.upload_claim().receipt(), max_bytes=5_000_000,
                    crypto_helper=str(self.helper))
                catalog = snapshot_catalog(str(recovered), crypto_helper=str(self.helper))
                self.assertEqual([item["path"] for item in catalog
                                  if item["collection"] == "attachments"],
                                 [attachment_id + "/pasted-text.txt"])
                browse_home = root / "browse-home"
                browse_home.mkdir()
                output = browse_home / ".codex"
                restore_snapshot(str(home), str(recovered), str(output),
                                 crypto_helper=str(self.helper))
                self.assertEqual((output / "attachments" / attachment_id /
                                  "pasted-text.txt").read_bytes(), prompt.read_bytes())
                self.assertEqual(len(search(str(browse_home),
                                            "PRIVATE-HOSTED-ATTACHMENT-PROMPT",
                                            catalog=catalog)), 1)
                prompt.unlink()
                second_id = str(uuid.uuid4())
                identity["reservation_id"] = str(uuid.uuid4())
                identity["snapshot_id"] = second_id
                second_directory = root / "second-journal"
                second_directory.mkdir(mode=0o700)
                second_client = Client()
                with HostedChunkJournal(second_directory, **identity,
                                        base_snapshot_id=snapshot_id) as journal:
                    incomplete = stage_hosted_snapshot(
                        str(source), metadata, catalog, journal, second_client,
                        crypto_helper=str(self.helper), apply=True)
                self.assertEqual(incomplete.at_risk_threads, 1)
            finally:
                if key_id is not None:
                    subprocess.run([str(self.helper), "delete-key", "--key-id", key_id],
                                   check=True, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)

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

    def test_hosted_whole_snapshot_stages_and_recovers_without_full_local_vault(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir(mode=0o700)
            self.fixture(source)
            active_bytes = (source / ".codex/sessions/2026/09/17/active.jsonl").read_bytes()
            archived_bytes = (source / ".codex/archived_sessions/archived.jsonl").read_bytes()
            created = subprocess.run(
                [str(self.helper), "create-key"], check=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            key_result = json.loads(created.stdout)
            key_id = key_result["key_id"]
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

                # The hosted-only stage must be restorable without ever
                # creating a full ciphertext Vault on the source Mac.
                remote = MemoryObjectStore()
                remote.objects = dict(client.store.objects)
                empty_home = root / "empty-home"
                empty_home.mkdir(mode=0o700)
                recovered = root / "recovered-vault"
                self.assertFalse((root / "vault").exists())
                subprocess.run([str(self.helper), "delete-key", "--key-id", key_id],
                               check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                key_id = None
                with self.assertRaises(MigrationError):
                    vault_remote_recovery.download_encrypted_snapshot(
                        str(empty_home), str(recovered), remote,
                        first.upload_claim().receipt(), max_bytes=5_000_000,
                        crypto_helper=str(self.helper))
                key_id = import_recovery_key(
                    str(recovered), key_result["recovery_key"],
                    crypto_helper=str(self.helper))
                result = vault_remote_recovery.download_encrypted_snapshot(
                    str(empty_home), str(recovered), remote,
                    first.upload_claim().receipt(), max_bytes=5_000_000,
                    crypto_helper=str(self.helper))
                self.assertEqual(result.transcript_files, 2)
                restored = root / "restored"
                restore_snapshot(str(empty_home), str(recovered), str(restored),
                                 crypto_helper=str(self.helper))
                self.assertEqual((restored / "sessions/2026/09/17/active.jsonl").read_bytes(),
                                 active_bytes)
                self.assertEqual((restored / "archived_sessions/archived.jsonl").read_bytes(),
                                 archived_bytes)
            finally:
                if key_id is not None:
                    subprocess.run([str(self.helper), "delete-key", "--key-id", key_id],
                                   check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def test_published_index_reuses_unchanged_transcripts_but_reads_changed_ones(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir(mode=0o700)
            self.fixture(source)
            runs = root / "runs"
            runs.mkdir(mode=0o700)
            created = subprocess.run([str(self.helper), "create-key"], check=True,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            key_id = json.loads(created.stdout)["key_id"]
            metadata = {"format": "codex-vault", "version": 1,
                        "key_id": key_id,
                        "created_at": "2026-09-27T00:00:00+00:00"}
            account_id, vault_id = str(uuid.uuid4()), str(uuid.uuid4())

            class Client:
                def __init__(self):
                    self.store = MetadataObjectStore()

                def published_chunks(self, ids):
                    result = {}
                    for identifier in ids:
                        key = "objects/" + identifier[:2] + "/" + identifier[2:] + ".cvchunk"
                        data = self.store.objects.get(key)
                        if data is not None:
                            result[identifier] = (len(data), hashlib.sha256(data).hexdigest())
                    return result

                def object_store(self, reservation_id, expected, *, apply=False):
                    self_outer.assertTrue(apply)
                    return self.store

            self_outer = self
            client = Client()

            def snapshot(base, prior):
                snapshot_id = str(uuid.uuid4())
                reservation_id = str(uuid.uuid4())
                journal_dir = runs / ("snapshot-" + snapshot_id)
                journal_dir.mkdir(mode=0o700)
                with HostedChunkJournal(
                        journal_dir, account_id=account_id, vault_id=vault_id,
                        reservation_id=reservation_id, snapshot_id=snapshot_id,
                        key_id=key_id, base_snapshot_id=base) as journal:
                    staged = stage_hosted_snapshot(
                        str(source), metadata, prior, journal, client,
                        crypto_helper=str(self.helper), chunk_size=64 * 1024,
                        window_bytes=64 * 1024, apply=True)
                sealed = runs / (snapshot_id + ".cvmanifest")
                sealed.write_bytes(client.store.objects[
                    "manifests/" + snapshot_id + ".cvmanifest"])
                catalog = vault_backup._run_helper(self.helper, [
                    "staging-catalog", "--key-id", key_id,
                    "--snapshot-id", snapshot_id, "--manifest", str(sealed)])
                promote_source_facts(runs, {
                    "accountId": account_id, "vaultId": vault_id,
                    "keyId": key_id, "snapshotId": snapshot_id})
                return staged, catalog["files"], snapshot_id

            try:
                first, prior, base = snapshot(None, [])
                writes = client.store.writes
                with patch.object(vault_hosted_snapshot_stage, "scan_transcript",
                                  side_effect=AssertionError("unchanged transcript was read")), \
                     patch.object(vault_hosted_snapshot_stage,
                                  "stage_remote_aware_file_windowed",
                                  side_effect=AssertionError("unchanged transcript was staged")):
                    second, prior, base = snapshot(base, prior)
                self.assertEqual(second.transcript_files, first.transcript_files)
                self.assertEqual(second.transcript_bytes, first.transcript_bytes)
                self.assertEqual(client.store.writes - writes, 3)

                changed = source / ".codex/sessions/2026/09/17/active.jsonl"
                with changed.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({"type": "response_item",
                                             "payload": {"role": "user"}}) + "\n")
                original = vault_hosted_snapshot_stage.stage_remote_aware_file_windowed
                reread = []

                def track(path, *args, **kwargs):
                    reread.append(path)
                    return original(path, *args, **kwargs)

                with patch.object(vault_hosted_snapshot_stage,
                                  "stage_remote_aware_file_windowed", side_effect=track):
                    third, _, _ = snapshot(base, prior)
                self.assertEqual(reread, [changed])
                self.assertGreater(third.transcript_bytes, second.transcript_bytes)
            finally:
                subprocess.run([str(self.helper), "delete-key", "--key-id", key_id],
                               check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def test_hosted_snapshot_encrypts_paginated_items_without_plaintext_staging(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            codex = source / ".codex"
            codex.mkdir(parents=True)
            database = codex / "thread_history_1.sqlite"
            thread_id = "44444444-4444-4444-8444-444444444444"
            item = {"id": "item-1", "type": "userMessage",
                    "text": "SYNTHETIC-HOSTED-DATABASE-TURN-" + "X" * 130000}
            missing_attachment_id = str(uuid.uuid4())
            later_item = {"id": "item-2", "type": "userMessage",
                          "text": ("SYNTHETIC-HOSTED-SECOND-TURN "
                                   "/Users/old/.codex/attachments/" +
                                   missing_attachment_id + "/pasted-text.txt")}
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE thread_items (thread_id TEXT, turn_id TEXT, "
                                   "item_id TEXT, rollout_ordinal INTEGER, created_at_ms INTEGER, "
                                   "item_json TEXT, item_type TEXT, updated_at_ordinal INTEGER)")
                connection.execute("CREATE TABLE thread_history_projection_state ("
                                   "thread_id TEXT, next_rollout_byte_offset INTEGER, "
                                   "next_rollout_ordinal INTEGER)")
                connection.execute("INSERT INTO thread_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                   (thread_id, "turn-1", "item-1", 1, 100,
                                    json.dumps(item), "userMessage", 1))
                connection.execute("INSERT INTO thread_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                   (thread_id, "turn-2", "item-2", 2, 200,
                                    json.dumps(later_item), "userMessage", 2))
            original = database.read_bytes()
            key_result = json.loads(subprocess.run(
                [str(self.helper), "create-key"], check=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout)
            key_id = key_result["key_id"]
            snapshot_id = str(uuid.uuid4())
            metadata = {"format": "codex-vault", "version": 1,
                        "key_id": key_id,
                        "created_at": "2026-09-28T00:00:00+00:00"}
            directory = root / ("snapshot-" + snapshot_id)
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
                    result = {}
                    for identifier in ids:
                        key = ("objects/" + identifier[:2] + "/" +
                               identifier[2:] + ".cvchunk")
                        stored = self.store.objects.get(key)
                        if stored is not None:
                            result[identifier] = (len(stored), hashlib.sha256(stored).hexdigest())
                    return result

                def object_store(self, reservation_id, expected, *, apply=False):
                    if reservation_id != identity["reservation_id"] or apply is not True:
                        raise AssertionError("wrong hosted reservation")
                    return self.store

            client = Client()
            try:
                with HostedChunkJournal(directory, **identity) as journal:
                    staged = stage_hosted_snapshot(
                        str(source), metadata, [], journal, client,
                        crypto_helper=str(self.helper), chunk_size=64 * 1024,
                        window_bytes=64 * 1024, apply=True)
                    self.assertEqual(staged.transcript_files, 1)
                    self.assertEqual(staged.at_risk_threads, 1)
                    self.assertEqual(database.read_bytes(), original)
                    self.assertFalse(list((directory / "scratch").rglob("*.cvchunk")))
                    ciphertext = b"".join(client.store.objects.values())
                    self.assertNotIn(b"SYNTHETIC-HOSTED-DATABASE-TURN", ciphertext)
                    journal_bytes = b"".join(path.read_bytes() for path in
                                             directory.rglob("*") if path.is_file())
                    self.assertNotIn(b"SYNTHETIC-HOSTED-DATABASE-TURN", journal_bytes)
                    self.assertGreater(staged.transcript_bytes, 130000)
                    writes = client.store.writes
                    retried = stage_hosted_snapshot(
                        str(source), metadata, [], journal, client,
                        crypto_helper=str(self.helper), chunk_size=64 * 1024,
                        window_bytes=64 * 1024, apply=True)
                    self.assertEqual(retried, staged)
                    self.assertEqual(client.store.writes, writes)
                remote = MemoryObjectStore()
                remote.objects = dict(client.store.objects)
                empty_home = root / "empty-home"
                empty_home.mkdir(mode=0o700)
                recovered = root / "recovered-vault"
                vault_remote_recovery.download_encrypted_snapshot(
                    str(empty_home), str(recovered), remote,
                    staged.upload_claim().receipt(), max_bytes=5_000_000,
                    crypto_helper=str(self.helper))
                (root / "browse").mkdir()
                restored = root / "browse/.codex"
                restore_snapshot(str(empty_home), str(recovered), str(restored),
                                 crypto_helper=str(self.helper))
                lines = (restored / "paginated_history" /
                         (thread_id + ".jsonl")).read_text().splitlines()
                self.assertEqual(len(lines), 2)
                self.assertEqual(json.loads(json.loads(lines[0])["item_json"]), item)
                self.assertEqual(json.loads(json.loads(lines[1])["item_json"]), later_item)
                catalog = snapshot_catalog(str(recovered), crypto_helper=str(self.helper))
                self.assertTrue(catalog[0]["at_risk"])
                found = search(str(root / "browse"), "SYNTHETIC-HOSTED-DATABASE-TURN",
                               catalog=catalog)
                self.assertEqual([(match.collection, match.transcript) for match in found],
                                 [("paginated", thread_id + ".jsonl")])
                sealed = root / "prior.cvmanifest"
                sealed.write_bytes(client.store.objects[
                    "manifests/" + snapshot_id + ".cvmanifest"])
                staging_catalog = vault_backup._run_helper(self.helper, [
                    "staging-catalog", "--key-id", key_id,
                    "--snapshot-id", snapshot_id, "--manifest", str(sealed)])["files"]
                self.assertIsNotNone(json.loads(
                    (directory / "source-index-candidate.json").read_text())["paginated"])
                promote_source_facts(root, {
                    "accountId": identity["account_id"], "vaultId": identity["vault_id"],
                    "keyId": key_id, "snapshotId": snapshot_id})
                identity = {**identity, "reservation_id": str(uuid.uuid4()),
                            "snapshot_id": str(uuid.uuid4())}
                reuse_directory = root / ("snapshot-" + identity["snapshot_id"])
                reuse_directory.mkdir(mode=0o700)
                with HostedChunkJournal(reuse_directory, **identity,
                                        base_snapshot_id=snapshot_id) as journal:
                    _, previous_db = vault_hosted_snapshot_stage.published_source_facts(
                        journal, crypto_helper=str(self.helper), include_paginated=True)
                    self.assertEqual(previous_db,
                                     vault_hosted_snapshot_stage.source_fingerprint(str(source)))
                    self.assertIsNotNone(
                        vault_hosted_snapshot_stage._reusable_paginated(staging_catalog, 1))
                    with patch.object(vault_hosted_snapshot_stage,
                                      "stage_remote_aware_records",
                                      side_effect=AssertionError("unchanged database reread")):
                        unchanged = stage_hosted_snapshot(
                            str(source), metadata, staging_catalog, journal, client,
                            crypto_helper=str(self.helper), chunk_size=64 * 1024,
                            window_bytes=64 * 1024, apply=True)
                    self.assertEqual(unchanged.transcript_files, 1)
                    self.assertEqual(unchanged.transcript_bytes, staged.transcript_bytes)
                identity = {**identity, "reservation_id": str(uuid.uuid4()),
                            "snapshot_id": str(uuid.uuid4())}
                race_directory = root / ("snapshot-" + identity["snapshot_id"])
                race_directory.mkdir(mode=0o700)
                published_objects = vault_hosted_snapshot_stage._published_objects

                def append_during_reuse(remote_client, ids):
                    result = published_objects(remote_client, ids)
                    with sqlite3.connect(database) as connection:
                        connection.execute("INSERT INTO thread_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                           (thread_id, "turn-3", "item-3", 3, 300,
                                            json.dumps({"id": "item-3", "type": "userMessage"}),
                                            "userMessage", 3))
                    return result

                with HostedChunkJournal(race_directory, **identity,
                                        base_snapshot_id=snapshot_id) as journal:
                    with patch.object(vault_hosted_snapshot_stage, "_published_objects",
                                      side_effect=append_during_reuse):
                        with self.assertRaisesRegex(MigrationError,
                                                    "paginated history changed"):
                            stage_hosted_snapshot(
                                str(source), metadata, staging_catalog, journal,
                                client, crypto_helper=str(self.helper),
                                chunk_size=64 * 1024, window_bytes=64 * 1024,
                                apply=True)
                with sqlite3.connect(database) as connection:
                    connection.execute("DELETE FROM thread_items WHERE item_id IN ('item-2', 'item-3')")
                identity = {**identity, "reservation_id": str(uuid.uuid4()),
                            "snapshot_id": str(uuid.uuid4())}
                next_directory = root / "next-journal"
                next_directory.mkdir(mode=0o700)
                with HostedChunkJournal(next_directory, **identity,
                                        base_snapshot_id=snapshot_id) as journal:
                    smaller = stage_hosted_snapshot(
                        str(source), metadata, staging_catalog, journal, client,
                        crypto_helper=str(self.helper), chunk_size=64 * 1024,
                        window_bytes=64 * 1024, apply=True)
                    self.assertEqual(smaller.at_risk_threads, 1)
                database.unlink()
                identity = {**identity, "reservation_id": str(uuid.uuid4()),
                            "snapshot_id": str(uuid.uuid4())}
                missing_directory = root / "missing-db-journal"
                missing_directory.mkdir(mode=0o700)
                with HostedChunkJournal(missing_directory, **identity,
                                        base_snapshot_id=snapshot_id) as journal:
                    missing = stage_hosted_snapshot(
                        str(source), metadata, staging_catalog, journal, client,
                        crypto_helper=str(self.helper), chunk_size=64 * 1024,
                        window_bytes=64 * 1024, apply=True)
                    self.assertEqual(missing.at_risk_threads, 1)
                    self.assertEqual(missing.transcript_files, 0)
            finally:
                subprocess.run([str(self.helper), "delete-key", "--key-id", key_id],
                               check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def test_hosted_staging_refuses_unsafe_paginated_sidecar_before_upload(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir(mode=0o700)
            self.fixture(source)
            database = source / ".codex/thread_history_1.sqlite"
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE thread_items (thread_id TEXT, turn_id TEXT, "
                                   "item_id TEXT, rollout_ordinal INTEGER, created_at_ms INTEGER, "
                                   "item_json TEXT, item_type TEXT, updated_at_ordinal INTEGER)")
                connection.execute("CREATE TABLE thread_history_projection_state ("
                                   "thread_id TEXT, next_rollout_byte_offset INTEGER, "
                                   "next_rollout_ordinal INTEGER)")
            outside = root / "outside-sidecar"
            outside.write_bytes(b"unrelated private data")
            Path(str(database) + "-shm").symlink_to(outside)
            directory = root / "journal"
            directory.mkdir(mode=0o700)
            key_id = str(uuid.uuid4())
            metadata = {"format": "codex-vault", "version": 1,
                        "key_id": key_id, "created_at": "2026-09-28T00:00:00+00:00"}
            with HostedChunkJournal(
                    directory, account_id=str(uuid.uuid4()),
                    vault_id=str(uuid.uuid4()), reservation_id=str(uuid.uuid4()),
                    snapshot_id=str(uuid.uuid4()), key_id=key_id) as journal, patch.object(
                    vault_hosted_snapshot_stage, "stage_remote_aware_file_windowed") as upload:
                with self.assertRaises(MigrationError):
                    stage_hosted_snapshot(str(source), metadata, [], journal,
                                          object(), crypto_helper=str(self.helper),
                                          apply=True)
                upload.assert_not_called()
            self.assertEqual(outside.read_bytes(), b"unrelated private data")

    def test_hosted_live_runner_stages_publishes_and_restores_synthetic_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir(mode=0o700)
            self.fixture(source)
            active = (source / ".codex/sessions/2026/09/17/active.jsonl").read_bytes()
            archived = (source / ".codex/archived_sessions/archived.jsonl").read_bytes()
            database = source / ".codex/thread_history_1.sqlite"
            paginated_id = "44444444-4444-4444-8444-444444444444"
            paginated_item = {"id": "item-1", "type": "userMessage",
                              "text": "SYNTHETIC-LIVE-RUN-DATABASE-TURN"}
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE thread_items (thread_id TEXT, turn_id TEXT, "
                                   "item_id TEXT, rollout_ordinal INTEGER, created_at_ms INTEGER, "
                                   "item_json TEXT, item_type TEXT, updated_at_ordinal INTEGER)")
                connection.execute("CREATE TABLE thread_history_projection_state ("
                                   "thread_id TEXT, next_rollout_byte_offset INTEGER, "
                                   "next_rollout_ordinal INTEGER)")
                connection.execute("INSERT INTO thread_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                   (paginated_id, "turn-1", "item-1", 1, 100,
                                    json.dumps(paginated_item), "userMessage", 1))
            key_result = json.loads(subprocess.run(
                [str(self.helper), "create-key"], check=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout)
            key_id = key_result["key_id"]
            account_id, vault_id = str(uuid.uuid4()), str(uuid.uuid4())
            origin = "http://127.0.0.1:49111"
            token = "hv1_" + "a" * 43

            class Upload(HostedUploadClient):
                def __init__(self):
                    super().__init__(origin, "http://127.0.0.1:49112", token,
                                     account_id, vault_id, allow_loopback_http=True)
                    self.store = MetadataObjectStore()
                    self.staged = None
                    self.published_id = None
                    self.published_objects = {}

                def reserve_with_base(self, *, reservation_id=None, apply=False):
                    assert apply is True and reservation_id is not None
                    return reservation_id, self.published_id

                def published_chunks(self, ids):
                    if self.published_id is None:
                        return {}
                    facts = {}
                    for identifier in ids:
                        key = ("objects/" + identifier[:2] + "/" +
                               identifier[2:] + ".cvchunk")
                        value = self.published_objects.get(key)
                        if value is not None:
                            facts[identifier] = (len(value), hashlib.sha256(value).hexdigest())
                    return facts

                def object_store(self, reservation_id, expected, *, apply=False):
                    assert apply is True and reservation_id is not None
                    return self.store

                def publish_hosted_stage(self, reservation_id, staged, *, apply=False):
                    assert apply is True and reservation_id == staged.reservation_id
                    for item in staged.objects:
                        data = self.store.objects[item.key]
                        assert len(data) == item.bytes
                        assert hashlib.sha256(data).hexdigest() == item.sha256
                    self.staged = staged
                    self.published_id = staged.snapshot_id
                    self.published_objects = {
                        item.key: self.store.objects[item.key] for item in staged.objects
                    }
                    return {"snapshotId": staged.snapshot_id,
                            "verifiedObjectCount": len(staged.objects)}

            class Recovery(HostedRecoveryClient):
                def __init__(self):
                    super().__init__(origin, token, vault_id, allow_loopback_http=True)
                    self.base_id = None

                def latest_snapshot(self, *, expected_account_id):
                    assert expected_account_id == account_id
                    return (None if self.base_id is None else
                            {"snapshotId": self.base_id, "totalObjects": 6,
                             "totalBytes": 100})

                def prior_catalog(self, *, key_id, crypto_helper, max_bytes,
                                  expected_snapshot_id, expected_account_id,
                                  include_chunks=False):
                    assert expected_snapshot_id == self.base_id
                    assert expected_account_id == account_id
                    if not include_chunks and self.base_id is not None:
                        with tempfile.TemporaryDirectory() as temporary_manifest:
                            manifest = Path(temporary_manifest) / "prior.cvmanifest"
                            manifest.write_bytes(upload.store.objects[
                                f"manifests/{self.base_id}.cvmanifest"])
                            result = subprocess.run([
                                crypto_helper, "catalog", "--key-id", key_id,
                                "--snapshot-id", self.base_id,
                                "--manifest", str(manifest),
                            ], check=True, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
                            return self.base_id, json.loads(result.stdout)["files"]
                    return self.base_id, []

            upload = Upload()
            recovery = Recovery()
            metadata = {"format": "codex-vault", "version": 1,
                        "key_id": key_id,
                        "created_at": "2026-09-27T00:00:00+00:00"}
            try:
                runner = HostedLiveBackupRun(upload, recovery, str(source))
                published = runner.back_up_live_history(
                    metadata, crypto_helper=str(self.helper),
                    max_prior_bytes=5_000_000, apply=True)
                self.assertIsNone(runner.pending())
                self.assertEqual(published["verifiedObjectCount"], 6)
                self.assertEqual(upload.staged.snapshot_id,
                                 published["snapshotId"])
                self.assertFalse((root / "vault").exists())
                combined = b"".join(upload.store.objects.values())
                self.assertNotIn(b"PRIVATE-ACTIVE-CONTENT", combined)
                self.assertNotIn(b"PRIVATE-ARCHIVED-CONTENT", combined)
                self.assertNotIn(b"NEVER-COPY-AUTH", combined)
                self.assertNotIn(b"SYNTHETIC-LIVE-RUN-DATABASE-TURN", combined)

                # A later snapshot pins the prior published base, reuses the
                # unchanged archived chunk, and never overwrites ciphertext.
                recovery.base_id = published["snapshotId"]
                prior_writes = upload.store.writes
                checked = runner.back_up_live_history(
                    metadata, crypto_helper=str(self.helper),
                    max_prior_bytes=5_000_000, apply=True)
                self.assertEqual(checked, {
                    "unchanged": True, "lastGoodSnapshotId": published["snapshotId"],
                    "lastGoodObjectCount": 6, "atRiskThreads": 0})
                self.assertEqual(upload.store.writes, prior_writes)
                self.assertEqual(upload.published_id, published["snapshotId"])
                self.assertIsNone(runner.pending())
                active_path = source / ".codex/sessions/2026/09/17/active.jsonl"
                with active_path.open("ab") as handle:
                    handle.write(b'{"type":"response_item","payload":{"role":"user",'
                                 b'"content":"NEW-SYNTHETIC-CONTENT"}}\n')
                active = active_path.read_bytes()
                second = runner.back_up_live_history(
                    metadata, crypto_helper=str(self.helper),
                    max_prior_bytes=5_000_000, apply=True)
                self.assertNotEqual(second["snapshotId"], published["snapshotId"])
                self.assertEqual(upload.store.writes, 10)
                self.assertIsNone(runner.pending())

                # Opt-in local scale probe: exercise the real hosted-only
                # staging path across many files and several 64 MiB windows.
                # This uses synthetic data and an in-memory object store; it
                # is not a real-R2 or clean-account recovery receipt.
                scale_digest = None
                if os.environ.get("CODEX_MIGRATE_HOSTED_SCALE_PROBE") == "1":
                    scale_files = int(os.environ.get(
                        "CODEX_MIGRATE_HOSTED_SCALE_FILES", "2048"))
                    if not 1 <= scale_files <= 25_000:
                        raise ValueError("Hosted scale file count must be 1–25,000")
                    bulk = source / ".codex/sessions/2026/09/17/scale"
                    bulk.mkdir(mode=0o700)
                    for index in range(scale_files):
                        (bulk / f"thread-{index:04d}.jsonl").write_bytes(
                            json.dumps({"thread": index, "text": f"synthetic-{index:04d}"})
                            .encode("utf-8") + b"\n")
                    long_path = bulk / "long-thread.jsonl"
                    scale_digest = hashlib.sha256()
                    with long_path.open("wb") as stream:
                        for index in range(1152):
                            line = (b'{"payload":{"message":{"content":"' +
                                    f"{index:04d}".encode("ascii") + b"x" * 65536 +
                                    b'"}}}\n')
                            stream.write(line)
                            scale_digest.update(line)
                    before_writes = upload.store.writes
                    recovery.base_id = second["snapshotId"]
                    third = runner.back_up_live_history(
                        metadata, crypto_helper=str(self.helper),
                        max_prior_bytes=5_000_000, apply=True)
                    self.assertEqual(third["snapshotId"], upload.staged.snapshot_id)
                    self.assertEqual(upload.staged.transcript_files, scale_files + 4)
                    self.assertGreaterEqual(upload.store.writes - before_writes,
                                            scale_files + 3)
                    self.assertIsNone(runner.pending())
                    self.assertFalse((root / "vault").exists())

                remote = MemoryObjectStore()
                remote.objects = dict(upload.store.objects)
                recovered = root / "recovered-vault"
                empty_home = root / "empty-home"
                empty_home.mkdir(mode=0o700)
                subprocess.run([str(self.helper), "delete-key", "--key-id", key_id],
                               check=True, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
                key_id = None
                recovery_limit = 256_000_000 if scale_digest is not None else 5_000_000
                with self.assertRaises(MigrationError):
                    vault_remote_recovery.download_encrypted_snapshot(
                        str(empty_home), str(recovered), remote,
                        upload.staged.upload_claim().receipt(),
                        max_bytes=recovery_limit, crypto_helper=str(self.helper))
                key_id = import_recovery_key(
                    str(recovered), key_result["recovery_key"],
                    crypto_helper=str(self.helper))
                vault_remote_recovery.download_encrypted_snapshot(
                    str(empty_home), str(recovered), remote,
                    upload.staged.upload_claim().receipt(),
                    max_bytes=recovery_limit, crypto_helper=str(self.helper))
                restored = root / "restored"
                restore_snapshot(str(empty_home), str(recovered), str(restored),
                                 crypto_helper=str(self.helper))
                self.assertEqual((restored / "sessions/2026/09/17/active.jsonl").read_bytes(),
                                 active)
                self.assertEqual((restored / "archived_sessions/archived.jsonl").read_bytes(),
                                 archived)
                paginated_lines = (restored / "paginated_history" /
                                   (paginated_id + ".jsonl")).read_text().splitlines()
                self.assertEqual(len(paginated_lines), 1)
                self.assertEqual(json.loads(json.loads(paginated_lines[0])["item_json"]),
                                 paginated_item)
                if scale_digest is not None:
                    self.assertEqual(len(list((restored / "sessions/2026/09/17/scale")
                                              .glob("thread-*.jsonl"))), scale_files)
                    self.assertEqual(hashlib.sha256(
                        (restored / "sessions/2026/09/17/scale/long-thread.jsonl")
                        .read_bytes()).hexdigest(), scale_digest.hexdigest())
            finally:
                if key_id is not None:
                    subprocess.run([str(self.helper), "delete-key", "--key-id", key_id],
                                   check=True, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)

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
                    store.objects[key] = original[:-1] + bytes([original[-1] ^ 1])
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

    def test_paginated_items_are_encrypted_separately_and_recoverable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "vault"
            codex = source / ".codex"
            codex.mkdir(parents=True)
            database = codex / "thread_history_1.sqlite"
            thread_id = "44444444-4444-4444-8444-444444444444"
            item = {"id": "item-1", "type": "userMessage",
                    "content": [{"type": "text", "text": "SYNTHETIC-DATABASE-ONLY-TURN"}]}
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE thread_items (thread_id TEXT, turn_id TEXT, "
                                   "item_id TEXT, rollout_ordinal INTEGER, created_at_ms INTEGER, "
                                   "item_json TEXT, item_type TEXT, updated_at_ordinal INTEGER)")
                connection.execute("CREATE TABLE thread_history_projection_state ("
                                   "thread_id TEXT, next_rollout_byte_offset INTEGER, "
                                   "next_rollout_ordinal INTEGER)")
                connection.execute("INSERT INTO thread_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                   (thread_id, "turn-1", "item-1", 1, 100,
                                    json.dumps(item), "userMessage", 1))
            original = database.read_bytes()
            planned = plan(str(source), str(destination))
            self.assertEqual(planned.transcript_files, 0)
            self.assertEqual(planned.paginated_threads, 1)
            self.assertGreaterEqual(planned.paginated_database_bytes, len(original))
            progress_states = []
            try:
                first = backup(str(source), str(destination), crypto_helper=str(self.helper),
                               chunk_size=64 * 1024, progress=lambda *values: progress_states.append(values))
                self.assertEqual(progress_states[0], (0, 1, 0, 0))
                self.assertEqual(progress_states[-1][0:2], (1, 1))
                self.assertEqual(progress_states[-1][3], 0)
                self.assertTrue(first.paginated_history_unprotected)
                self.assertTrue(first.needs_attention)
                self.assertEqual(first.transcript_files, 1)
                self.assertEqual(database.read_bytes(), original)
                catalog = snapshot_catalog(str(destination), crypto_helper=str(self.helper))
                self.assertEqual([(file["collection"], file["thread_id"])
                                  for file in catalog], [("paginated", thread_id)])
                encrypted = b"".join(path.read_bytes() for path in
                                     destination.rglob("*") if path.is_file())
                self.assertNotIn(b"SYNTHETIC-DATABASE-ONLY-TURN", encrypted)
                (root / "browse").mkdir()
                restored = root / "browse/.codex"
                restore_snapshot(str(source), str(destination), str(restored),
                                 crypto_helper=str(self.helper))
                rows = (restored / "paginated_history" /
                        (thread_id + ".jsonl")).read_text().splitlines()
                self.assertEqual(len(rows), 1)
                self.assertEqual(json.loads(json.loads(rows[0])["item_json"]), item)
                self.assertEqual(json.loads(next(restored_items(
                    str(root / "browse"), thread_id)).item_json), item)
                found = search(str(root / "browse"), "SYNTHETIC-DATABASE-ONLY-TURN",
                               catalog=catalog)
                self.assertEqual([(match.collection, match.transcript, match.cursor)
                                  for match in found], [("paginated", thread_id + ".jsonl", 0)])
                titled_catalog = [{**catalog[0], "titles": ["An older synthetic title"]}]
                by_title = search(str(root / "browse"), "older synthetic",
                                  catalog=titled_catalog)
                self.assertEqual([(match.collection, match.line) for match in by_title],
                                 [("paginated", 0)])
                page, next_cursor = read_thread_page(
                    str(root / "browse"), "paginated", thread_id + ".jsonl",
                    expected_query="SYNTHETIC-DATABASE-ONLY-TURN")
                self.assertIsNone(next_cursor)
                self.assertEqual([(entry.role, entry.text) for entry in page.entries],
                                 [("User", "SYNTHETIC-DATABASE-ONLY-TURN")])
                exported = b"".join(markdown_chunks(
                    str(root / "browse"), "paginated", thread_id + ".jsonl"))
                self.assertIn(b"SYNTHETIC-DATABASE-ONLY-TURN", exported)
                self.assertIn(b"saved paginated source", exported)
                with self.assertRaisesRegex(MigrationError, "whole-history install is refused"):
                    plan_install(str(source), str(destination), crypto_helper=str(self.helper))
                second = backup(str(source), str(destination), crypto_helper=str(self.helper),
                                chunk_size=64 * 1024)
                self.assertTrue(second.needs_attention)
                self.assertEqual(len(list((destination / "objects").rglob("*.cvchunk"))), 1)
                with sqlite3.connect(database) as connection:
                    connection.execute("INSERT INTO thread_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                       (thread_id, "turn-2", "item-2", 2, 101,
                                        json.dumps({"id": "item-2", "type": "agentMessage",
                                                    "text": "SYNTHETIC-APPENDED-ANSWER"}),
                                        "agentMessage", 2))
                appended = backup(str(source), str(destination), crypto_helper=str(self.helper),
                                  chunk_size=64 * 1024)
                appended_catalog = snapshot_catalog(str(destination),
                                                    crypto_helper=str(self.helper))
                self.assertFalse(appended_catalog[0]["at_risk"])
                self.assertGreater(len(list((destination / "objects").rglob("*.cvchunk"))), 1)
                with sqlite3.connect(database) as connection:
                    connection.execute("DELETE FROM thread_items WHERE item_id='item-2'")
                shortened = backup(str(source), str(destination), crypto_helper=str(self.helper),
                                   chunk_size=64 * 1024)
                self.assertTrue(shortened.needs_attention)
                self.assertEqual(shortened.at_risk_threads, 1)
                shortened_catalog = snapshot_catalog(str(destination),
                                                     crypto_helper=str(self.helper))
                self.assertTrue(shortened_catalog[0]["at_risk"])
                old_catalog = snapshot_catalog(str(destination), snapshot=appended.snapshot_id,
                                               crypto_helper=str(self.helper))
                self.assertEqual(old_catalog[0]["assistant_messages"], 1)
                older_home = root / "before-shrink"
                older_home.mkdir()
                restore_snapshot(str(source), str(destination), str(older_home / ".codex"),
                                 snapshot=appended.snapshot_id, crypto_helper=str(self.helper))
                older_items = list(restored_items(str(older_home), thread_id))
                self.assertEqual(len(older_items), 2)
                self.assertEqual(json.loads(older_items[1].item_json)["text"],
                                 "SYNTHETIC-APPENDED-ANSWER")
                repeated = backup(str(source), str(destination), crypto_helper=str(self.helper),
                                  chunk_size=64 * 1024)
                self.assertEqual(repeated.at_risk_threads, 1)
                repeated_catalog = snapshot_catalog(str(destination),
                                                    crypto_helper=str(self.helper))
                self.assertTrue(repeated_catalog[0]["at_risk"])
                with sqlite3.connect(database) as connection:
                    connection.execute("UPDATE thread_items SET item_json='not JSON'")
                with self.assertRaises(MigrationError):
                    backup(str(source), str(destination), crypto_helper=str(self.helper),
                           chunk_size=64 * 1024)
                self.assertEqual(json.loads((destination / "latest.json").read_text())
                                 ["snapshot_id"], repeated.snapshot_id)
                database.unlink()
                missing = backup(str(source), str(destination), crypto_helper=str(self.helper),
                                 chunk_size=64 * 1024)
                self.assertTrue(missing.needs_attention)
                self.assertEqual(missing.at_risk_threads, 1)
                self.assertEqual(missing.transcript_files, 0)
                self.assertEqual(snapshot_catalog(str(destination),
                    snapshot=repeated.snapshot_id, crypto_helper=str(self.helper))[0]
                    ["thread_id"], thread_id)
            finally:
                self.delete_key(destination)

    def test_paginated_reference_to_missing_pasted_text_is_at_risk(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "vault"
            codex = source / ".codex"
            codex.mkdir(parents=True)
            database = codex / "thread_history_1.sqlite"
            thread_id = str(uuid.uuid4())
            attachment_id = str(uuid.uuid4())
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE thread_items (thread_id TEXT, turn_id TEXT, "
                                   "item_id TEXT, rollout_ordinal INTEGER, created_at_ms INTEGER, "
                                   "item_json TEXT, item_type TEXT, updated_at_ordinal INTEGER)")
                connection.execute("CREATE TABLE thread_history_projection_state ("
                                   "thread_id TEXT, next_rollout_byte_offset INTEGER, "
                                   "next_rollout_ordinal INTEGER)")
                connection.execute("INSERT INTO thread_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                   (thread_id, "turn-1", "item-1", 1, 100,
                                    json.dumps({"id": "item-1", "type": "userMessage",
                                                "text": ("/Users/old/.codex/attachments/" +
                                                         attachment_id + "/pasted-text.txt")}),
                                    "userMessage", 1))
            try:
                result = backup(str(source), str(destination),
                                crypto_helper=str(self.helper))
                self.assertTrue(result.needs_attention)
                self.assertEqual(result.at_risk_threads, 1)
                catalog = snapshot_catalog(str(destination), crypto_helper=str(self.helper))
                self.assertTrue(catalog[0]["at_risk"])
            finally:
                self.delete_key(destination)

    def test_paginated_shrink_does_not_mark_same_id_rollout_at_risk(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "vault"
            codex = source / ".codex"
            thread_id = "44444444-4444-4444-8444-444444444444"
            transcript = codex / "sessions" / ("rollout-" + thread_id + ".jsonl")
            transcript.parent.mkdir(parents=True)
            transcript.write_text(json.dumps({"type": "session_meta", "payload": {
                "id": thread_id,
            }}) + "\n", encoding="utf-8")
            database = codex / "thread_history_1.sqlite"
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE thread_items (thread_id TEXT, turn_id TEXT, "
                                   "item_id TEXT, rollout_ordinal INTEGER, created_at_ms INTEGER, "
                                   "item_json TEXT, item_type TEXT, updated_at_ordinal INTEGER)")
                connection.execute("CREATE TABLE thread_history_projection_state ("
                                   "thread_id TEXT, next_rollout_byte_offset INTEGER, "
                                   "next_rollout_ordinal INTEGER)")
                for ordinal, item_type in ((1, "userMessage"), (2, "agentMessage")):
                    item_id = "item-" + str(ordinal)
                    connection.execute("INSERT INTO thread_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                       (thread_id, "turn-" + item_id, item_id, ordinal,
                                        100 + ordinal,
                                        json.dumps({"id": item_id, "type": item_type,
                                                    "text": "synthetic " + item_type}),
                                        item_type, ordinal))
            try:
                backup(str(source), str(destination), crypto_helper=str(self.helper))
                with sqlite3.connect(database) as connection:
                    connection.execute("DELETE FROM thread_items WHERE item_id='item-2'")
                result = backup(str(source), str(destination), crypto_helper=str(self.helper))
                catalog = snapshot_catalog(str(destination), crypto_helper=str(self.helper))
                by_collection = {item["collection"]: item for item in catalog}
                self.assertEqual(set(by_collection), {"active", "paginated"})
                self.assertFalse(by_collection["active"]["at_risk"])
                self.assertTrue(by_collection["paginated"]["at_risk"])
                self.assertEqual(result.at_risk_threads, 1)
            finally:
                self.delete_key(destination)

    def test_restored_fork_search_preserves_inherited_prefix(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "vault"
            parent_id = "11111111-1111-4111-8111-111111111111"
            child_id = "22222222-2222-4222-8222-222222222222"
            parent = (source / ".codex/archived_sessions" /
                      ("rollout-" + parent_id + ".jsonl"))
            child = (source / ".codex/sessions/2026/09/28" /
                     ("rollout-" + child_id + ".jsonl"))
            child_transcript = "2026/09/28/" + child.name
            parent.parent.mkdir(parents=True)
            child.parent.mkdir(parents=True)

            def record(ordinal, kind, payload):
                return json.dumps({"ordinal": ordinal, "type": kind,
                                   "payload": payload}) + "\n"

            inherited = (record(0, "session_meta", {"id": parent_id})
                         + record(1, "response_item", {"text": "Inherited Clerk plan"}))
            parent.write_text(inherited + record(
                2, "response_item", {"text": "Parent-only later plan"}), encoding="utf-8")
            child.write_text(record(2, "session_meta", {"id": child_id, "history_base": {
                "thread_id": parent_id, "end_ordinal_exclusive": 2,
                "end_byte_offset": len(inherited.encode("utf-8")),
            }}) + record(3, "response_item", {"text": "Child-local implementation"}),
                encoding="utf-8")

            try:
                result = backup(str(source), str(destination), crypto_helper=str(self.helper))
                self.assertEqual(result.transcript_files, 2)
                restored_home = root / "restored"
                restored = restored_home / ".codex"
                restored_home.mkdir()
                restore_snapshot(str(source), str(destination), str(restored),
                                 crypto_helper=str(self.helper))
                matches = search(str(restored_home), "Inherited Clerk plan")
                self.assertEqual({(match.collection, match.transcript) for match in matches},
                                 {("active", child_transcript), ("archived", parent.name)})
                later = search(str(restored_home), "Parent-only later plan")
                self.assertEqual({(match.collection, match.transcript) for match in later},
                                 {("archived", parent.name)})
                child_match = next(match for match in matches if match.collection == "active")
                page, _ = read_thread_page(str(restored_home), "active", child_transcript,
                                           child_match.cursor, expected_query="Inherited Clerk")
                self.assertEqual(page.entries[0].text, "Inherited Clerk plan")
            finally:
                self.delete_key(destination)

    def test_restored_fork_search_includes_bounded_database_only_parent_items(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "vault"
            codex = source / ".codex"
            archived = codex / "archived_sessions"
            active = codex / "sessions"
            archived.mkdir(parents=True)
            active.mkdir()
            parent_id = "11111111-1111-4111-8111-111111111111"
            child_id = "22222222-2222-4222-8222-222222222222"
            grandchild_id = "33333333-3333-4333-8333-333333333333"

            def record(ordinal, kind, payload):
                return json.dumps({"ordinal": ordinal, "type": kind,
                                   "payload": payload}) + "\n"

            parent_prefix = (record(0, "session_meta", {"id": parent_id})
                             + record(1, "event_msg", {"event": "metadata"}))
            (archived / ("rollout-" + parent_id + ".jsonl")).write_text(
                parent_prefix + record(2, "event_msg", {"event": "later metadata"}))
            child_rollout = (
                record(2, "session_meta", {"id": child_id, "history_base": {
                    "thread_id": parent_id, "end_ordinal_exclusive": 2,
                    "end_byte_offset": len(parent_prefix.encode()),
                }}) + record(3, "event_msg", {"event": "child metadata"}))
            (active / ("rollout-" + child_id + ".jsonl")).write_text(child_rollout)
            (active / ("rollout-" + grandchild_id + ".jsonl")).write_text(
                record(4, "session_meta", {"id": grandchild_id, "history_base": {
                    "thread_id": child_id, "end_ordinal_exclusive": 4,
                    "end_byte_offset": len(child_rollout.encode()),
                }}) + record(5, "event_msg", {"event": "grandchild metadata"}))
            database = codex / "thread_history_1.sqlite"
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE thread_items (thread_id TEXT, turn_id TEXT, "
                                   "item_id TEXT, rollout_ordinal INTEGER, created_at_ms INTEGER, "
                                   "item_json TEXT, item_type TEXT, updated_at_ordinal INTEGER)")
                connection.execute("CREATE TABLE thread_history_projection_state ("
                                   "thread_id TEXT, next_rollout_byte_offset INTEGER, "
                                   "next_rollout_ordinal INTEGER)")
                for thread_id, ordinal, item_id, text in (
                        (parent_id, 1, "item-parent", "Inherited database-only plan"),
                        (parent_id, 2, "item-later", "Parent-only database plan"),
                        (child_id, 3, "item-child", "Child-local database plan"),
                        (grandchild_id, 5, "item-grandchild", "Grandchild database plan")):
                    connection.execute(
                        "INSERT INTO thread_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (thread_id, "turn-" + item_id, item_id, ordinal, 100 + ordinal,
                         json.dumps({"id": item_id, "type": "userMessage", "text": text}),
                         "userMessage", ordinal))
            try:
                backup(str(source), str(destination), crypto_helper=str(self.helper))
                restored_home = root / "restored"
                restored_home.mkdir()
                restore_snapshot(str(source), str(destination),
                                 str(restored_home / ".codex"),
                                 crypto_helper=str(self.helper))
                catalog = snapshot_catalog(str(destination), crypto_helper=str(self.helper))
                inherited = search(str(restored_home), "Inherited database-only plan",
                                   catalog=catalog)
                self.assertEqual({match.transcript for match in inherited
                                  if match.collection == "paginated"},
                                 {parent_id + ".jsonl", child_id + ".jsonl",
                                  grandchild_id + ".jsonl"})
                later = search(str(restored_home), "Parent-only database plan",
                               catalog=catalog)
                self.assertEqual({match.transcript for match in later
                                  if match.collection == "paginated"},
                                 {parent_id + ".jsonl"})
                page, _ = read_thread_page(
                    str(restored_home), "paginated", child_id + ".jsonl")
                self.assertEqual([entry.text for entry in page.entries],
                                 ["Inherited database-only plan", "Child-local database plan"])
                grandchild_page, _ = read_thread_page(
                    str(restored_home), "paginated", grandchild_id + ".jsonl")
                self.assertEqual([entry.text for entry in grandchild_page.entries],
                                 ["Inherited database-only plan", "Child-local database plan",
                                  "Grandchild database plan"])
                before = markdown_source_stamp(
                    str(restored_home), "paginated", child_id + ".jsonl")
                parent_items = (restored_home / ".codex/paginated_history" /
                                (parent_id + ".jsonl"))
                parent_items.write_bytes(parent_items.read_bytes() + b"\n")
                self.assertNotEqual(
                    markdown_source_stamp(str(restored_home), "paginated",
                                          child_id + ".jsonl"), before)
            finally:
                self.delete_key(destination)

    def test_restored_fork_skips_ancestor_with_no_database_rows(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "vault"
            codex = source / ".codex"
            parent_id = "11111111-1111-4111-8111-111111111111"
            child_id = "22222222-2222-4222-8222-222222222222"
            parent = codex / "archived_sessions" / ("rollout-" + parent_id + ".jsonl")
            child = codex / "sessions" / ("rollout-" + child_id + ".jsonl")
            parent.parent.mkdir(parents=True)
            child.parent.mkdir()

            def record(ordinal, kind, payload):
                return json.dumps({"ordinal": ordinal, "type": kind,
                                   "payload": payload}) + "\n"

            parent_prefix = (record(0, "session_meta", {"id": parent_id})
                             + record(1, "event_msg", {"event": "parent metadata"}))
            parent.write_text(parent_prefix, encoding="utf-8")
            child.write_text(record(2, "session_meta", {"id": child_id, "history_base": {
                "thread_id": parent_id, "end_ordinal_exclusive": 2,
                "end_byte_offset": len(parent_prefix.encode("utf-8")),
            }}) + record(3, "event_msg", {"event": "child metadata"}), encoding="utf-8")
            database = codex / "thread_history_1.sqlite"
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE thread_items (thread_id TEXT, turn_id TEXT, "
                                   "item_id TEXT, rollout_ordinal INTEGER, created_at_ms INTEGER, "
                                   "item_json TEXT, item_type TEXT, updated_at_ordinal INTEGER)")
                connection.execute("CREATE TABLE thread_history_projection_state ("
                                   "thread_id TEXT, next_rollout_byte_offset INTEGER, "
                                   "next_rollout_ordinal INTEGER)")
                connection.execute(
                    "INSERT INTO thread_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (child_id, "turn-child", "item-child", 3, 103,
                     json.dumps({"id": "item-child", "type": "userMessage",
                                 "text": "Child-only database message"}), "userMessage", 3))
            try:
                backup(str(source), str(destination), crypto_helper=str(self.helper))
                restored_home = root / "restored"
                restored_home.mkdir()
                restore_snapshot(str(source), str(destination),
                                 str(restored_home / ".codex"),
                                 crypto_helper=str(self.helper))
                catalog = snapshot_catalog(str(destination), crypto_helper=str(self.helper))
                self.assertEqual([item["path"] for item in catalog
                                  if item["collection"] == "paginated"],
                                 [child_id + ".jsonl"])
                saved_parent = (restored_home / ".codex/paginated_history" /
                                (parent_id + ".jsonl"))
                self.assertFalse(saved_parent.exists())
                child_name = child_id + ".jsonl"
                matches = search(str(restored_home), "Child-only database message",
                                 catalog=catalog)
                self.assertEqual([(match.collection, match.transcript)
                                  for match in matches if match.collection == "paginated"],
                                 [("paginated", child_name)])
                page, _ = read_thread_page(str(restored_home), "paginated", child_name,
                                           catalog=catalog)
                self.assertEqual([entry.text for entry in page.entries],
                                 ["Child-only database message"])
                exported = b"".join(markdown_chunks(
                    str(restored_home), "paginated", child_name, catalog=catalog))
                self.assertIn(b"Child-only database message", exported)
                markdown_source_stamp(str(restored_home), "paginated", child_name,
                                      catalog=catalog)
                with self.assertRaisesRegex(MigrationError, "not in the selected backup"):
                    read_thread_page(str(restored_home), "paginated",
                                     parent_id + ".jsonl", catalog=catalog)

                # A catalog-listed projection missing on disk is corruption, not a
                # harmless zero-row ancestor. It must never be skipped.
                (restored_home / ".codex/paginated_history" / child_name).unlink()
                with self.assertRaises(MigrationError):
                    read_thread_page(str(restored_home), "paginated", child_name,
                                     catalog=catalog)
                with self.assertRaises(MigrationError):
                    markdown_source_stamp(str(restored_home), "paginated", child_name,
                                          catalog=catalog)
            finally:
                self.delete_key(destination)

    def test_progress_counts_both_transcript_and_database_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            codex = source / ".codex"
            transcript = codex / "sessions/fixture.jsonl"
            transcript.parent.mkdir(parents=True)
            transcript.write_text(json.dumps({"payload": {"text": "synthetic transcript"}}) + "\n")
            database = codex / "thread_history_1.sqlite"
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE thread_items (thread_id TEXT, turn_id TEXT, "
                                   "item_id TEXT, rollout_ordinal INTEGER, created_at_ms INTEGER, "
                                   "item_json TEXT, item_type TEXT, updated_at_ordinal INTEGER)")
                connection.execute("CREATE TABLE thread_history_projection_state ("
                                   "thread_id TEXT, next_rollout_byte_offset INTEGER, "
                                   "next_rollout_ordinal INTEGER)")
                connection.execute("INSERT INTO thread_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                   ("44444444-4444-4444-8444-444444444444", "turn-1",
                                    "item-1", 1, 100,
                                    json.dumps({"id": "item-1", "type": "userMessage",
                                                "text": "synthetic database turn"}),
                                    "userMessage", 1))
            destination = root / "vault"
            updates = []
            try:
                result = backup(str(source), str(destination), crypto_helper=str(self.helper),
                                progress=lambda *values: updates.append(values))
                self.assertEqual(result.transcript_files, 2)
                self.assertEqual(updates[0], (0, 2, 0, 0))
                self.assertTrue(any(done == 1 and total == 2 for done, total, _, _ in updates))
                self.assertEqual(updates[-1][:2], (2, 2))
                self.assertEqual(updates[-1][3], 0)
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
