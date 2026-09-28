"""Opt-in synthetic paginated-history backup benchmark; never reads user data.

Run from the repository root with PYTHONPATH=src. All Codex state and Vault
objects live under a temporary directory and are removed after the run.
"""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import sqlite3
import subprocess
import tempfile
import time

from codex_migrate.vault_backup import backup
from codex_migrate.vault_recovery import verify_snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threads", type=int, default=100)
    parser.add_argument("--items-per-thread", type=int, default=100)
    parser.add_argument("--text-bytes", type=int, default=200)
    parser.add_argument("--second-snapshot", action="store_true")
    parser.add_argument("--append-one", action="store_true",
                        help="append one synthetic item before the second snapshot")
    parser.add_argument("--varied-text", action="store_true",
                        help="generate distinct deterministic payloads per item")
    args = parser.parse_args()
    if platform.system() != "Darwin":
        parser.error("the CryptoKit helper requires macOS")
    if args.append_one and not args.second_snapshot:
        parser.error("--append-one requires --second-snapshot")
    if not (1 <= args.threads <= 2000 and 1 <= args.items_per_thread <= 1000
            and 1 <= args.text_bytes <= 8192
            and args.threads * args.items_per_thread * args.text_bytes <= 2_000_000_000):
        parser.error("benchmark sizes are outside the bounded synthetic range")
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="codex-vault-paginated-scale-") as temporary:
        root = Path(temporary)
        source = root / "source"
        codex = source / ".codex"
        codex.mkdir(parents=True)
        database = codex / "thread_history_1.sqlite"
        shared_text = "S" * args.text_bytes
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE thread_items (thread_id TEXT, turn_id TEXT, "
                               "item_id TEXT, rollout_ordinal INTEGER, created_at_ms INTEGER, "
                               "item_json TEXT, item_type TEXT, updated_at_ordinal INTEGER)")
            connection.execute("CREATE INDEX thread_items_thread_ordinal "
                               "ON thread_items(thread_id, rollout_ordinal)")
            connection.execute("CREATE TABLE thread_history_projection_state ("
                               "thread_id TEXT, next_rollout_byte_offset INTEGER, "
                               "next_rollout_ordinal INTEGER)")
            def rows():
                for thread_number in range(args.threads):
                    thread_id = "00000000-0000-4000-8000-%012d" % thread_number
                    for ordinal in range(args.items_per_thread):
                        item_id = "item-%d-%d" % (thread_number, ordinal)
                        text = (hashlib.shake_256(item_id.encode()).hexdigest(
                            (args.text_bytes + 1) // 2)[:args.text_bytes]
                            if args.varied_text else shared_text)
                        body = json.dumps({"id": item_id, "type": "userMessage",
                                           "content": [{"type": "text", "text": text}]})
                        yield (thread_id, "turn-%d" % ordinal, item_id, ordinal,
                               ordinal, body, "userMessage", ordinal)
            connection.executemany("INSERT INTO thread_items VALUES (?,?,?,?,?,?,?,?)", rows())
        populated = time.monotonic()
        helper = root / "CodexVaultCrypto"
        subprocess.run(["xcrun", "swiftc", "-parse-as-library", "-O", "-D",
                        "CODEX_VAULT_TEST_LEGACY_KEYCHAIN", "-target",
                        platform.machine() + "-apple-macos13.0",
                        "desktop/CodexVaultCrypto.swift", "-o", str(helper)],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        compiled = time.monotonic()
        vault = root / "vault"
        try:
            result = backup(str(source), str(vault), crypto_helper=str(helper))
            backed_up = time.monotonic()
            verified = verify_snapshot(str(vault), snapshot=result.snapshot_id,
                                       crypto_helper=str(helper))
            if verified.transcript_files != args.threads:
                raise AssertionError("verified file count differs from synthetic source")
            if result.paginated_history_unprotected is not True:
                raise AssertionError("draft history coverage warning was not retained")
            first_objects = {path.relative_to(vault).as_posix() for path in
                             (vault / "objects").rglob("*.cvchunk")}
            first_vault_bytes = sum(path.stat().st_size for path in
                                    vault.rglob("*") if path.is_file())
            metrics = {
                "threads": args.threads,
                "items": args.threads * args.items_per_thread,
                "database_bytes": database.stat().st_size,
                "vault_bytes": first_vault_bytes,
                "seconds_populate": round(populated - started, 2),
                "seconds_compile": round(compiled - populated, 2),
                "seconds_backup": round(backed_up - compiled, 2),
                "seconds_verify": round(time.monotonic() - backed_up, 2),
            }
            if args.second_snapshot:
                if args.append_one:
                    item_id = "appended-item"
                    text = (hashlib.shake_256(item_id.encode()).hexdigest(
                        (args.text_bytes + 1) // 2)[:args.text_bytes]
                        if args.varied_text else shared_text)
                    body = json.dumps({"id": item_id, "type": "userMessage",
                                       "content": [{"type": "text", "text": text}]})
                    with sqlite3.connect(database) as connection:
                        connection.execute("INSERT INTO thread_items VALUES (?,?,?,?,?,?,?,?)",
                                           ("00000000-0000-4000-8000-%012d" % 0,
                                            "appended-turn", item_id, args.items_per_thread,
                                            args.items_per_thread, body, "userMessage",
                                            args.items_per_thread))
                second_started = time.monotonic()
                second = backup(str(source), str(vault), crypto_helper=str(helper))
                if second.snapshot_id == result.snapshot_id or second.recovery_key is not None:
                    raise AssertionError("second snapshot did not reuse the Vault identity")
                verified_second = verify_snapshot(str(vault), snapshot=second.snapshot_id,
                                                  crypto_helper=str(helper))
                if verified_second.transcript_files != args.threads:
                    raise AssertionError("second snapshot did not verify exactly")
                second_objects = {path.relative_to(vault).as_posix() for path in
                                  (vault / "objects").rglob("*.cvchunk")}
                if args.append_one:
                    if not first_objects < second_objects:
                        raise AssertionError("changed snapshot did not retain old and new chunks")
                elif second_objects != first_objects:
                    raise AssertionError("unchanged snapshot wrote new encrypted chunks")
                metrics["seconds_second_backup_and_verify"] = round(
                    time.monotonic() - second_started, 2)
                metrics["objects_retained"] = len(first_objects & second_objects)
                metrics["objects_added"] = len(second_objects - first_objects)
                metrics["new_ciphertext_bytes"] = sum(
                    (vault / relative).stat().st_size for relative in
                    second_objects - first_objects)
                metrics["vault_bytes_after_second"] = sum(
                    path.stat().st_size for path in vault.rglob("*") if path.is_file())
            print(json.dumps(metrics, sort_keys=True))
        finally:
            metadata = vault / "vault.json"
            if metadata.is_file():
                key_id = json.loads(metadata.read_text())["key_id"]
                subprocess.run([str(helper), "delete-key", "--key-id", key_id],
                               check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


if __name__ == "__main__":
    main()
