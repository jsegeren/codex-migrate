"""Synthetic-only checks for conversation-only sizing; no customer data."""

import gzip
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "ops/vault-message-size.py"


def record(kind, payload):
    return (json.dumps({"type": kind, "payload": payload}) + "\n").encode()


class VaultMessageSizeTests(unittest.TestCase):
    def fixture(self, root, body):
        home = root / "home"
        sessions = home / ".codex/sessions/2026/09/26"
        sessions.mkdir(parents=True)
        transcript = sessions / "one.jsonl"
        transcript.write_bytes(body)
        return home, transcript

    def test_keeps_only_original_user_and_assistant_messages(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            user = record("response_item", {"type": "message", "role": "user",
                                            "content": "PRIVATE-USER"})
            assistant = record("response_item", {"type": "message", "role": "assistant",
                                                 "content": "PRIVATE-ASSISTANT"})
            tool = record("response_item", {"type": "function_call_output",
                                            "output": "PRIVATE-TOOL"})
            event = record("event_msg", {"type": "agent_message",
                                         "message": "PRIVATE-DUPLICATE"})
            home, transcript = self.fixture(root, user + tool + event + assistant)
            result = runpy.run_path(str(SCRIPT))["estimate"](str(home))
            self.assertTrue(result["complete"])
            self.assertEqual(result["transcripts"], 1)
            self.assertEqual(result["source_bytes"], transcript.stat().st_size)
            self.assertEqual(result["message_records"], 2)
            self.assertEqual(result["message_source_bytes"], len(user + assistant))
            self.assertEqual(result["message_gzip_bytes"], len(gzip.compress(user + assistant)))
            self.assertEqual(transcript.read_bytes(), user + tool + event + assistant)

    def test_oversized_record_makes_result_incomplete_without_leaking_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            oversized = record("response_item", {"type": "message", "role": "user",
                                                 "content": "PRIVATE-" + "X" * 200})
            home, _ = self.fixture(root, oversized)
            estimate = runpy.run_path(str(SCRIPT))["estimate"]
            estimate.__globals__["MAX_RECORD_BYTES"] = 80
            result = estimate(str(home))
            self.assertFalse(result["complete"])
            self.assertEqual(result["unclassified_records"], 1)
            self.assertEqual(result["unclassified_bytes"], len(oversized))

    def test_cli_output_is_aggregate_only_and_linked_home_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home, _ = self.fixture(root, record("response_item", {
                "type": "message", "role": "user", "content": "PRIVATE-FIXTURE"}))
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--source-home", str(home)],
                capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(result.stdout)["message_records"], 1)
            self.assertNotIn("PRIVATE-FIXTURE", result.stdout + result.stderr)
            self.assertNotIn(str(home), result.stdout + result.stderr)
            linked = root / "linked"
            linked.mkdir()
            (linked / ".codex").symlink_to(home / ".codex")
            refused = subprocess.run(
                [sys.executable, str(SCRIPT), "--source-home", str(linked)],
                capture_output=True, text=True)
            self.assertNotEqual(refused.returncode, 0)
            self.assertNotIn(str(linked), refused.stdout + refused.stderr)


if __name__ == "__main__":
    unittest.main()
