import json
from dataclasses import replace
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import tempfile
import threading
import unittest

from codex_migrate.config import MigrationConfig
from codex_migrate.dashboard import Dashboard
from codex_migrate.dashboard import HTML
from codex_migrate.migration import MigrationEngine
from codex_migrate.state import StateStore


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        state_root = self.temporary.name + "/state"
        config = MigrationConfig(
            target="person@host.local",
            source_home=self.temporary.name,
            target_home="/Users/person",
            state_dir=state_root,
        ).validate()
        state = StateStore(state_root)
        self.dashboard = Dashboard(MigrationEngine(config, state), state, port=0)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.dashboard._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.dashboard.close()
        self.temporary.cleanup()

    def request(self, token=None):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        headers = {"X-Codex-Migrate-Token": token} if token else {}
        connection.request("GET", "/api/status", headers=headers)
        response = connection.getresponse()
        body = json.loads(response.read())
        connection.close()
        return response.status, body

    def post(self, payload, token=None):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Codex-Migrate-Token"] = token
        connection.request("POST", "/api/action", body=json.dumps(payload), headers=headers)
        response = connection.getresponse()
        body = json.loads(response.read())
        connection.close()
        return response.status, body

    def test_status_requires_token(self):
        status, _ = self.request()
        self.assertEqual(status, 403)

    def test_backup_protection_is_visible_and_receipt_not_assumed(self):
        self.assertIn('id="backup-safety"', HTML)
        self.assertIn('No verified backup recorded', HTML)
        self.assertIn('r.backup_verified', HTML)
        self.assertIn('Blocked — not enough space', HTML)
        self.assertIn('not disk failure', HTML)
        self.assertIn('verification.json', HTML)

    def test_status_accepts_exact_token(self):
        status, body = self.request(self.dashboard.token)
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "idle")

    def test_refuses_public_bind(self):
        with self.assertRaises(ValueError):
            Dashboard(self.dashboard.engine, self.dashboard.state, host="0.0.0.0")

    def test_finalize_remains_available_while_waiting_for_codex_to_close(self):
        self.assertIn('s.status==="waiting"', HTML)
        self.assertIn('"close_source_codex","close_target_codex"', HTML)

    def test_control_token_is_removed_from_visible_url(self):
        self.assertIn('history.replaceState(null,"",location.pathname)', HTML)

    def test_controls_are_disabled_until_authenticated_state_loads(self):
        for control in ("inspect", "start", "pause", "resume", "finalize", "cancel"):
            self.assertIn('id="%s" disabled' % control, HTML)

    def test_dry_run_cannot_resume_a_mutating_migration(self):
        self.assertIn('$("resume").disabled=!s.apply||', HTML)

    def test_finalize_requires_explicit_server_side_confirmation(self):
        self.dashboard.engine.config = replace(self.dashboard.engine.config, apply=True)
        self.dashboard.state.update(
            status="ready_to_finalize",
            phase="ready_to_finalize",
            staging_complete=True,
        )
        status, body = self.post(
            {"action": "finalize"},
            token=self.dashboard.token,
        )
        self.assertEqual(status, 400)
        self.assertIn("explicit confirmation", body["error"])

    def test_read_only_rejects_mutation_before_starting_worker(self):
        for action in ("start", "resume", "finalize"):
            with self.subTest(action=action):
                status, body = self.post({"action": action, "confirmed": True}, self.dashboard.token)
                self.assertEqual(status, 400)
                self.assertIn("Changes are disabled", body["error"])
                self.assertIsNone(self.dashboard.engine._thread)
                self.assertEqual(self.dashboard.state.read()["status"], "idle")


if __name__ == "__main__":
    unittest.main()
