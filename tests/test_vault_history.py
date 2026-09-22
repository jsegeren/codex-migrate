import json
from pathlib import Path
import platform
import subprocess
import tempfile
import unittest

from codex_migrate.vault import search
from codex_migrate.vault_backup import backup
from codex_migrate.vault_history import search_titles, thread_timeline
from codex_migrate.vault_identity import loss_warnings, peek_identity
from codex_migrate.vault_recovery import snapshot_catalog, verify_snapshot


THREAD_ID = "44444444-4444-4444-8444-444444444444"


def record(kind, payload):
    return json.dumps({"type": kind, "payload": payload}) + "\n"


class IdentityTests(unittest.TestCase):
    def test_embedded_id_survives_rename_and_conflict_needs_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "renamed.jsonl"
            path.write_text(record("session_meta", {"id": THREAD_ID}))
            self.assertEqual(peek_identity(path, path.name), (THREAD_ID, "verified"))
            self.assertEqual(peek_identity(path, "rollout-" + THREAD_ID + ".jsonl"),
                             (THREAD_ID, "verified"))
            self.assertEqual(
                peek_identity(path, "rollout-11111111-1111-4111-8111-111111111111.jsonl"),
                (None, "needs_review"),
            )

    def test_lost_assistant_messages_are_flagged_without_logging_content(self):
        previous = [{"thread_id": THREAD_ID, "identity_state": "verified",
                     "size": 1000, "assistant_messages": 300}]
        current = [{"thread_id": THREAD_ID, "identity_state": "verified",
                    "size": 950, "assistant_messages": 0}]
        self.assertEqual(loss_warnings(previous, current), [THREAD_ID])

    def test_reported_851mb_to_7mb_compaction_shape_flags_previous_version(self):
        previous = [{"thread_id": THREAD_ID, "identity_state": "verified",
                     "size": 851046757, "records": 122877,
                     "assistant_messages": 3777}]
        current = [{"thread_id": THREAD_ID, "identity_state": "verified",
                    "size": 7117868, "records": 762,
                    "assistant_messages": 0}]
        self.assertEqual(loss_warnings(previous, current), [THREAD_ID])


@unittest.skipUnless(platform.system() == "Darwin", "CryptoKit helper requires macOS")
class EncryptedHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory()
        cls.helper = Path(cls.build.name) / "CodexVaultCrypto"
        subprocess.run([
            "xcrun", "swiftc", "-parse-as-library", "-O",
            "-target", platform.machine() + "-apple-macos13.0",
            "desktop/CodexVaultCrypto.swift", "-o", str(cls.helper),
        ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def test_duplicate_live_thread_id_needs_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            sessions = source / ".codex/sessions"
            sessions.mkdir(parents=True)
            for name in ("first.jsonl", "second.jsonl"):
                (sessions / name).write_text(record("session_meta", {"id": THREAD_ID}))
            vault = root / "vault"
            try:
                result = backup(str(source), str(vault), crypto_helper=str(self.helper))
                self.assertTrue(result.needs_attention)
                self.assertEqual(result.at_risk_threads, 2)
                catalog = snapshot_catalog(str(vault), crypto_helper=str(self.helper))
                self.assertEqual([item["identity_state"] for item in catalog],
                                 ["needs_review", "needs_review"])
                self.assertTrue(all(item["at_risk"] for item in catalog))
            finally:
                if (vault / "vault.json").exists():
                    key_id = json.loads((vault / "vault.json").read_text())["key_id"]
                    subprocess.run([str(self.helper), "delete-key", "--key-id", key_id],
                                   check=True, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)

    def test_titles_and_versions_are_encrypted_and_rewrite_is_flagged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            codex = source / ".codex"
            path = codex / "sessions/rollout-" / ("rollout-" + THREAD_ID + ".jsonl")
            path.parent.mkdir(parents=True)
            index = codex / "session_index.jsonl"
            index.write_text(json.dumps({"id": THREAD_ID, "thread_name": "Unification Foundation"}) + "\n")
            initial = record("session_meta", {"id": THREAD_ID})
            initial += "".join(record("response_item", {"role": "assistant", "content": "PRIVATE WORK"})
                               for _ in range(12))
            path.write_text(initial)
            vault = root / "vault"
            try:
                first = backup(str(source), str(vault), crypto_helper=str(self.helper))
                self.assertFalse(first.needs_attention)
                catalog = snapshot_catalog(str(vault), crypto_helper=str(self.helper))
                self.assertEqual(catalog[0]["thread_id"], THREAD_ID)
                self.assertEqual(catalog[0]["titles"], ["Unification Foundation"])
                self.assertEqual(catalog[0]["assistant_messages"], 12)
                self.assertEqual(len(search(str(source), "Unification Foundation")), 1)
                ciphertext = b"".join(item.read_bytes() for item in vault.rglob("*")
                                      if item.is_file())
                self.assertNotIn(b"Unification Foundation", ciphertext)
                self.assertNotIn(b"PRIVATE WORK", ciphertext)

                index.write_text(index.read_text()
                                 + json.dumps({"id": THREAD_ID,
                                               "thread_name": "Release Manager"}) + "\n")
                second = backup(str(source), str(vault), crypto_helper=str(self.helper))
                self.assertFalse(second.needs_attention)
                hits = search_titles(str(vault), "Unification Foundation",
                                     crypto_helper=str(self.helper))
                self.assertEqual(len(hits), 1)
                self.assertEqual(hits[0]["thread_id"], THREAD_ID)
                timeline = thread_timeline(str(vault), "id:" + THREAD_ID,
                                           crypto_helper=str(self.helper))
                self.assertEqual(len(timeline), 2)  # Title changed, bytes did not.

                path.write_text(record("session_meta", {"id": THREAD_ID})
                                + record("response_item", {"role": "user", "content": "keep me"}))
                third = backup(str(source), str(vault), crypto_helper=str(self.helper))
                self.assertTrue(third.needs_attention)
                self.assertEqual(third.at_risk_threads, 1)
                self.assertTrue(snapshot_catalog(str(vault), crypto_helper=str(self.helper))[0]["at_risk"])
                fourth = backup(str(source), str(vault), crypto_helper=str(self.helper))
                self.assertTrue(fourth.needs_attention)  # Later identical captures cannot clear a loss.
                verify_snapshot(str(vault), snapshot=first.snapshot_id,
                                crypto_helper=str(self.helper))
                timeline = thread_timeline(str(vault), "id:" + THREAD_ID,
                                           crypto_helper=str(self.helper))
                self.assertEqual(timeline[0]["snapshot_id"], fourth.snapshot_id)
                self.assertEqual(len(timeline), 3)
            finally:
                if (vault / "vault.json").exists():
                    key_id = json.loads((vault / "vault.json").read_text())["key_id"]
                    subprocess.run([str(self.helper), "delete-key", "--key-id", key_id],
                                   check=True, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
