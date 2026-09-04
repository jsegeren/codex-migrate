import json
from html.parser import HTMLParser
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from codex_migrate.dashboard import HTML
from codex_migrate.setup import SETUP_HTML
from codex_migrate.state import StateStore
from codex_migrate.support import diagnostic_report, SUPPORT_URL, SUPPORT_EMAIL, HISTORY_LIMIT, _build_identity


class SupportTests(unittest.TestCase):
    def test_packaged_build_identity_exports_only_validated_fields(self):
        with tempfile.TemporaryDirectory() as root:
            engine = Path(root) / "engine" / "codex-migrate-engine"
            metadata = Path(root) / "build-info.json"
            metadata.write_text(json.dumps({"source_revision": "a" * 40, "bundle_version": "1",
                                            "build_mode": "local-test", "private": "/Users/private"}))
            with patch("codex_migrate.support.sys.frozen", True, create=True), \
                 patch("codex_migrate.support.sys.executable", str(engine)):
                result = _build_identity()
                self.assertEqual(result["source_revision"], "a" * 40)
                self.assertEqual(result["mode"], "local-test")
                self.assertNotIn("private", json.dumps(result))
                metadata.write_text('{"source_revision":"/Users/private","bundle_version":"secret","mode":"secret"}')
                self.assertEqual(_build_identity(), {"source_revision": None, "bundle_version": None, "mode": "unknown"})

    def test_report_is_allowlisted_even_when_nested_values_are_hostile(self):
        secret = "PRIVATE_SENTINEL /Users/private/project bearer-credential"
        state = {"status": secret, "phase": secret, "error": secret,
                 "config": {"target": secret}, "current_item": secret,
                 "pending_backup": secret, "migration_mode": secret,
                 "receipt": {"auth_preserved": secret, "backup": secret},
                 "bytes_staged": secret, "bytes_total": True,
                 "support_history": [{"at": secret, "phase": secret, "status": secret,
                                      "failure_category": secret, "extra": secret}]}
        with patch("codex_migrate.support.platform.mac_ver", return_value=(secret, (), "")), \
             patch("codex_migrate.support.platform.machine", return_value=secret):
            report = diagnostic_report(state)
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(report))
        self.assertNotIn("/Users", json.dumps(report))
        self.assertEqual(report["current"]["status"], "unknown")
        self.assertIsNone(report["verification"]["auth_preserved"])
        self.assertIsNone(report["sizes_bytes"]["bytes_total"])
        self.assertTrue(report["pending_backup_recorded"])

    def test_transition_history_is_persistent_bounded_and_not_progress_spam(self):
        with tempfile.TemporaryDirectory() as root:
            state = StateStore(root)
            state.update(status="running", phase="staging")
            for size in range(100):
                state.update(bytes_staged=size)
            self.assertEqual(len(state.read()["support_history"]), 1)
            for index in range(90):
                state.update(status="paused" if index % 2 else "running")
            events = diagnostic_report(StateStore(root).read())["recent_events"]
            self.assertEqual(len(events), HISTORY_LIMIT)
            self.assertEqual(events[-1]["status"], "paused")

    def test_log_includes_failure_and_recovery_without_raw_message(self):
        with tempfile.TemporaryDirectory() as root:
            state = StateStore(root)
            state.update(status="failed", phase="installing",
                         error="Workspace verification failed for /Users/private/secret")
            state.update(status="running", phase="staging", error=None)
            report = diagnostic_report(state.read())
            self.assertEqual(report["recent_events"][0]["failure_category"], "verification")
            self.assertEqual(report["recent_events"][1]["failure_category"], "none")
            self.assertNotIn("/Users/private", json.dumps(report))

    def test_empty_legacy_or_malformed_history_has_honest_unknowns(self):
        for state in ({}, {"support_history": "not a list"}, None):
            report = diagnostic_report(state)
            self.assertEqual(report["recent_events"], [])
            self.assertIsNone(report["verification"]["backup_verified"])
        state = {"support_history": [None] * 100 + [{"status": "running", "phase": "staging"}]}
        self.assertEqual(len(diagnostic_report(state)["recent_events"]), 1)

    def test_recovery_check_events_include_only_fixed_status_not_private_report(self):
        with tempfile.TemporaryDirectory() as root:
            state = StateStore(root)
            state.update(recovery={"status": "checking"})
            state.update(recovery={"status": "backup_verified", "backup": "/Users/PRIVATE",
                                   "items": [{"original": "PRIVATE"}], "backup_digest": "PRIVATE"})
            report = diagnostic_report(state.read())
            self.assertEqual(report["current"]["recovery_status"], "backup_verified")
            self.assertEqual([e["recovery_status"] for e in report["recent_events"]], ["checking", "backup_verified"])
            self.assertNotIn("PRIVATE", json.dumps(report))

    def test_help_is_available_before_configuration_and_during_failure(self):
        for document in (HTML, SETUP_HTML):
            self.assertIn('href="#migration-help"', document)
            self.assertIn('id="prepare-support"', document)
            self.assertIn('id="support-report" readonly', document)
            self.assertIn('id="support-status" role="status"', document)
            self.assertIn("X-Codex-Migrate-Token", document)
            self.assertIn("reviewedSupportReport", document)
            self.assertNotIn("__SUPPORT", document)
        self.assertIn('id="migration-events"', HTML)

    def test_restoration_events_never_export_bound_private_evidence(self):
        with tempfile.TemporaryDirectory() as root:
            state = StateStore(root)
            for phase, status in (("restoring", "restoring"), ("recovery_required", "restore_unconfirmed"), ("restored", "restore_verified")):
                state.update(phase=phase, recovery={"status": status, "backup": "PRIVATE"},
                             recovery_attempt={"reference": "PRIVATE", "inspection": "PRIVATE", "proof": "PRIVATE"})
            report = diagnostic_report(state.read())
            self.assertEqual(report["current"]["recovery_status"], "restore_verified")
            self.assertEqual([e["phase"] for e in report["recent_events"]], ["restoring", "recovery_required", "restored"])
            self.assertNotIn("PRIVATE", json.dumps(report))

    def test_optional_details_are_collapsed_but_safety_status_stays_visible(self):
        class Visibility(HTMLParser):
            def __init__(self):
                super().__init__()
                self.depth = 0
                self.inside = {}
            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == "details":
                    self.depth += 1
                    if "open" in attrs:
                        raise AssertionError("Help disclosures should start collapsed")
                if "id" in attrs:
                    self.inside[attrs["id"]] = self.depth > 0
            def handle_endtag(self, tag):
                if tag == "details":
                    self.depth -= 1
        dashboard = Visibility()
        dashboard.feed(HTML)
        for name in ("status", "message", "route", "backup-space", "backup-location", "error", "prepare-support"):
            self.assertFalse(dashboard.inside[name], name)
        for name in ("workspace-list", "skill-explanation", "migration-events"):
            self.assertTrue(dashboard.inside[name], name)
        setup = Visibility()
        setup.feed(SETUP_HTML)
        self.assertTrue(setup.inside["identity"])
        self.assertFalse(setup.inside["apply"])
        self.assertIn("it does not merge existing work", SETUP_HTML)

    def test_email_draft_is_fixed_and_does_not_send_or_attach_automatically(self):
        url = urlparse(SUPPORT_URL)
        self.assertEqual(url.scheme, "mailto")
        self.assertEqual(url.path, SUPPORT_EMAIL)
        self.assertNotIn("+", url.query)
        self.assertIn("subject=Codex%20Migrate%20support", url.query)
        self.assertIn("%0D%0A", url.query)
        fields = parse_qs(url.query)
        self.assertEqual(set(fields), {"subject", "body"})
        self.assertIn("attach", fields["body"][0])
        native = (Path(__file__).parents[1] / "desktop/CodexMigrate.swift").read_text()
        self.assertIn(SUPPORT_EMAIL, native)
        self.assertIn('Link("Help / Email support"', native)

    def test_corrupt_or_missing_state_does_not_become_a_fresh_migration(self):
        for payload in ("not json", "[]", "null", '{"error":"PRIVATE"}'):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as root:
                state = StateStore(root)
                state.path.write_text(payload)
                with self.assertRaisesRegex(RuntimeError, "contact"):
                    state.update(status="running")
                self.assertEqual(state.path.read_text(), payload)
        with tempfile.TemporaryDirectory() as root:
            state = StateStore(root)
            state.token()
            state.path.unlink()
            with self.assertRaises(RuntimeError):
                state.read()
            with self.assertRaises(RuntimeError):
                StateStore(root)
            self.assertFalse(state.path.exists())

    def test_state_link_cannot_be_read_or_overwritten(self):
        with tempfile.TemporaryDirectory() as root:
            state = StateStore(root)
            other = Path(root) / "other.json"
            other.write_text('{"status":"running","secret":"PRIVATE"}')
            state.path.unlink()
            state.path.symlink_to(other)
            with self.assertRaises(RuntimeError):
                state.read()
            with self.assertRaises(RuntimeError):
                StateStore(root)
            self.assertIn("PRIVATE", other.read_text())


if __name__ == "__main__":
    unittest.main()
