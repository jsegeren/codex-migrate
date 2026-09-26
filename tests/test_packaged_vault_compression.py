"""Opt-in exact-package Vault round trip with disposable synthetic history.

Set CODEX_MIGRATE_PACKAGED_APP to an extracted local-test app. Recovery material
is captured only in memory and never printed or written to a receipt.
"""

import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import tempfile
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
