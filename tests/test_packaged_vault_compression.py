"""Opt-in exact-package Vault round trip with disposable synthetic history.

Set CODEX_MIGRATE_PACKAGED_APP to an extracted local-test app. Recovery material
is captured only in memory and never printed or written to a receipt.
"""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.environ.get("CODEX_MIGRATE_PACKAGED_APP"),
                     "requires an explicit packaged app path")
class PackagedVaultCompressionTests(unittest.TestCase):
    def test_bundled_engine_and_crypto_helper_restore_exact_bytes(self):
        app = Path(os.environ["CODEX_MIGRATE_PACKAGED_APP"])
        resources = app / "Contents/Resources"
        engine = resources / "engine/codex-migrate-engine"
        helper = resources / "CodexVaultCrypto"
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
                backup = subprocess.run([
                    str(engine), "vault", "--source-home", str(source), "backup",
                    "--destination", str(vault), "--apply", "--json",
                ], capture_output=True, check=True, timeout=120)
                result = json.loads(backup.stdout)
                self.assertTrue(result["applied"])
                self.assertEqual(result["transcript_files"], 1)
                key_id = json.loads((vault / "vault.json").read_text())["key_id"]
                objects = list((vault / "objects").rglob("*.cvchunk"))
                self.assertLess(sum(path.stat().st_size for path in objects),
                                transcript.stat().st_size // 2)
                subprocess.run([
                    str(engine), "vault", "verify", "--vault", str(vault), "--json",
                ], capture_output=True, check=True, timeout=120)
                subprocess.run([
                    str(engine), "vault", "--source-home", str(source), "restore",
                    "--vault", str(vault), "--output", str(restored), "--apply", "--json",
                ], capture_output=True, check=True, timeout=120)
                self.assertEqual(hashlib.sha256(
                    (restored / "sessions/fixture.jsonl").read_bytes()).hexdigest(), expected)
            finally:
                if key_id is None and (vault / "vault.json").is_file():
                    key_id = json.loads((vault / "vault.json").read_text())["key_id"]
                if key_id is not None:
                    subprocess.run([
                        str(helper), "delete-key", "--key-id", key_id,
                    ], capture_output=True, check=True, timeout=30)


if __name__ == "__main__":
    unittest.main()
