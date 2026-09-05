"""Disposable two-browser UI fixture, not a real cross-Mac acceptance test.

Run with PYTHONPATH=src. The only homes are fresh temporary directories. Account
lookup and receiving-Mac metadata are fixtures; key generation, approval files,
cards, setup routes and browser interactions use the real implementation.
URLs contain private loopback control tokens; don't publish them or these files.
"""
import base64
import json
from pathlib import Path
import tempfile
import threading
from unittest.mock import patch

from codex_migrate.dashboard import LoopbackHTTPServer
from codex_migrate.setup import SetupDashboard


def main():
    helpers, servers = [], []
    key = "ssh-ed25519 " + base64.b64encode(b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + b"x" * 32).decode()
    with tempfile.TemporaryDirectory(prefix="codex-pairing-ui-") as root, patch(
            "codex_migrate.pairing._account", return_value="sampleuser"):
        try:
            for role in ("old", "new"):
                home = Path(root) / role
                home.mkdir(mode=0o700)
                helper = SetupDashboard(str(home), str(home / "state"))
                helpers.append(helper)
                if role == "new":
                    helper.pairing._prepare()
                    helper.pairing._receiver_details = lambda: dict(
                        target="sampleuser@fixture.local", home="/Users/sampleuser", host_key=key)
                server = LoopbackHTTPServer(("127.0.0.1", 0), helper._handler())
                servers.append(server)
                threading.Thread(target=server.serve_forever, daemon=True).start()
                print(json.dumps({"role": role, "url": "http://127.0.0.1:%d/#token=%s" %
                                  (server.server_port, helper.token)}), flush=True)
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        finally:
            for server in servers:
                server.shutdown()
                server.server_close()
            for helper in helpers:
                helper.close()


if __name__ == "__main__":
    main()
