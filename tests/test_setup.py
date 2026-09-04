import json
from http.client import HTTPConnection
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from codex_migrate.dashboard import LoopbackHTTPServer
from codex_migrate.setup import SetupDashboard, SETUP_HTML


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name).resolve()
        (self.home / "Git").mkdir()
        self.helper = SetupDashboard(str(self.home), str(self.home / "state"))
        self.server = LoopbackHTTPServer(("127.0.0.1", 0), self.helper._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.helper.close()
        self.temporary.cleanup()

    def request(self, path, payload=None, authorized=True, extra_headers=None):
        headers = {"Content-Type": "application/json"}
        if authorized:
            headers["X-Codex-Migrate-Token"] = self.helper.token
        headers.update(extra_headers or {})
        client = HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        client.request("POST" if payload is not None else "GET", path,
                       json.dumps(payload) if payload is not None else None, headers)
        response = client.getresponse()
        body = response.read().decode()
        result = json.loads(body) if "application/json" in response.getheader("Content-Type", "") else body
        client.close()
        return response.status, result

    def config(self, **extra):
        return dict(target="user@fixture.local", target_home="/Users/user",
                    workspace_roots=[str(self.home / "Git")], **extra)

    def test_support_report_works_before_setup_and_requires_local_token(self):
        code, report = self.request("/api/support-report")
        self.assertEqual(code, 200)
        self.assertEqual(report["current"]["status"], "idle")
        self.assertNotIn(str(self.home), json.dumps(report))
        self.assertEqual(self.request("/api/support-report", authorized=False)[0], 403)
        self.assertEqual(self.request("/api/support-report", extra_headers={"Origin": "https://example.com"})[0], 403)

    def test_setup_shell_exposes_no_local_paths_or_token(self):
        code, body = self.request("/", authorized=False)
        self.assertEqual(code, 200)
        self.assertIn("Choose folders on this Mac", body)
        self.assertNotIn(str(self.home), body)
        self.assertNotIn(self.helper.token, body)

    def test_private_setup_and_picker_require_token(self):
        for path, data in (("/api/setup", None), ("/api/setup", self.config()),
                           ("/api/folders", {}), ("/api/suggestions", {})):
            self.assertEqual(self.request(path, data, authorized=False)[0], 403)

    def test_rejects_foreign_origin_and_rebinding_host(self):
        for headers in ({"Origin": "https://evil.invalid"}, {"Host": "evil.invalid"}):
            self.assertEqual(self.request("/api/setup", self.config(), extra_headers=headers)[0], 403)
        self.assertIsNone(self.helper.engine)

    def test_configure_attaches_real_engine_without_remote_calls(self):
        with patch("codex_migrate.transport.SSHTransport.run_remote", side_effect=AssertionError("Unexpected SSH")):
            self.assertEqual(self.request("/api/setup", self.config())[0], 200)
            code, state = self.request("/api/status")
        self.assertEqual(code, 200)
        self.assertEqual(state["status"], "idle")
        self.assertFalse(state["apply"])
        self.assertIn("Backup required before replacement", self.request("/migration")[1])
        self.assertEqual(self.request("/api/action", {"action": "start"})[0], 400)

    def test_reconfiguration_cannot_change_active_scope(self):
        self.request("/api/setup", self.config())
        self.assertEqual(self.request("/api/setup", self.config(apply=True))[0], 400)
        self.assertFalse(self.helper.engine.config.apply)

    def test_saved_setup_excludes_permission_key_paths_and_tokens(self):
        self.request("/api/setup", self.config(apply=True, identity_file=str(self.home / "private-key")))
        saved = self.helper.registry.read()["saved"]
        self.assertEqual(set(saved), {"target", "target_home", "workspace_roots"})
        self.assertNotIn("private-key", self.helper.registry.path.read_text())
        self.assertEqual(self.helper.registry.path.stat().st_mode & 0o777, 0o600)

    def test_resume_uses_same_state_without_reusing_apply_permission(self):
        self.request("/api/setup", self.config(apply=True))
        self.helper.state.update(status="cancelled", bytes_staged=12345)
        original = self.helper.state.root
        saved = self.helper.registry.read()["saved"]
        self.server.shutdown()
        self.server.server_close()
        self.helper.close()
        self.helper = SetupDashboard(str(self.home), str(self.home / "state"))
        self.helper.configure(saved)
        self.assertEqual(self.helper.state.root, original)
        self.assertEqual(self.helper.state.read()["bytes_staged"], 12345)
        self.assertFalse(self.helper.engine.config.apply)

    def test_shutdown_blocks_running_or_paused_and_closes_action_gate(self):
        self.request("/api/setup", self.config())
        for status in ("running", "paused"):
            self.helper.state.update(status=status)
            self.assertFalse(self.helper.can_shutdown())
        self.helper.state.update(status="idle")
        self.assertTrue(self.helper.can_shutdown())
        self.assertEqual(self.request("/api/action", {"action": "inspect"})[0], 409)

    def test_shutdown_does_not_race_request(self):
        with self.helper._request_lock:
            self.assertFalse(self.helper.can_shutdown())

    def test_suggestions_only_use_existing_common_folders(self):
        code, result = self.request("/api/suggestions", {})
        self.assertEqual(code, 200)
        self.assertEqual(result["paths"], [str(self.home / "Git")])

    def test_stale_tab_cannot_open_picker_after_configuration(self):
        self.request("/api/setup", self.config())
        with patch.object(self.helper, "choose_folders", side_effect=AssertionError("Picker opened")):
            self.assertEqual(self.request("/api/folders", {})[0], 400)
            self.assertEqual(self.request("/api/suggestions", {})[0], 400)

    def test_reverse_order_roots_have_same_engine_config_as_saved_setup(self):
        (self.home / "Projects").mkdir()
        payload = self.config()
        payload["workspace_roots"] = [str(self.home / "Projects"), str(self.home / "Git")]
        self.request("/api/setup", payload)
        self.assertEqual(self.helper.engine.config.workspace_roots,
                         self.helper.registry.read()["saved"]["workspace_roots"])

    def test_inspection_does_not_block_stop_request(self):
        self.request("/api/setup", self.config())
        entered, release = threading.Event(), threading.Event()
        def inspect():
            entered.set()
            release.wait(3)
            self.helper.engine._inspection_checkpoint()
        try:
            with patch.object(self.helper.engine, "preflight", side_effect=inspect):
                self.assertEqual(self.request("/api/action", {"action": "inspect"})[0], 202)
                self.assertTrue(entered.wait(1))
                self.assertEqual(self.request("/api/status")[1]["phase"], "inspecting")
                self.assertEqual(self.request("/api/action", {"action": "cancel"})[0], 202)
        finally:
            release.set()
            self.helper.engine._thread.join(timeout=3)
        self.assertEqual(self.helper.state.read()["status"], "cancelled")

    def test_invalid_paths_and_types_fail_before_attaching(self):
        payloads = [[], self.config(apply="yes"), {**self.config(), "workspace_roots": ["/etc"]},
                    {**self.config(), "target": "user@host;touch /tmp/no"},
                    {**self.config(), "workspace_roots": [str(self.home / "state")]},
                    self.config(arbitrary="no")]
        for payload in payloads:
            self.assertEqual(self.request("/api/setup", payload)[0], 400)
            self.assertIsNone(self.helper.engine)

    def test_folder_picker_uses_fixed_script_and_rejects_linebreak_names(self):
        with patch("codex_migrate.setup.platform.system", return_value="Darwin"), \
             patch("codex_migrate.setup.subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = json.dumps([str(self.home / "Git")])
            self.assertEqual(self.helper.choose_folders(), [str(self.home / "Git")])
            self.assertEqual(run.call_args.args[0][:3], ["/usr/bin/osascript", "-l", "JavaScript"])
            run.return_value.stdout = json.dumps(["/Users/source/new\nline"])
            with self.assertRaises(RuntimeError):
                self.helper.choose_folders()

    def test_browser_refresh_keeps_tab_scoped_token_and_apply_defaults_off(self):
        self.assertIn("sessionStorage", SETUP_HTML)
        self.assertNotIn("localStorage", SETUP_HTML)
        self.assertIn('$("apply").checked=false', SETUP_HTML)
        self.assertIn("A key stored inside a selected workspace is copied", SETUP_HTML)

    def test_skills_mode_attaches_without_ssh_and_preserves_read_only_guard(self):
        with patch("codex_migrate.transport.SSHTransport.run_remote", side_effect=AssertionError("Unexpected SSH")):
            self.assertEqual(self.request("/api/setup", self.config(mode="skills", components=["personal-skills"]))[0], 200)
            code, state = self.request("/api/status")
        self.assertEqual(code, 200)
        self.assertEqual(state["migration_mode"], "skills")
        self.assertEqual(state["components"], ["personal-skills"])
        self.assertFalse(state["apply"])
        self.assertIsNone(state["compatibility_command"])
        self.assertEqual(self.request("/api/action", {"action": "start"})[0], 400)

    def test_skills_mode_restores_scope_and_separate_staging_without_apply(self):
        self.helper.configure(self.config(mode="skills", components=["workspace-skills", "personal-skills"], apply=True))
        original_root = self.helper.state.root
        original_staging = self.helper.engine.config.target_staging
        saved = self.helper.registry.read()["saved"]
        self.assertEqual(saved["components"], ["personal-skills", "workspace-skills"])
        self.assertNotIn("apply", saved)
        self.assertNotEqual(original_staging, "/Users/user/Codex-Migrate-Staging")
        self.server.shutdown()
        self.server.server_close()
        self.helper.close()
        self.helper = SetupDashboard(str(self.home), str(self.home / "state"))
        self.helper.configure(saved)
        self.assertEqual(self.helper.state.root, original_root)
        self.assertEqual(self.helper.engine.config.target_staging, original_staging)
        self.assertFalse(self.helper.engine.config.apply)

    def test_invalid_skills_modes_do_not_attach_or_save(self):
        for extra in ({"mode": "skills"}, {"mode": "unknown"},
                      {"mode": "skills", "components": ["everything"]},
                      {"mode": "skills", "components": "personal-skills"},
                      {"mode": "full", "components": ["personal-skills"]}):
            self.assertEqual(self.request("/api/setup", self.config(**extra))[0], 400)
            self.assertIsNone(self.helper.engine)
            self.assertIsNone(self.helper.registry.read().get("saved"))

    def test_skills_inspection_is_async_and_stoppable(self):
        self.request("/api/setup", self.config(mode="skills", components=["personal-skills"]))
        entered, release = threading.Event(), threading.Event()
        def inspect():
            entered.set()
            release.wait(3)
            self.helper.engine._inspection_checkpoint()
        try:
            with patch.object(self.helper.engine, "preflight", side_effect=inspect):
                self.assertEqual(self.request("/api/action", {"action": "inspect"})[0], 202)
                self.assertTrue(entered.wait(1))
                self.assertEqual(self.request("/api/action", {"action": "cancel"})[0], 202)
        finally:
            release.set()
            self.helper.engine._thread.join(timeout=3)
        self.assertEqual(self.helper.state.read()["status"], "cancelled")
