"""Synthetic encrypted Vault snapshot over the local Worker object route.

Run only with the loopback Wrangler fixture from README.md. This deliberately
does not call a hosted publication service or touch the user's Codex home.
"""

import json
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import tempfile
from urllib.request import Request, build_opener
import uuid

from codex_migrate.errors import MigrationError
from codex_migrate.vault_hosted_chunk_journal import HostedChunkJournal
from codex_migrate.vault_hosted_snapshot_stage import stage_hosted_snapshot
from codex_migrate.vault_http_store import CapabilityHttpStore, _NoRedirect
from codex_migrate.vault_recovery import import_recovery_key, restore_snapshot
from codex_migrate.vault_remote_recovery import download_encrypted_snapshot


def prove(origin: str) -> None:
    if origin not in ("http://127.0.0.1:8789", "http://localhost:8789"):
        raise AssertionError("The encrypted probe requires loopback Wrangler")
    opener = build_opener(_NoRedirect())
    # The loopback-only fixture deliberately accepts only this synthetic
    # account/Vault pair; object IDs and every backup run remain random.
    account_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    vault_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    reservation_id, snapshot_id = str(uuid.uuid4()), str(uuid.uuid4())
    expected_objects = {}

    def grant(method: str, scoped_key: str, size: int, digest: str) -> str:
        claim = json.dumps({"method": method, "key": scoped_key,
                            "bytes": size, "sha256": digest},
                           separators=(",", ":")).encode("utf-8")
        request = Request(origin + "/native-grant", data=claim, method="POST",
                          headers={"Content-Type": "application/json",
                                   "Content-Length": str(len(claim))})
        with opener.open(request, timeout=15) as response:
            result = json.loads(response.read(2049))
        if set(result) != {"token"} or not isinstance(result["token"], str):
            raise AssertionError("The loopback grant fixture returned an invalid token")
        return result["token"]

    class Upload:
        def published_chunks(self, identifiers):
            return {}

        def object_store(self, reservation, expected, *, apply=False):
            if reservation != reservation_id or apply is not True:
                raise AssertionError("The synthetic reservation changed")
            for key, fact in expected.items():
                prior = expected_objects.setdefault(key, fact)
                if prior != fact:
                    raise AssertionError("An encrypted object changed during staging")
            return CapabilityHttpStore(origin, account_id, vault_id, expected,
                                       grant, allow_loopback_http=True)

    def remove_objects() -> None:
        # The probe owns these random account/Vault keys. DELETE is exact-fact
        # scoped and idempotent, including after an interrupted stage.
        for key, (size, digest) in expected_objects.items():
            scoped = f"accounts/{account_id}/vaults/{vault_id}/{key}"
            token = grant("DELETE", scoped, size, digest)
            request = Request(origin + "/v1/object/" + scoped, method="DELETE",
                              headers={"Authorization": "Bearer " + token,
                                       "Content-Length": "0"})
            with opener.open(request, timeout=15) as response:
                if response.status != 204:
                    raise AssertionError("Synthetic R2 object cleanup failed")
        if expected_objects:
            store = CapabilityHttpStore(origin, account_id, vault_id,
                                        expected_objects, grant,
                                        allow_loopback_http=True)
            for key in expected_objects:
                if store.checked_metadata(key) is not None:
                    raise AssertionError("A synthetic R2 object remained after cleanup")

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source = root / "source"
        source.mkdir(mode=0o700)
        transcript = source / ".codex/sessions/2026/09/28/thread.jsonl"
        transcript.parent.mkdir(parents=True, mode=0o700)
        transcript.write_text(json.dumps({"payload": {"message": {
            "content": "SYNTHETIC-ENCRYPTED-WORKER-ROUNDTRIP"}}}) + "\n")
        database = source / ".codex/thread_history_1.sqlite"
        item_id = "synthetic-item"
        thread_id = str(uuid.uuid4())
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE thread_items (thread_id TEXT, turn_id TEXT, "
                               "item_id TEXT, rollout_ordinal INTEGER, created_at_ms INTEGER, "
                               "item_json TEXT, item_type TEXT, updated_at_ordinal INTEGER)")
            connection.execute("CREATE TABLE thread_history_projection_state ("
                               "thread_id TEXT, next_rollout_byte_offset INTEGER, "
                               "next_rollout_ordinal INTEGER)")
            connection.execute("INSERT INTO thread_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                               (thread_id, "turn-1", item_id, 1, 100,
                                json.dumps({"id": item_id, "type": "userMessage",
                                            "text": "SYNTHETIC-DATABASE-WORKER-ROUNDTRIP"}),
                                "userMessage", 1))
        helper = root / "CodexVaultCrypto"
        subprocess.run(["xcrun", "swiftc", "-parse-as-library", "-O",
                        "-D", "CODEX_VAULT_TEST_LEGACY_KEYCHAIN",
                        "-target", platform.machine() + "-apple-macos13.0",
                        "desktop/CodexVaultCrypto.swift", "-o", str(helper)],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        key_result = json.loads(subprocess.run(
            [str(helper), "create-key"], check=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE).stdout)
        key_id = key_result["key_id"]
        metadata = {"format": "codex-vault", "version": 1, "key_id": key_id,
                    "created_at": "2026-09-28T00:00:00+00:00"}
        journal_root = root / "journal"
        journal_root.mkdir(mode=0o700)
        try:
            with HostedChunkJournal(
                    journal_root, account_id=account_id, vault_id=vault_id,
                    reservation_id=reservation_id, snapshot_id=snapshot_id,
                    key_id=key_id, base_snapshot_id=None) as journal:
                staged = stage_hosted_snapshot(
                    str(source), metadata, [], journal, Upload(),
                    crypto_helper=str(helper), apply=True)
            receipt = staged.upload_claim().receipt()
            if set(expected_objects) != {item.key for item in staged.objects}:
                raise AssertionError("The Worker did not receive the exact snapshot inventory")
            remote = CapabilityHttpStore(
                origin, account_id, vault_id, expected_objects, grant,
                allow_loopback_http=True)
            subprocess.run([str(helper), "delete-key", "--key-id", key_id],
                           check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            key_id = None
            empty_home = root / "empty-home"
            empty_home.mkdir(mode=0o700)
            recovered = root / "recovered-vault"
            try:
                download_encrypted_snapshot(
                    str(empty_home), str(recovered), remote, receipt,
                    max_bytes=5_000_000, crypto_helper=str(helper))
            except MigrationError:
                pass  # Ciphertext is present, but this login has no Vault key.
            else:
                raise AssertionError("Recovery succeeded without the imported key")
            key_id = import_recovery_key(
                str(recovered), key_result["recovery_key"], crypto_helper=str(helper))
            download_encrypted_snapshot(
                str(empty_home), str(recovered), remote, receipt,
                max_bytes=5_000_000, crypto_helper=str(helper))
            restored = root / "restored"
            restore_snapshot(str(empty_home), str(recovered), str(restored),
                             crypto_helper=str(helper))
            if (restored / "sessions/2026/09/28/thread.jsonl").read_bytes() != transcript.read_bytes():
                raise AssertionError("The encrypted transcript did not restore exactly")
            saved = restored / "paginated_history" / (thread_id + ".jsonl")
            record = json.loads(saved.read_text().strip())
            if json.loads(record["item_json"])["text"] != "SYNTHETIC-DATABASE-WORKER-ROUNDTRIP":
                raise AssertionError("The database-only message did not restore")
            for key in expected_objects:
                with remote.open_read(key) as response:
                    ciphertext = response.read()
                if (b"SYNTHETIC-ENCRYPTED-WORKER-ROUNDTRIP" in ciphertext or
                        b"SYNTHETIC-DATABASE-WORKER-ROUNDTRIP" in ciphertext):
                    raise AssertionError("Plaintext appeared in a remote object")
        finally:
            try:
                remove_objects()
            finally:
                if key_id is not None:
                    subprocess.run([str(helper), "delete-key", "--key-id", key_id],
                                   check=True, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: encrypted_roundtrip.py http://127.0.0.1:8789")
    prove(sys.argv[1])
    print("Synthetic encrypted Worker roundtrip passed")
