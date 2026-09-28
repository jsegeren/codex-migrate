"""Opt-in exact-package Vault round trip with disposable synthetic history.

Set CODEX_MIGRATE_PACKAGED_APP to an extracted local-test app. Recovery material
is captured only in memory and never printed or written to a receipt.
"""

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest


def run_packaged(command, timeout=30):
    """Bound a packaged engine and its helper; never surface captured key output."""
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True)
    try:
        stdout, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
        raise AssertionError("packaged Vault command timed out; check Keychain access") from None
    if process.returncode:
        raise AssertionError("packaged Vault command failed without publishing output")
    return stdout


@unittest.skipUnless(os.environ.get("CODEX_MIGRATE_PACKAGED_APP"),
                     "requires an explicit packaged app path")
class PackagedVaultCompressionTests(unittest.TestCase):
    def test_bundled_engine_recovers_database_only_paginated_item(self):
        app = Path(os.environ["CODEX_MIGRATE_PACKAGED_APP"])
        resources = app / "Contents/Resources"
        engine = resources / "engine/codex-migrate-engine"
        helper = resources / "CodexVaultCrypto"
        if not helper.is_file():
            helper = app / "Contents/Helpers/CodexVaultCrypto.app/Contents/MacOS/CodexVaultCrypto"
        self.assertTrue(engine.is_file() and helper.is_file())
        thread_id = "44444444-4444-4444-8444-444444444444"
        marker = "packaged-database-only-marker-qzmx"
        with tempfile.TemporaryDirectory(prefix="vault-package-paginated-test-") as temporary:
            root = Path(temporary)
            source = root / "source"
            codex = source / ".codex"
            rollout = codex / "sessions" / ("rollout-" + thread_id + ".jsonl")
            rollout.parent.mkdir(parents=True)
            rollout.write_text(json.dumps({"type": "session_meta", "payload": {
                "id": thread_id,
            }}) + "\n", encoding="utf-8")
            database = codex / "thread_history_1.sqlite"
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE thread_items ("
                                   "thread_id TEXT, turn_id TEXT, item_id TEXT, "
                                   "rollout_ordinal INTEGER, created_at_ms INTEGER, "
                                   "item_json TEXT, item_type TEXT, updated_at_ordinal INTEGER)")
                connection.execute("CREATE TABLE thread_history_projection_state ("
                                   "thread_id TEXT, next_rollout_byte_offset INTEGER, "
                                   "next_rollout_ordinal INTEGER)")
                connection.execute("INSERT INTO thread_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                   (thread_id, "turn-1", "item-1", 1, 100,
                                    json.dumps({"id": "item-1", "type": "userMessage",
                                                "content": [{"type": "text", "text": marker}]}),
                                    "userMessage", 1))
            original_database = database.read_bytes()
            vault = root / "vault"
            restored_home = root / "restored-home"
            restored_home.mkdir()
            restored = restored_home / ".codex"
            key_id = None
            try:
                live = json.loads(run_packaged([
                    str(engine), "vault", "--source-home", str(source),
                    "search", marker, "--json",
                ]))
                self.assertTrue(any(result["collection"] == "paginated" for result in live))
                saved = json.loads(run_packaged([
                    str(engine), "vault", "--source-home", str(source), "backup",
                    "--destination", str(vault), "--apply", "--json",
                ], timeout=120))
                self.assertTrue(saved["applied"])
                first_snapshot = saved["snapshot_id"]
                key_id = json.loads((vault / "vault.json").read_text())["key_id"]
                self.assertEqual(database.read_bytes(), original_database)
                run_packaged([str(engine), "vault", "verify", "--vault", str(vault),
                              "--json"], timeout=120)
                second_marker = "scheduled-database-only-marker-nyvk"
                with sqlite3.connect(database) as connection:
                    connection.execute("INSERT INTO thread_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                       (thread_id, "turn-2", "item-2", 2, 200,
                                        json.dumps({"id": "item-2", "type": "userMessage",
                                                    "content": [{"type": "text", "text": second_marker}]}),
                                        "userMessage", 2))
                updated_database = database.read_bytes()
                config_path = source / "Library/Application Support/Codex Vault/schedule.json"
                config_path.parent.mkdir(parents=True)
                configuration = {
                    "format": "codex-vault-schedule", "version": 2,
                    "source_home": str(source), "vault": str(vault),
                    "vault_key_id": key_id, "crypto_helper": str(helper),
                    "interval_seconds": 24 * 3600,
                    "installed_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
                }
                descriptor = os.open(config_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    json.dump(configuration, handle)
                run_packaged([str(engine), "vault", "--source-home", str(source),
                              "scheduled-run", "--config", str(config_path)], timeout=120)
                receipt = json.loads((config_path.parent / "last-run.json").read_text())
                self.assertEqual(receipt["status"], "needs_attention")
                self.assertNotEqual(receipt["snapshot_id"], first_snapshot)
                self.assertEqual(database.read_bytes(), updated_database)
                run_packaged([str(engine), "vault", "verify", "--vault", str(vault),
                              "--json"], timeout=120)
                run_packaged([str(engine), "vault", "--source-home", str(source),
                              "restore", "--vault", str(vault), "--output", str(restored),
                              "--apply", "--json"], timeout=120)
                restored_items = restored / "paginated_history" / (thread_id + ".jsonl")
                self.assertTrue(restored_items.is_file())
                records = [json.loads(line) for line in
                           restored_items.read_text(encoding="utf-8").splitlines()]
                self.assertEqual(len(records), 2)
                self.assertEqual(records[0]["source"], "codex-paginated-thread-items-v1")
                self.assertEqual(records[0]["thread_id"], thread_id)
                self.assertEqual(json.loads(records[0]["item_json"])["content"][0]["text"],
                                 marker)
                self.assertEqual(json.loads(records[1]["item_json"])["content"][0]["text"],
                                 second_marker)
                first_restored = root / "first-restored"
                run_packaged([str(engine), "vault", "--source-home", str(source),
                              "restore", "--vault", str(vault), "--snapshot", first_snapshot,
                              "--output", str(first_restored), "--apply", "--json"], timeout=120)
                first_items = (first_restored / "paginated_history" / (thread_id + ".jsonl"))
                self.assertEqual(len(first_items.read_text(encoding="utf-8").splitlines()), 1)
            finally:
                if key_id is None and (vault / "vault.json").is_file():
                    key_id = json.loads((vault / "vault.json").read_text())["key_id"]
                if key_id is not None:
                    run_packaged([str(helper), "delete-key", "--key-id", key_id])

    @unittest.skipUnless(sys.platform == "darwin" and
                         os.environ.get("CODEX_MIGRATE_LAUNCHAGENT_PAGINATED_TEST") == "yes",
                         "opt in to a disposable real macOS LaunchAgent test")
    def test_real_launch_agent_captures_appended_paginated_history(self):
        app = Path(os.environ["CODEX_MIGRATE_PACKAGED_APP"])
        engine = app / "Contents/Resources/engine/codex-migrate-engine"
        helper = app / "Contents/Helpers/CodexVaultCrypto.app/Contents/MacOS/CodexVaultCrypto"
        self.assertTrue(engine.is_file() and helper.is_file())
        label = "com.segeren.codex-vault.backup"
        service = "gui/%d/%s" % (os.getuid(), label)
        if subprocess.run(["/bin/launchctl", "print", service],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            self.skipTest("the account already has a Vault backup agent")
        if (Path.home() / "Library/LaunchAgents" / (label + ".plist")).exists():
            self.skipTest("the account already has a Vault backup configuration")
        thread_id = "77777777-7777-4777-8777-777777777777"
        with tempfile.TemporaryDirectory(prefix="vault-package-launchagent-paginated-") as temporary:
            root = Path(temporary)
            source = root / "source"
            codex = source / ".codex"
            rollout = codex / "sessions" / ("rollout-" + thread_id + ".jsonl")
            rollout.parent.mkdir(parents=True)
            rollout.write_text(json.dumps({"type": "session_meta", "payload": {
                "id": thread_id,
            }}) + "\n", encoding="utf-8")
            database = codex / "thread_history_1.sqlite"
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE thread_items ("
                                   "thread_id TEXT, turn_id TEXT, item_id TEXT, "
                                   "rollout_ordinal INTEGER, created_at_ms INTEGER, "
                                   "item_json TEXT, item_type TEXT, updated_at_ordinal INTEGER)")
                connection.execute("CREATE TABLE thread_history_projection_state ("
                                   "thread_id TEXT, next_rollout_byte_offset INTEGER, "
                                   "next_rollout_ordinal INTEGER)")
                connection.execute("INSERT INTO thread_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                   (thread_id, "turn-1", "item-1", 1, 100,
                                    json.dumps({"id": "item-1", "type": "userMessage",
                                                "content": [{"type": "text", "text": "before-wake"}]}),
                                    "userMessage", 1))
            vault = root / "vault"
            key_id = None
            installed = False
            try:
                first = json.loads(run_packaged([
                    str(engine), "vault", "--source-home", str(source), "backup",
                    "--destination", str(vault), "--apply", "--json",
                ], timeout=120))
                key_id = json.loads((vault / "vault.json").read_text())["key_id"]
                run_packaged([
                    str(engine), "vault", "--source-home", str(source), "schedule",
                    "--vault", str(vault), "--crypto-helper", str(helper), "--apply", "--json",
                ], timeout=60)
                installed = True
                config_path = source / "Library/Application Support/Codex Vault/schedule.json"
                config = json.loads(config_path.read_text(encoding="utf-8"))
                config["installed_at"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
                config_path.write_text(json.dumps(config), encoding="utf-8")
                with sqlite3.connect(database) as connection:
                    connection.execute("INSERT INTO thread_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                       (thread_id, "turn-2", "item-2", 2, 200,
                                        json.dumps({"id": "item-2", "type": "userMessage",
                                                    "content": [{"type": "text", "text": "after-wake"}]}),
                                        "userMessage", 2))
                source_bytes = database.read_bytes()
                started = subprocess.run(["/bin/launchctl", "kickstart", "-k", service],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                         timeout=60)
                self.assertEqual(started.returncode, 0, "disposable LaunchAgent did not start")
                receipt_path = config_path.parent / "last-run.json"
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if receipt_path.exists():
                        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                        if receipt.get("status") in ("completed", "needs_attention", "failed"):
                            break
                    time.sleep(0.05)
                else:
                    self.fail("disposable LaunchAgent produced no final backup receipt")
                self.assertEqual(receipt["status"], "needs_attention")
                self.assertTrue(receipt["paginated_history_unprotected"])
                self.assertNotEqual(receipt["snapshot_id"], first["snapshot_id"])
                self.assertEqual(database.read_bytes(), source_bytes)
                for snapshot, expected in ((first["snapshot_id"], 1),
                                           (receipt["snapshot_id"], 2)):
                    output = root / ("recovered-" + str(expected))
                    run_packaged([str(engine), "vault", "--source-home", str(source),
                                  "restore", "--vault", str(vault), "--snapshot", snapshot,
                                  "--output", str(output), "--apply", "--json"], timeout=120)
                    items = output / "paginated_history" / (thread_id + ".jsonl")
                    records = [json.loads(line) for line in
                               items.read_text(encoding="utf-8").splitlines()]
                    self.assertEqual(len(records), expected)
                    self.assertEqual(json.loads(records[-1]["item_json"])["content"][0]["text"],
                                     "before-wake" if expected == 1 else "after-wake")
            finally:
                try:
                    if installed:
                        run_packaged([str(engine), "vault", "--source-home", str(source),
                                      "schedule-remove", "--apply", "--json"], timeout=30)
                        self.assertNotEqual(subprocess.run(
                            ["/bin/launchctl", "print", service], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL).returncode, 0)
                finally:
                    if key_id is None and (vault / "vault.json").is_file():
                        key_id = json.loads((vault / "vault.json").read_text())["key_id"]
                    if key_id is not None:
                        run_packaged([str(helper), "delete-key", "--key-id", key_id])

    def test_bundled_engine_search_index_preserves_live_search(self):
        app = Path(os.environ["CODEX_MIGRATE_PACKAGED_APP"])
        engine = app / "Contents/Resources/engine/codex-migrate-engine"
        self.assertTrue(engine.is_file())
        with tempfile.TemporaryDirectory(prefix="vault-package-index-test-") as temporary:
            source = Path(temporary) / "source"
            transcript = source / ".codex/sessions/fixture.jsonl"
            transcript.parent.mkdir(parents=True)
            transcript.write_text(json.dumps({"payload": {"message": {
                "content": "Unification Foundation"
            }}}) + "\n", encoding="utf-8")

            def search_for(phrase):
                output = run_packaged([
                    str(engine), "vault", "--source-home", str(source),
                    "search", phrase, "--json",
                ])
                return json.loads(output)

            self.assertEqual(len(search_for("Unification Foundation")), 1)
            built = json.loads(run_packaged([
                str(engine), "vault", "--source-home", str(source),
                "search-index", "--apply", "--json",
            ]))
            self.assertTrue(built["applied"])
            self.assertEqual(built["indexed"], 1)
            index = source / "Library/Caches/Codex Migrate/search-index-v1.sqlite"
            self.assertTrue(index.is_file())
            self.assertEqual(index.stat().st_mode & 0o077, 0)
            self.assertEqual(len(search_for("Unification Foundation")), 1)

            with transcript.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"payload": {"message": {
                    "content": "Clerk follow-up"
                }}}) + "\n")
            self.assertEqual(len(search_for("Clerk follow-up")), 1)
            archived = source / ".codex/archived_sessions/fixture.jsonl"
            archived.parent.mkdir(parents=True)
            transcript.replace(archived)
            self.assertEqual(search_for("Clerk follow-up")[0]["collection"], "archived")
            refreshed = json.loads(run_packaged([
                str(engine), "vault", "--source-home", str(source),
                "search-index", "--apply", "--json",
            ]))
            self.assertTrue(refreshed["applied"])
            self.assertEqual(search_for("Clerk follow-up")[0]["collection"], "archived")
            removed = json.loads(run_packaged([
                str(engine), "vault", "--source-home", str(source),
                "search-index-remove", "--apply", "--json",
            ]))
            self.assertTrue(removed["applied"])
            self.assertFalse(index.exists())
            self.assertEqual(len(search_for("Clerk follow-up")), 1)

    def test_bundled_engine_search_ignores_missing_thread_store_table(self):
        app = Path(os.environ["CODEX_MIGRATE_PACKAGED_APP"])
        engine = app / "Contents/Resources/engine/codex-migrate-engine"
        self.assertTrue(engine.is_file())
        with tempfile.TemporaryDirectory(prefix="vault-package-search-test-") as temporary:
            source = Path(temporary) / "source"
            codex = source / ".codex"
            transcript = codex / "sessions/fixture.jsonl"
            transcript.parent.mkdir(parents=True)
            transcript.write_text(json.dumps({"payload": {"message": {
                "content": "Recover the missing thread-store fixture"
            }}}) + "\n")
            database = codex / "state_5.sqlite"
            with sqlite3.connect(str(database)) as connection:
                connection.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
            original = database.read_bytes()

            output = run_packaged([
                str(engine), "vault", "--source-home", str(source), "search",
                "missing thread-store fixture", "--json",
            ])
            matches = json.loads(output)
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0]["transcript"], "fixture.jsonl")
            self.assertEqual(database.read_bytes(), original)

    def test_bundled_engine_and_crypto_helper_restore_exact_bytes(self):
        app = Path(os.environ["CODEX_MIGRATE_PACKAGED_APP"])
        resources = app / "Contents/Resources"
        engine = resources / "engine/codex-migrate-engine"
        helper = resources / "CodexVaultCrypto"
        if not helper.is_file():
            helper = app / "Contents/Helpers/CodexVaultCrypto.app/Contents/MacOS/CodexVaultCrypto"
        self.assertTrue(engine.is_file() and helper.is_file())
        with tempfile.TemporaryDirectory(prefix="vault-package-test-") as temporary:
            root = Path(temporary)
            source = root / "source"
            transcript = source / ".codex/sessions/fixture.jsonl"
            transcript.parent.mkdir(parents=True)
            content = "".join(f"{index:08x}" + "A" * 65528 for index in range(16))
            transcript.write_text(json.dumps({"payload": {"text": content}}) + "\n")
            expected = hashlib.sha256(transcript.read_bytes()).hexdigest()
            vault = root / "vault"
            restored = root / "restored"
            key_id = None
            try:
                backup = run_packaged([
                    str(engine), "vault", "--source-home", str(source), "backup",
                    "--destination", str(vault), "--apply", "--json",
                ], timeout=120)
                result = json.loads(backup)
                self.assertTrue(result["applied"])
                self.assertEqual(result["transcript_files"], 1)
                key_id = json.loads((vault / "vault.json").read_text())["key_id"]
                objects = list((vault / "objects").rglob("*.cvchunk"))
                self.assertLess(sum(path.stat().st_size for path in objects),
                                transcript.stat().st_size // 2)
                run_packaged([
                    str(engine), "vault", "verify", "--vault", str(vault), "--json",
                ], timeout=120)
                run_packaged([
                    str(engine), "vault", "--source-home", str(source), "restore",
                    "--vault", str(vault), "--output", str(restored), "--apply", "--json",
                ], timeout=120)
                self.assertEqual(hashlib.sha256(
                    (restored / "sessions/fixture.jsonl").read_bytes()).hexdigest(), expected)
            finally:
                if key_id is None and (vault / "vault.json").is_file():
                    key_id = json.loads((vault / "vault.json").read_text())["key_id"]
                if key_id is not None:
                    run_packaged([
                        str(helper), "delete-key", "--key-id", key_id,
                    ])

    @unittest.skipUnless(os.environ.get("CODEX_MIGRATE_LEGACY_PACKAGED_APP"),
                         "requires an explicit previous packaged app path")
    def test_previous_package_snapshot_survives_compressed_upgrade(self):
        current = Path(os.environ["CODEX_MIGRATE_PACKAGED_APP"]) / "Contents/Resources"
        legacy = Path(os.environ["CODEX_MIGRATE_LEGACY_PACKAGED_APP"]) / "Contents/Resources"
        current_engine = current / "engine/codex-migrate-engine"
        old_engine = legacy / "engine/codex-migrate-engine"
        old_helper = legacy / "CodexVaultCrypto"
        self.assertTrue(all(path.is_file() for path in
                            (current_engine, old_engine, old_helper)))
        with tempfile.TemporaryDirectory(prefix="vault-upgrade-test-") as temporary:
            root = Path(temporary)
            source = root / "source"
            transcript = source / ".codex/sessions/fixture.jsonl"
            transcript.parent.mkdir(parents=True)
            transcript.write_text(json.dumps({"payload": {"text": "A" * 200_000}}) + "\n")
            vault = root / "vault"
            first_restore = root / "first-restore"
            second_restore = root / "second-restore"
            key_id = None
            try:
                old_backup = run_packaged([
                    str(old_engine), "vault", "--source-home", str(source), "backup",
                    "--destination", str(vault), "--apply", "--json",
                ], timeout=120)
                first = json.loads(old_backup)
                key_id = json.loads((vault / "vault.json").read_text())["key_id"]
                self.assertNotIn("storage_codec", json.loads((vault / "vault.json").read_text()))
                run_packaged([
                    str(current_engine), "vault", "--source-home", str(source), "restore",
                    "--vault", str(vault), "--snapshot", first["snapshot_id"],
                    "--output", str(first_restore), "--apply", "--json",
                ], timeout=15)
                self.assertEqual((first_restore / "sessions/fixture.jsonl").read_bytes(),
                                 transcript.read_bytes())
                transcript.write_text(json.dumps({"payload": {"text": "B" * 250_000}}) + "\n")
                new_backup = run_packaged([
                    str(current_engine), "vault", "--source-home", str(source), "backup",
                    "--destination", str(vault), "--apply", "--json",
                ], timeout=120)
                second = json.loads(new_backup)
                self.assertNotEqual(first["snapshot_id"], second["snapshot_id"])
                self.assertEqual(json.loads((vault / "vault.json").read_text())
                                 ["storage_codec"], "lzfse-v1")
                run_packaged([
                    str(current_engine), "vault", "--source-home", str(source), "restore",
                    "--vault", str(vault), "--snapshot", second["snapshot_id"],
                    "--output", str(second_restore), "--apply", "--json",
                ], timeout=15)
                self.assertEqual((second_restore / "sessions/fixture.jsonl").read_bytes(),
                                 transcript.read_bytes())
            finally:
                if key_id is None and (vault / "vault.json").is_file():
                    key_id = json.loads((vault / "vault.json").read_text())["key_id"]
                if key_id is not None:
                    run_packaged([
                        str(old_helper), "delete-key", "--key-id", key_id,
                    ])


if __name__ == "__main__":
    unittest.main()
