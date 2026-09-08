"""Serve the shipped setup UI with synthetic, delayed folder responses only.

PYTHONPATH=src python3 tests/manual_folder_selection_browser.py
No real folder picker, SSH, migration, credentials or filesystem writes.
The first picker request fails; the second returns an invented path; later
picker requests simulate Cancel. Suggestions return the same invented path.
"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import time

from codex_migrate.setup import FOLDER_PICKER_ERROR, SETUP_HTML


class Handler(BaseHTTPRequestHandler):
    picker_requests = 0

    def log_message(self, *args):
        pass

    def reply(self, status, value, html=False):
        body = value.encode() if html else json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8" if html else "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            return self.reply(200, SETUP_HTML, html=True)
        if self.path == "/api/setup":
            return self.reply(200, {"saved": {"target": "test@fixture.invalid",
                "target_home": "/Users/test", "workspace_roots": []}, "attached": False})
        self.reply(404, {"error": "Synthetic fixture endpoint only"})

    def do_POST(self):
        if self.path not in ("/api/folders", "/api/suggestions"):
            return self.reply(403, {"error": "Fixture cannot configure or run a migration"})
        time.sleep(5)
        if self.path == "/api/folders":
            Handler.picker_requests += 1
            if Handler.picker_requests == 1:
                return self.reply(400, {"error": FOLDER_PICKER_ERROR})
            if Handler.picker_requests > 2:
                return self.reply(200, {"paths": [],
                    "message": "No folders added. Your existing selection is unchanged."})
        self.reply(200, {"paths": ["/Users/test/Example Project"],
            "message": "Review the selected folders. Synthetic fixture only."})


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    print("http://127.0.0.1:%d/" % server.server_port, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
