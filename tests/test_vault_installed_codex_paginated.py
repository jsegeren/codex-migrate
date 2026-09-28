"""Opt-in proof against the installed Codex app-server using synthetic work only.

Run with CODEX_MIGRATE_TEST_INSTALLED_CODEX=1. CODEX_HOME, working directory,
and model endpoint are all isolated; no real account or conversation is used.
"""

import http.server
import json
import os
from pathlib import Path
import platform
import queue
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import unittest
import uuid

from codex_migrate.vault import markdown_chunks, read_thread_page, search
from codex_migrate.vault_backup import backup
from codex_migrate.vault_recovery import (
    import_recovery_key, restore_snapshot, snapshot_catalog,
)


class _SyntheticModel(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        response_id = str(uuid.uuid4())
        item = {
            "id": "msg-" + response_id, "type": "message", "role": "assistant",
            "status": "completed", "content": [{
                "type": "output_text", "text": "Synthetic reply", "annotations": [],
            }],
        }
        events = [
            {"type": "response.created", "response": {"id": response_id}},
            {"type": "response.output_item.added", "output_index": 0, "item": item},
            {"type": "response.output_item.done", "output_index": 0, "item": item},
            {"type": "response.completed", "response": {
                "id": response_id, "status": "completed", "output": [item],
                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            }},
        ]
        body = "".join("event: " + event["type"] + "\ndata: " +
                       json.dumps(event) + "\n\n" for event in events).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _AppServer:
    def __init__(self, binary: str, codex_home: Path, cwd: Path):
        environment = dict(os.environ)
        for name in list(environment):
            if (name.startswith(("OPENAI_", "CODEX_", "CHATGPT_", "ANTHROPIC_", "XAI_"))
                    or name.endswith(("_API_KEY", "_TOKEN"))):
                environment.pop(name)
        environment["CODEX_HOME"] = str(codex_home)
        environment["CODEX_APP_SERVER_DISABLE_MANAGED_CONFIG"] = "1"
        self.process = subprocess.Popen(
            [binary, "app-server", "--stdio"], cwd=str(cwd), env=environment,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8")
        self.incoming = queue.Queue()
        self.events = []
        self.request_id = 0
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            for line in self.process.stdout:
                self.incoming.put(json.loads(line))
        finally:
            self.incoming.put(None)

    def _receive(self, timeout=30):
        response = self.incoming.get(timeout=timeout)
        if response is None:
            raise AssertionError("isolated Codex app-server closed unexpectedly")
        return response

    def send(self, message):
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def call(self, method, **params):
        self.request_id += 1
        self.send({"id": self.request_id, "method": method, "params": params})
        deadline = time.monotonic() + 30
        while True:
            response = self._receive(max(0, deadline - time.monotonic()))
            if response.get("id") == self.request_id:
                if "error" in response:
                    raise AssertionError("isolated Codex %s failed: %s" %
                                         (method, response["error"]))
                return response["result"]
            self.events.append(response)

    def turn(self, thread_id, text):
        started = self.call("turn/start", threadId=thread_id, input=[{
            "type": "text", "text": text, "text_elements": [],
        }])
        turn_id = started["turn"]["id"]
        deadline = time.monotonic() + 30
        while True:
            for event in self.events:
                params = event.get("params", {})
                turn = params.get("turn", {})
                if (event.get("method") == "turn/completed"
                        and params.get("threadId") == thread_id
                        and turn.get("id") == turn_id):
                    self.events.remove(event)
                    self.assert_completed(turn)
                    return turn_id
            self.events.append(self._receive(max(0, deadline - time.monotonic())))

    @staticmethod
    def assert_completed(turn):
        if turn.get("status") != "completed":
            raise AssertionError("isolated synthetic Codex turn did not complete")

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
        self.reader.join(timeout=2)
        self.process.stdin.close()
        self.process.stdout.close()


@unittest.skipUnless(platform.system() == "Darwin", "installed Mac proof requires macOS")
@unittest.skipUnless(os.environ.get("CODEX_MIGRATE_TEST_INSTALLED_CODEX") == "1",
                     "explicit installed Codex opt-in required")
class InstalledCodexPaginatedTests(unittest.TestCase):
    def test_database_only_inherited_content_survives_backup_and_restore(self):
        binary = os.environ.get("CODEX_MIGRATE_TEST_CODEX_BINARY") or shutil.which("codex")
        if not binary:
            self.skipTest("Codex CLI is not installed")
        with tempfile.TemporaryDirectory(prefix="codex-vault-installed-proof-") as temporary:
            home = Path(temporary)
            source = home / "source"
            codex_home = source / ".codex"
            codex_home.mkdir(parents=True)
            with http.server.ThreadingHTTPServer(("127.0.0.1", 0), _SyntheticModel) as model:
                server_thread = threading.Thread(target=model.serve_forever, daemon=True)
                server_thread.start()
                (codex_home / "config.toml").write_text(
                    'model = "synthetic-model"\n'
                    'model_provider = "isolated_fixture"\n'
                    'approval_policy = "never"\n'
                    'sandbox_mode = "read-only"\n'
                    '[model_providers.isolated_fixture]\n'
                    'name = "Isolated fixture"\n'
                    'base_url = "http://127.0.0.1:%d/v1"\n'
                    'wire_api = "responses"\n'
                    'requires_openai_auth = false\n'
                    'supports_websockets = false\n'
                    'request_max_retries = 0\n'
                    'stream_max_retries = 0\n'
                    '[analytics]\n'
                    'enabled = false\n' % model.server_port,
                    encoding="utf-8")
                rpc = _AppServer(binary, codex_home, source)
                try:
                    rpc.call("initialize", clientInfo={"name": "vault-proof", "version": "1.0"},
                             capabilities={"experimentalApi": True})
                    rpc.send({"method": "initialized"})
                    parent_id = rpc.call("thread/start", historyMode="paginated")["thread"]["id"]
                    rpc.turn(parent_id, "Synthetic pre-fork setup")
                    fork_point = rpc.turn(parent_id, "inherited-vault-marker-qzmx")
                    child_id = rpc.call("thread/fork", threadId=parent_id,
                                        lastTurnId=fork_point, excludeTurns=True)["thread"]["id"]
                    rpc.turn(child_id, "child-local-vault-marker-qzmx")
                    rpc.call("thread/archive", threadId=parent_id)
                finally:
                    rpc.close()
                    model.shutdown()
                    server_thread.join(timeout=2)

            marker = b"inherited-vault-marker-qzmx"
            original_matches = search(str(source), marker.decode())
            self.assertTrue(any(match.collection == "paginated" and
                                match.transcript == child_id + ".jsonl"
                                for match in original_matches))
            database = codex_home / "thread_history_1.sqlite"
            with sqlite3.connect("file:%s?mode=ro" % database, uri=True) as connection:
                projected = connection.execute(
                    "SELECT COUNT(*) FROM thread_items WHERE instr(item_json, ?) > 0",
                    (marker.decode(),)).fetchone()[0]
            self.assertGreater(projected, 0)
            # Simulate a rollout rewrite in this disposable source only. Keep
            # every byte offset and ordinal intact so the real Codex-generated
            # history_base remains valid while the database alone keeps text.
            for folder in (codex_home / "sessions", codex_home / "archived_sessions"):
                if folder.exists():
                    for rollout in folder.rglob("*.jsonl"):
                        contents = rollout.read_bytes()
                        if marker in contents:
                            rollout.write_bytes(contents.replace(marker, b"x" * len(marker)))
            self.assertFalse(any(
                marker in rollout.read_bytes()
                for folder in (codex_home / "sessions", codex_home / "archived_sessions")
                if folder.exists() for rollout in folder.rglob("*.jsonl")))
            inherited = search(str(source), marker.decode())
            child = [match for match in inherited if
                     match.collection == "paginated" and
                     match.transcript == child_id + ".jsonl"]
            self.assertEqual(len(child), 1)
            page, _ = read_thread_page(str(source), "paginated", child_id + ".jsonl",
                                       cursor=child[0].cursor,
                                       expected_query="inherited-vault-marker-qzmx",
                                       live_paginated=True)
            self.assertTrue(any("inherited-vault-marker-qzmx" in entry.text
                                for entry in page.entries))

            original_database = database.read_bytes()
            helper = os.environ.get("CODEX_MIGRATE_TEST_VAULT_HELPER")
            if not helper:
                helper = str(home / "CodexVaultCrypto")
                subprocess.run([
                    "xcrun", "swiftc", "-parse-as-library", "-O", "-D",
                    "CODEX_VAULT_TEST_LEGACY_KEYCHAIN", "-target",
                    platform.machine() + "-apple-macos13.0",
                    "desktop/CodexVaultCrypto.swift", "-o", helper,
                ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            vault = home / "vault"
            try:
                saved = backup(str(source), str(vault), crypto_helper=helper)
                self.assertIsNotNone(saved.recovery_key)
                self.assertEqual(database.read_bytes(), original_database)
                self.assertFalse(any(marker in path.read_bytes()
                                     for path in vault.rglob("*") if path.is_file()))
                key_id = json.loads((vault / "vault.json").read_text())["key_id"]
                subprocess.run([helper, "delete-key", "--key-id", key_id],
                               check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                import_recovery_key(str(vault), saved.recovery_key, crypto_helper=helper)
                restored_home = home / "restored"
                restored_home.mkdir()
                restore_snapshot(str(source), str(vault), str(restored_home / ".codex"),
                                 crypto_helper=helper)
                catalog = snapshot_catalog(str(vault), crypto_helper=helper)
                recovered = search(str(restored_home), marker.decode(), catalog=catalog)
                recovered_child = [match for match in recovered if
                                   match.collection == "paginated" and
                                   match.transcript == child_id + ".jsonl"]
                self.assertEqual(len(recovered_child), 1)
                recovered_page, _ = read_thread_page(
                    str(restored_home), "paginated", child_id + ".jsonl",
                    cursor=recovered_child[0].cursor, expected_query=marker.decode())
                self.assertTrue(any(marker.decode() in entry.text
                                    for entry in recovered_page.entries))
                exported = b"".join(markdown_chunks(
                    str(restored_home), "paginated", child_id + ".jsonl",
                    catalog=catalog))
                self.assertIn(marker, exported)
            finally:
                if (vault / "vault.json").exists():
                    key_id = json.loads((vault / "vault.json").read_text())["key_id"]
                    subprocess.run([helper, "delete-key", "--key-id", key_id],
                                   check=True, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
