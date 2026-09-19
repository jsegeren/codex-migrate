import json
from http.client import HTTPConnection
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from codex_migrate.dashboard import LoopbackHTTPServer
from codex_migrate.errors import MigrationError
from codex_migrate.setup import SetupDashboard, SETUP_HTML
from codex_migrate.vault_backup import BackupPlan, BackupResult
from codex_migrate.vault_install import InstallResult, ThreadInstallResult
from codex_migrate.vault_recovery import RestoreResult, SnapshotInfo
from codex_migrate.vault_schedule import SchedulePlan


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

    def test_vault_shell_is_content_free_and_private_apis_require_token(self):
        transcript = self.home / ".codex/sessions/2026/09/thread.jsonl"
        transcript.parent.mkdir(parents=True)
        transcript.write_text(json.dumps({
            "timestamp": "2026-09-17T10:00:00Z",
            "payload": {"message": {"role": "user", "content": "PRIVATE VAULT FIXTURE"}},
        }) + "\n", encoding="utf-8")
        code, shell = self.request("/vault", authorized=False)
        self.assertEqual(code, 200)
        self.assertIn("Codex Vault", shell)
        self.assertIn("Print / Save PDF", shell)
        self.assertIn("Share thread", shell)
        self.assertIn("Create encrypted backup", shell)
        self.assertIn("Save this recovery key", shell)
        self.assertIn("Automatic backup", shell)
        self.assertIn("Turn on daily backup", shell)
        self.assertIn('id="backup-frequency-daily" type="radio" name="backup-frequency" value="daily" checked', shell)
        self.assertIn("Back up automatically every day", shell)
        self.assertIn("Back up only when I ask", shell)
        self.assertIn("Create backup + turn on daily backup", shell)
        self.assertIn("pendingAutomaticBackup", shell)
        self.assertIn("enableRequestedSchedule", shell)
        self.assertIn("Recover a backup", shell)
        self.assertIn("Open this backup", shell)
        self.assertIn("Restore this conversation into Codex", shell)
        self.assertIn("never overwrites or merges", shell)
        self.assertIn("Replace conversation history", shell)
        self.assertIn("installation identity stay unchanged", shell)
        self.assertNotIn("PRIVATE VAULT FIXTURE", shell)
        for path in ("/api/vault/summary", "/api/vault/search?q=PRIVATE",
                     "/api/vault/thread?collection=active&transcript=2026/09/thread.jsonl",
                     "/api/vault/export?collection=active&transcript=2026/09/thread.jsonl",
                     "/api/vault/backup-status", "/api/vault/schedule",
                     "/api/vault/restore-status",
                     "/api/vault/install-status",
                     "/api/vault/browse-status",
                     "/api/vault/thread-install-status",
                     "/api/vault/snapshots?vault=/private/tmp/vault"):
            self.assertEqual(self.request(path, authorized=False)[0], 403)
        for path in ("/api/vault/folder", "/api/vault/backup",
                     "/api/vault/recovery-saved", "/api/vault/schedule",
                     "/api/vault/schedule-remove", "/api/vault/restore-folder",
                     "/api/vault/restore", "/api/vault/install",
                     "/api/vault/install-recover", "/api/vault/browse",
                     "/api/vault/install-thread"):
            self.assertEqual(self.request(path, {}, authorized=False)[0], 403)

    def test_vault_backup_can_be_opened_searched_and_selected_thread_installed(self):
        (self.home / ".codex").mkdir()
        vault = str(self.home / "vault")
        snapshot = "11111111-1111-4111-8111-111111111111"

        def restored(_home, _vault, output, *, snapshot, crypto_helper=None):
            root = Path(output)
            (root / "sessions/2026/09").mkdir(parents=True)
            content = json.dumps({
                "timestamp": "2026-09-18T10:00:00Z",
                "payload": {"message": {"role": "user", "content": "RECOVER ME"}},
            }) + "\n"
            (root / "sessions/2026/09/recovered.jsonl").write_text(content)
            return RestoreResult(
                vault=vault, snapshot_id=snapshot, transcript_files=1,
                transcript_bytes=len(content.encode()), output=str(root),
            )

        installed = ThreadInstallResult(
            vault=vault, snapshot_id=snapshot, collection="active",
            transcript="2026/09/recovered.jsonl", status="installed",
            target="sessions/2026/09/recovered.jsonl", transcript_bytes=10,
            receipt=str(self.home / "receipt.json"), applied=True,
        )
        with patch("codex_migrate.setup.restore_vault_snapshot",
                   side_effect=restored), patch(
                "codex_migrate.setup.persistent_install_status",
                return_value={"status": "idle"}), patch(
                "codex_migrate.setup.install_vault_thread",
                return_value=installed) as install:
            code, opening = self.request("/api/vault/browse", {
                "vault": vault, "snapshot": snapshot, "apply": True,
            })
            self.assertEqual(code, 202)
            self.assertIn(opening["status"], ("running", "ready"))
            self.helper._browse_thread.join(timeout=3)
            status = self.request("/api/vault/browse-status")[1]
            self.assertEqual(status["status"], "ready")

            code, results = self.request(
                "/api/vault/search?q=RECOVER&limit=50&source=backup")
            self.assertEqual(code, 200)
            self.assertEqual(len(results["results"]), 1)
            item = results["results"][0]
            self.assertEqual(item["transcript"], "2026/09/recovered.jsonl")
            code, thread = self.request(
                "/api/vault/thread?collection=active&"
                "transcript=2026%2F09%2Frecovered.jsonl&source=backup")
            self.assertEqual(code, 200)
            self.assertEqual(thread["entries"][0]["text"], "RECOVER ME")

            code, running = self.request("/api/vault/install-thread", {
                "collection": "active", "transcript": item["transcript"],
                "apply": True,
            })
            self.assertEqual(code, 202)
            self.assertIn(running["status"], ("running", "installed"))
            self.helper._thread_install_thread.join(timeout=3)
            result = self.request("/api/vault/thread-install-status")[1]
            self.assertEqual(result["status"], "installed")
            install.assert_called_once_with(
                str(self.home), vault, "active", "2026/09/recovered.jsonl",
                snapshot=snapshot,
            )

    def test_vault_selected_thread_install_requires_open_backup_and_confirmation(self):
        (self.home / ".codex").mkdir()
        self.assertEqual(self.request("/api/vault/install-thread", {
            "collection": "active", "transcript": "thread.jsonl",
            "apply": False,
        })[0], 400)
        code, body = self.request("/api/vault/install-thread", {
            "collection": "active", "transcript": "thread.jsonl",
            "apply": True,
        })
        self.assertEqual(code, 400)
        self.assertIn("Open a verified Vault backup", body["error"])

    def test_vault_selected_thread_unverified_rollback_reports_attention(self):
        (self.home / ".codex").mkdir()
        vault = str(self.home / "vault")
        snapshot = "11111111-1111-4111-8111-111111111111"
        self.helper._browse_status = {
            "status": "ready", "vault": vault, "snapshot_id": snapshot,
        }
        with patch("codex_migrate.setup.persistent_install_status",
                   return_value={"status": "idle"}), patch(
                "codex_migrate.setup.install_vault_thread",
                side_effect=MigrationError(
                    "Selected recovery stopped and automatic rollback could not be verified. "
                    "PRIVATE CUSTOMER CONTENT")):
            code, _ = self.request("/api/vault/install-thread", {
                "collection": "active", "transcript": "thread.jsonl",
                "apply": True,
            })
            self.assertEqual(code, 202)
            self.helper._thread_install_thread.join(timeout=3)
        status = self.request("/api/vault/thread-install-status")[1]
        self.assertEqual(status["status"], "needs_attention")
        self.assertIn("Keep Codex closed", status["error"])
        self.assertNotIn("PRIVATE CUSTOMER CONTENT", json.dumps(status))

    def test_vault_install_runs_off_request_thread_and_uses_selected_snapshot(self):
        (self.home / ".codex").mkdir()
        vault = str(self.home / "vault")
        snapshot = "11111111-1111-4111-8111-111111111111"
        backup = str(self.home / "Codex-Vault-Restore-Backup-fixture")
        completed = InstallResult(
            vault=vault, snapshot_id=snapshot, transcript_files=2,
            transcript_bytes=100, backup=backup,
        )
        with patch("codex_migrate.setup.persistent_install_status",
                   return_value={"status": "idle"}), patch(
                "codex_migrate.setup.install_vault_snapshot",
                return_value=completed) as install:
            code, running = self.request("/api/vault/install", {
                "vault": vault, "snapshot": snapshot, "apply": True,
            })
            self.assertEqual(code, 202)
            self.assertIn(running["status"], ("running", "completed"))
            self.helper._install_thread.join(timeout=3)
            code, status = self.request("/api/vault/install-status")
            self.assertEqual(code, 200)
            self.assertEqual(status["status"], "completed")
            self.assertEqual(status["backup"], backup)
            install.assert_called_once_with(
                str(self.home), vault, snapshot=snapshot)

    def test_vault_install_requires_confirmation_and_sanitizes_failure(self):
        (self.home / ".codex").mkdir()
        vault = str(self.home / "vault")
        self.assertEqual(self.request("/api/vault/install", {
            "vault": vault, "snapshot": "latest", "apply": False,
        })[0], 400)
        with patch("codex_migrate.setup.persistent_install_status",
                   return_value={"status": "idle"}), patch(
                "codex_migrate.setup.install_vault_snapshot",
                side_effect=RuntimeError("PRIVATE CUSTOMER CONTENT")):
            self.assertEqual(self.request("/api/vault/install", {
                "vault": vault, "snapshot": "latest", "apply": True,
            })[0], 202)
            self.helper._install_thread.join(timeout=3)
        status = self.request("/api/vault/install-status")[1]
        self.assertEqual(status["status"], "failed")
        self.assertNotIn("PRIVATE CUSTOMER CONTENT", json.dumps(status))

    def test_vault_install_recovery_requires_interrupted_journal(self):
        (self.home / ".codex").mkdir()
        with patch("codex_migrate.setup.persistent_install_status",
                   return_value={"status": "interrupted", "backup": "/safe/backup"}), patch(
                "codex_migrate.setup.recover_interrupted_install",
                return_value={"status": "rolled_back", "applied": True,
                              "backup": "/safe/backup"}) as recover:
            self.assertEqual(self.request(
                "/api/vault/install-recover", {"apply": False})[0], 400)
            code, running = self.request(
                "/api/vault/install-recover", {"apply": True})
            self.assertEqual(code, 202)
            self.assertIn(running["status"], ("rolling_back", "rolled_back"))
            self.helper._install_thread.join(timeout=3)
            self.assertEqual(
                self.request("/api/vault/install-status")[1]["status"],
                "rolled_back")
            recover.assert_called_once_with(str(self.home), apply=True)

    def test_backup_and_recovery_wait_for_active_vault_install(self):
        (self.home / ".codex").mkdir()
        vault = str(self.home / "vault")
        snapshot = "11111111-1111-4111-8111-111111111111"
        entered, release = threading.Event(), threading.Event()

        def wait_for_release(*_args, **_kwargs):
            entered.set()
            release.wait(3)
            return InstallResult(
                vault=vault, snapshot_id=snapshot, transcript_files=1,
                transcript_bytes=10,
                backup=str(self.home / "Codex-Vault-Restore-Backup-fixture"),
            )

        try:
            with patch("codex_migrate.setup.persistent_install_status",
                       return_value={"status": "idle"}), patch(
                    "codex_migrate.setup.install_vault_snapshot",
                    side_effect=wait_for_release), patch(
                    "codex_migrate.setup.plan_vault_backup") as plan:
                self.assertEqual(self.request("/api/vault/install", {
                    "vault": vault, "snapshot": snapshot, "apply": True,
                })[0], 202)
                self.assertTrue(entered.wait(1))
                code, body = self.request(
                    "/api/vault/backup", {"destination": vault, "apply": True})
                self.assertEqual(code, 400)
                self.assertIn("installation to finish", body["error"])
                plan.assert_not_called()
                code, body = self.request("/api/vault/restore", {
                    "vault": vault, "output": str(self.home / "recovered"),
                    "snapshot": snapshot, "apply": True,
                })
                self.assertEqual(code, 400)
                self.assertIn("installation to finish", body["error"])
        finally:
            release.set()
            if self.helper._install_thread:
                self.helper._install_thread.join(timeout=3)

    def test_vault_restore_runs_off_request_thread_and_never_changes_live_data(self):
        vault = str(self.home / "vault")
        output = str(self.home / "recovered")
        snapshot = "11111111-1111-4111-8111-111111111111"
        completed = RestoreResult(
            vault=vault, snapshot_id=snapshot, transcript_files=2,
            transcript_bytes=100, output=output,
        )
        with patch("codex_migrate.setup.restore_vault_snapshot",
                   return_value=completed) as restore:
            code, running = self.request("/api/vault/restore", {
                "vault": vault, "output": output, "snapshot": snapshot,
                "apply": True,
            })
            self.assertEqual(code, 202)
            self.assertIn(running["status"], ("running", "completed"))
            self.helper._restore_thread.join(timeout=3)
            code, status = self.request("/api/vault/restore-status")
            self.assertEqual(code, 200)
            self.assertEqual(status["status"], "completed")
            self.assertEqual(status["transcript_files"], 2)
            restore.assert_called_once_with(
                str(self.home), vault, output, snapshot=snapshot)

    def test_vault_restore_requires_explicit_apply_and_sanitizes_failure(self):
        vault = str(self.home / "vault")
        output = str(self.home / "recovered")
        code, body = self.request("/api/vault/restore", {
            "vault": vault, "output": output, "snapshot": "latest",
            "apply": False,
        })
        self.assertEqual(code, 400)
        self.assertIn("explicit confirmation", body["error"])
        code, body = self.request("/api/vault/restore", {
            "vault": vault, "output": output, "snapshot": "not-a-snapshot",
            "apply": True,
        })
        self.assertEqual(code, 400)
        self.assertIn("valid Vault snapshot", body["error"])
        with patch("codex_migrate.setup.restore_vault_snapshot",
                   side_effect=RuntimeError("PRIVATE CUSTOMER CONTENT")):
            self.assertEqual(self.request("/api/vault/restore", {
                "vault": vault, "output": output, "snapshot": "latest",
                "apply": True,
            })[0], 202)
            self.helper._restore_thread.join(timeout=3)
        status = self.request("/api/vault/restore-status")[1]
        self.assertEqual(status["status"], "failed")
        self.assertNotIn("PRIVATE CUSTOMER CONTENT", json.dumps(status))

    def test_vault_snapshot_history_is_bounded_and_content_free(self):
        vault = str(self.home / "vault")
        snapshot = SnapshotInfo(
            snapshot_id="11111111-1111-4111-8111-111111111111",
            created_at="2026-09-18T06:00:00+00:00", latest=True,
        )
        with patch("codex_migrate.setup.list_vault_snapshots",
                   return_value=[snapshot]) as listed:
            code, body = self.request(
                "/api/vault/snapshots?vault=" + vault)
        self.assertEqual(code, 200)
        self.assertEqual(body, {"snapshots": [snapshot.as_dict()]})
        listed.assert_called_once_with(vault, limit=100)
        self.assertNotIn("content", json.dumps(body).lower())

    def test_vault_backup_waits_for_active_restore(self):
        vault = str(self.home / "vault")
        output = str(self.home / "recovered")
        started = threading.Event()
        release = threading.Event()

        def slow_restore(*_args, **_kwargs):
            started.set()
            release.wait(timeout=3)
            return RestoreResult(
                vault=vault,
                snapshot_id="11111111-1111-4111-8111-111111111111",
                transcript_files=1,
                transcript_bytes=10, output=output,
            )

        try:
            with patch("codex_migrate.setup.restore_vault_snapshot", side_effect=slow_restore):
                self.assertEqual(self.request("/api/vault/restore", {
                    "vault": vault, "output": output, "snapshot": "latest",
                    "apply": True,
                })[0], 202)
                self.assertTrue(started.wait(timeout=1))
                code, body = self.request(
                    "/api/vault/backup", {"destination": vault, "apply": True})
                self.assertEqual(code, 400)
                self.assertIn("recovery to finish", body["error"])
        finally:
            release.set()
            if self.helper._restore_thread:
                self.helper._restore_thread.join(timeout=3)

    def test_vault_restore_folder_picker_is_fixed_and_cancel_is_non_destructive(self):
        completed = subprocess.CompletedProcess(
            [], 0, stdout=str(self.home / "Recovered") + "\n", stderr="")
        with patch("codex_migrate.setup.subprocess.run", return_value=completed) as run:
            code, result = self.request("/api/vault/restore-folder", {})
        self.assertEqual(code, 200)
        self.assertEqual(result["path"], str(self.home / "Recovered"))
        self.assertEqual(run.call_args.args[0][:3], ["/usr/bin/osascript", "-l", "JavaScript"])
        self.assertNotIn(str(self.home), run.call_args.args[0][-1])

        cancelled = subprocess.CompletedProcess([], 1, stdout="", stderr="User canceled. (-128)")
        with patch("codex_migrate.setup.subprocess.run", return_value=cancelled):
            self.assertEqual(self.request("/api/vault/restore-folder", {})[1]["path"], None)

    def test_vault_schedule_requires_explicit_apply_and_reports_state(self):
        destination = str(self.home / "vault")
        plan = SchedulePlan(destination, 24, applied=True)
        with patch("codex_migrate.setup.vault_schedule_status", return_value={
                "enabled": True, "healthy": True, "vault": destination,
                "interval_hours": 24,
        }) as status, patch(
                "codex_migrate.setup.install_vault_schedule", return_value=plan
        ) as install, patch(
                "codex_migrate.setup.remove_vault_schedule",
                return_value={"enabled": False},
        ) as remove:
            code, current = self.request("/api/vault/schedule")
            self.assertEqual(code, 200)
            self.assertTrue(current["healthy"])
            status.assert_called_once_with(str(self.home))

            self.assertEqual(self.request(
                "/api/vault/schedule",
                {"destination": destination, "interval_hours": 24},
            )[0], 400)
            install.assert_not_called()

            code, enabled = self.request(
                "/api/vault/schedule",
                {"destination": destination, "interval_hours": 24, "apply": True},
            )
            self.assertEqual(code, 200)
            self.assertTrue(enabled["enabled"])
            install.assert_called_once_with(
                str(self.home), destination, interval_hours=24)

            self.assertEqual(self.request(
                "/api/vault/schedule-remove", {"apply": False})[0], 400)
            remove.assert_not_called()
            code, disabled = self.request(
                "/api/vault/schedule-remove", {"apply": True})
            self.assertEqual(code, 200)
            self.assertFalse(disabled["enabled"])
            remove.assert_called_once_with(str(self.home))

    def test_vault_backup_runs_off_request_thread_and_recovery_key_is_acknowledged(self):
        destination = str(self.home / "vault")
        planned = BackupPlan(destination, 2, 100)
        completed = BackupResult(
            destination=destination, snapshot_id="fixture-snapshot",
            transcript_files=2, transcript_bytes=100, chunks=2,
            key_id="fixture-key", recovery_key="CV1-PRIVATE-RECOVERY",
        )

        def finish(*args, **kwargs):
            kwargs["progress"](2, 2, 100, 100)
            return completed

        with patch("codex_migrate.setup.plan_vault_backup", return_value=planned), \
                patch("codex_migrate.setup.backup_vault", side_effect=finish):
            code, running = self.request(
                "/api/vault/backup", {"destination": destination, "apply": True})
            self.assertEqual(code, 202)
            self.assertIn(running["status"], ("running", "completed"))
            self.helper._vault_thread.join(timeout=3)
            code, status = self.request("/api/vault/backup-status")
            self.assertEqual(code, 200)
            self.assertEqual(status["status"], "completed")
            self.assertEqual(status["recovery_key"], "CV1-PRIVATE-RECOVERY")
            self.assertEqual(status["transcript_files"], 2)
            self.assertEqual(self.request("/api/shutdown", {})[0], 409)
            code, acknowledged = self.request("/api/vault/recovery-saved", {})
            self.assertEqual(code, 200)
            self.assertNotIn("recovery_key", acknowledged)

    def test_vault_backup_rejects_a_second_writer_while_running(self):
        destination = str(self.home / "vault")
        planned = BackupPlan(destination, 1, 10)
        entered, release = threading.Event(), threading.Event()

        def wait_for_release(*args, **kwargs):
            entered.set()
            release.wait(3)
            return BackupResult(
                destination=destination, snapshot_id="fixture-snapshot",
                transcript_files=1, transcript_bytes=10, chunks=1,
                key_id="fixture-key", recovery_key=None,
            )

        try:
            with patch("codex_migrate.setup.plan_vault_backup", return_value=planned), \
                    patch("codex_migrate.setup.backup_vault", side_effect=wait_for_release):
                self.assertEqual(self.request(
                    "/api/vault/backup", {"destination": destination, "apply": True})[0], 202)
                self.assertTrue(entered.wait(1))
                code, body = self.request(
                    "/api/vault/backup", {"destination": destination, "apply": True})
                self.assertEqual(code, 400)
                self.assertIn("already running", body["error"])
                code, body = self.request("/api/vault/restore", {
                    "vault": destination, "output": str(self.home / "recovered"),
                    "snapshot": "latest", "apply": True,
                })
                self.assertEqual(code, 400)
                self.assertIn("backup to finish", body["error"])
        finally:
            release.set()
            if self.helper._vault_thread:
                self.helper._vault_thread.join(timeout=3)

    def test_failed_first_backup_preserves_recovery_key_until_acknowledged(self):
        destination = str(self.home / "vault")
        planned = BackupPlan(destination, 1, 10)
        with patch("codex_migrate.setup.plan_vault_backup", return_value=planned), \
                patch("codex_migrate.setup.backup_vault", side_effect=RuntimeError("private")), \
                patch("codex_migrate.setup.export_recovery_key",
                      return_value="CV1-PRIVATE-RECOVERY"):
            self.assertEqual(self.request(
                "/api/vault/backup", {"destination": destination, "apply": True})[0], 202)
            self.helper._vault_thread.join(timeout=3)
            status = self.request("/api/vault/backup-status")[1]
            self.assertEqual(status["status"], "failed")
            self.assertEqual(status["recovery_key"], "CV1-PRIVATE-RECOVERY")
            self.assertNotIn("private", status["error"])
            self.assertEqual(self.request("/api/shutdown", {})[0], 409)
            acknowledged = self.request("/api/vault/recovery-saved", {})[1]
            self.assertNotIn("recovery_key", acknowledged)

    def test_vault_folder_picker_is_fixed_and_cancel_is_non_destructive(self):
        completed = subprocess.CompletedProcess(
            [], 0, stdout=str(self.home / "Vault") + "\n", stderr="")
        with patch("codex_migrate.setup.subprocess.run", return_value=completed) as run:
            code, result = self.request("/api/vault/folder", {})
        self.assertEqual(code, 200)
        self.assertEqual(result["path"], str(self.home / "Vault"))
        self.assertEqual(run.call_args.args[0][:3], ["/usr/bin/osascript", "-l", "JavaScript"])
        self.assertNotIn(str(self.home), run.call_args.args[0][-1])

        cancelled = subprocess.CompletedProcess([], 1, stdout="", stderr="User canceled. (-128)")
        with patch("codex_migrate.setup.subprocess.run", return_value=cancelled):
            self.assertEqual(self.request("/api/vault/folder", {})[1]["path"], None)

    def test_vault_search_open_and_markdown_export_are_read_only(self):
        transcript = self.home / ".codex/sessions/2026/09/thread.jsonl"
        transcript.parent.mkdir(parents=True)
        original = json.dumps({
            "timestamp": "2026-09-17T10:00:00Z",
            "payload": {"message": {"role": "user", "content": "Portable launch notes"}},
        }) + "\n"
        transcript.write_text(original, encoding="utf-8")
        code, summary = self.request("/api/vault/summary")
        self.assertEqual(code, 200)
        self.assertEqual(summary["active_transcripts"], 1)
        code, results = self.request("/api/vault/search?q=launch&limit=10")
        self.assertEqual(code, 200)
        item = results["results"][0]
        self.assertEqual(item["collection"], "active")
        identifier = "2026/09/thread.jsonl"
        code, thread = self.request("/api/vault/thread?collection=active&transcript=" + identifier)
        self.assertEqual(code, 200)
        self.assertEqual(thread["entries"][0]["role"], "user")
        code, document = self.request("/api/vault/export?collection=active&transcript=" + identifier)
        self.assertEqual(code, 200)
        self.assertIn("# Codex conversation", document)
        self.assertIn("Portable launch notes", document)
        self.assertEqual(transcript.read_text(encoding="utf-8"), original)

    def test_vault_rejects_traversal_and_foreign_origin(self):
        path = "/api/vault/thread?collection=active&transcript=../auth.json"
        self.assertEqual(self.request(path)[0], 400)
        self.assertEqual(self.request("/api/vault/summary", extra_headers={"Origin": "https://example.com"})[0], 403)

    def test_private_setup_and_picker_require_token(self):
        for path, data in (("/api/setup", None), ("/api/setup", self.config()),
                           ("/api/folders", {}), ("/api/suggestions", {})):
            self.assertEqual(self.request(path, data, authorized=False)[0], 403)

    def test_saved_connection_is_private_and_reopening_never_approves_it(self):
        state = {"source": {"status": "request_ready", "card": "public-fixture"}}
        with patch.object(self.helper.pairing, "snapshot", return_value=state) as snapshot, \
                patch.object(self.helper.pairing, "approve") as approve:
            self.assertEqual(self.request("/api/setup", authorized=False)[0], 403)
            snapshot.assert_not_called()
            code, result = self.request("/api/setup")
            self.assertEqual(code, 200)
            self.assertEqual(result["connection"], state)
            self.assertIsNone(self.helper.engine)
            approve.assert_not_called()
            self.helper.configure(self.config())
            snapshot.reset_mock()
            self.assertTrue(self.request("/api/setup")[1]["attached"])
            snapshot.assert_not_called()

    def test_unreadable_connection_is_not_fresh_or_raw_error_disclosure(self):
        with patch.object(self.helper.pairing, "snapshot", side_effect=OSError("PRIVATE path")):
            code, result = self.request("/api/setup")
        self.assertEqual(code, 200)
        self.assertIn("could not be verified", result["connection_error"])
        self.assertNotIn("connection", result)
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.assertFalse(result["attached"])

    def test_rejects_foreign_origin_and_rebinding_host(self):
        for headers in ({"Origin": "https://evil.invalid"}, {"Host": "evil.invalid"}):
            self.assertEqual(self.request("/api/setup", self.config(), extra_headers=headers)[0], 403)
        self.assertIsNone(self.helper.engine)

    def test_connection_endpoints_require_local_token_and_explicit_approval(self):
        for action in ("request", "approve", "accept", "revoke", "restart"):
            endpoint = "/api/connection/" + action
            self.assertEqual(self.request(endpoint, {}, authorized=False)[0], 403)
            self.assertEqual(self.request(endpoint, {}, extra_headers={"Origin": "https://evil.invalid"})[0], 403)
        with patch.object(self.helper.pairing, "request", return_value={"card": "public-fixture"}) as create:
            self.assertEqual(self.request("/api/connection/request", {})[0], 200)
            create.assert_called_once_with()
            self.assertEqual(self.request("/api/connection/request", {"apply": True})[0], 400)
        for action in ("approve", "accept", "revoke", "restart"):
            self.assertEqual(self.request("/api/connection/" + action, {})[0], 400)
        self.assertFalse((self.home / ".ssh").exists())
        self.helper.configure(self.config())
        self.assertEqual(self.request("/api/connection/request", {})[0], 409)

    def test_paired_configuration_uses_owned_options_and_rejects_custom_key(self):
        from codex_migrate.config import SSHOptions
        options = SSHOptions(identity_file=str(self.home / "state/connection/identity"),
                             known_hosts_file=str(self.home / "state/connection/known_hosts"),
                             host_key_alias="paired-fixture", isolated=True)
        with patch.object(self.helper.pairing, "options", return_value=options) as paired:
            self.assertEqual(self.request("/api/setup", self.config(paired=True, identity_file="/tmp/other"))[0], 400)
            paired.assert_not_called()
            self.assertEqual(self.request("/api/setup", self.config(paired=True))[0], 200)
            paired.assert_called_once_with("user@fixture.local", "/Users/user")
            self.assertEqual(self.helper.engine.config.ssh, options)
            self.assertTrue(self.helper.registry.read()["saved"]["paired"])

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

    def test_browser_shutdown_requires_local_token_and_stops_idle_server(self):
        self.assertEqual(self.request("/api/shutdown", {}, authorized=False)[0], 403)
        self.assertEqual(self.request("/api/shutdown", {}, extra_headers={"Origin": "https://example.com"})[0], 403)
        self.assertFalse(self.helper._closing)
        self.assertEqual(self.request("/api/shutdown", {})[0], 200)
        self.thread.join(timeout=2)
        self.assertFalse(self.thread.is_alive())
        self.assertTrue(self.helper._closing)

    def test_browser_shutdown_cannot_interrupt_running_paused_or_worker(self):
        self.helper.configure(self.config())
        for status in ("running", "paused"):
            self.helper.state.update(status=status)
            self.assertEqual(self.request("/api/shutdown", {})[0], 409)
            self.assertFalse(self.helper._closing)
        self.helper.state.update(status="idle")
        release = threading.Event()
        self.helper.engine._thread = threading.Thread(target=lambda: release.wait(3))
        self.helper.engine._thread.start()
        try:
            self.assertEqual(self.request("/api/shutdown", {})[0], 409)
        finally:
            release.set()
            self.helper.engine._thread.join(timeout=3)

    def test_suggestions_only_use_existing_common_folders(self):
        code, result = self.request("/api/suggestions", {})
        self.assertEqual(code, 200)
        self.assertEqual(result["paths"], [str(self.home / "Git")])

    def test_cancelled_folder_picker_reports_no_addition_without_configuring(self):
        before = self.helper.registry.read()
        with patch.object(self.helper, "choose_folders", return_value=[]):
            code, result = self.request("/api/folders", {})
        self.assertEqual(code, 200)
        self.assertEqual(result, {"paths": [], "message":
                         "No folders added. Your existing selection is unchanged."})
        self.assertEqual(self.helper.registry.read(), before)
        self.assertIsNone(self.helper.engine)

    def test_selected_folder_message_does_not_claim_suggestions_were_used(self):
        with patch.object(self.helper, "choose_folders", return_value=[str(self.home / "Git")]):
            code, result = self.request("/api/folders", {})
        self.assertEqual(code, 200)
        self.assertEqual(result["paths"], [str(self.home / "Git")])
        self.assertEqual(result["message"], "Review the selected folder paths.")

    def test_picker_failure_gives_recovery_without_private_exception_text(self):
        before = self.helper.registry.read()
        for failure in (PermissionError("private-fixture-path"), RuntimeError("private-native-stderr")):
            with self.subTest(failure=type(failure).__name__), \
                    patch.object(self.helper, "choose_folders", side_effect=failure):
                code, result = self.request("/api/folders", {})
            self.assertEqual(code, 400)
            self.assertIn("Review or edit folder paths", result["error"])
            self.assertIn("System Settings", result["error"])
            self.assertIn("existing selection is unchanged", result["error"])
            self.assertNotIn("private-", json.dumps(result))
            self.assertEqual(self.helper.registry.read(), before)
            self.assertIsNone(self.helper.engine)

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

    def test_protected_case_aliases_fail_http_setup_without_saving_or_ssh(self):
        before = self.helper.registry.read()
        with patch("codex_migrate.transport.SSHTransport.run_remote",
                   side_effect=AssertionError("Unexpected SSH")):
            for mode in ("full", "skills"):
                for relative in (".CODEX", ".SSH", ".AGENTS/SKILLS", "STATE"):
                    payload = {**self.config(mode=mode), "workspace_roots": [str(self.home / relative)]}
                    if mode == "skills":
                        payload["components"] = ["workspace-skills"]
                    with self.subTest(mode=mode, relative=relative):
                        self.assertEqual(self.request("/api/setup", payload)[0], 400)
                        self.assertIsNone(self.helper.engine)
                        self.assertEqual(self.helper.registry.read(), before)

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
