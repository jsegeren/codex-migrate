"""Loopback-only rendered UI fixture, not cloud or encryption acceptance.

No Codex files, accounts, Keychain, provider or billing calls. This serves the
actual dashboard with explicitly labelled synthetic unfinished-upload states.
Run with PYTHONPATH=src python3 tests/manual_hosted_setup_fixture.py.
"""

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlsplit

from codex_migrate.vault_dashboard import VAULT_HTML


RESERVATION = "11111111-1111-4111-8111-111111111111"
SNAPSHOT = "22222222-2222-4222-8222-222222222222"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", choices=("active", "cleanup_pending", "released", "published"), default="active")
    args = parser.parse_args()
    state = {"remote": args.state, "phase": "pending_upload"}

    def public():
        result = {"enabled": True, "phase": state["phase"], "status": "ready",
                  "automatic_protection_verified": False, "upload_authorized": False,
                  "last_backup_checked_at": "2026-10-03T00:00:00+00:00",
                  "last_backup": {"status": "published", "source_coverage": "complete", "at_risk_threads": 0},
                  "background": {"enabled": False}}
        if state["remote"] is not None:
            result["pending_upload"] = {"pending": True, "reservation_id": RESERVATION,
                "snapshot_id": SNAPSHOT, "local_phase": "active", "remote_status": state["remote"],
                "can_abandon": state["remote"] != "published", "automatic_protection_verified": False}
        return result

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, code, value, content_type="application/json"):
            data = value.encode() if isinstance(value, str) else json.dumps(value).encode()
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/vault":
                self.send(200, VAULT_HTML.replace("<h2>Connect this Mac</h2>",
                    "<h2>Connect this Mac</h2><p role=note>SIMULATED UI FIXTURE — no real backup, account or subscription.</p>"), "text/html; charset=utf-8")
            elif path == "/api/vault/hosted-setup-status":
                self.send(200, public())
            elif path == "/api/vault/summary":
                self.send(200, {"active_transcripts": 0, "archived_transcripts": 0,
                    "transcript_bytes": 0, "paginated_database_present": False})
            elif path == "/api/vault/schedule":
                self.send(200, {"enabled": False})
            elif path in ("/api/vault/backup-status", "/api/vault/restore-status",
                          "/api/vault/install-status", "/api/vault/browse-status",
                          "/api/vault/thread-install-status", "/api/vault/search-index-status"):
                self.send(200, {"status": "idle"})
            else:
                self.send(404, {"error": "Not part of this synthetic UI fixture."})

        def do_POST(self):
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if self.path != "/api/vault/hosted-setup" or not 0 < size <= 8192:
                    raise ValueError()
                data = json.loads(self.rfile.read(size))
                step, action = data["step"], data["action"]
                if step.get("apply") is not True:
                    raise ValueError()
                if action == "leave_upload_review":
                    state["phase"] = "backup_ready"
                elif action == "check_upload":
                    state["phase"] = "pending_upload" if state["remote"] else "backup_ready"
                elif (action == "abandon_upload" and state["phase"] == "pending_upload"
                      and step.get("reservation_id") == RESERVATION
                      and step.get("confirm_abandon") is True and state["remote"] != "published"):
                    if state["remote"] == "active":
                        state["remote"] = "cleanup_pending"
                    else:
                        state.update(remote=None, phase="backup_ready")
                else:
                    raise ValueError()
                self.send(202, public())
            except (ValueError, TypeError, KeyError):
                self.send(400, {"error": "Invalid synthetic fixture step."})

    server = HTTPServer(("127.0.0.1", 0), Handler)
    print("http://127.0.0.1:%d/vault?view=backup" % server.server_port, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
