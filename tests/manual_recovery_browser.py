"""Render the shipped recovery UI against local, disposable APFS fixtures.

Run with PYTHONPATH=src:tests python3 tests/manual_recovery_browser.py.
No SSH, real home, real authentication or real Codex process is used. The
fixture transport substitutes the process snapshot only; production restoration
and verification operate on fresh temporary directories. This is not physical
cross-Mac, authentic Codex, or complete buyer-flow acceptance.
"""

import json
import os
import platform
from unittest.mock import patch

from codex_migrate.dashboard import Dashboard, LoopbackHTTPServer
from test_restore import RestoreTests


def main():
    if platform.system() != "Darwin" or os.getuid() == 0:
        raise SystemExit("Requires a non-root macOS user and disposable APFS fixtures")
    fixture = RestoreTests()
    fixture.setUp()
    dashboard = None
    server = None
    try:
        fixture.newer_work()
        engine = fixture.fixture.engine
        state = engine.state
        state.update(status="interrupted", phase="installing", percent=0,
                     message="Synthetic demonstration: installation was interrupted. Review recovery before continuing.",
                     recovery={"status": "not_checked"})
        dashboard = Dashboard(engine, state, port=0)
        # Intentionally public fixture marker, never a real migration token.
        # Only these newly created temporary folders can be affected.
        dashboard.token = "disposable-browser-fixture-only"
        base_handler = dashboard._handler()

        class FixtureHandler(base_handler):
            def do_GET(self):
                if self.path != "/fixture-proof":
                    return super().do_GET()
                if not self._authorized():
                    return self._json(403, {"error": "Missing fixture token"})
                try:
                    fixture.assert_restored(newer=True)
                    self._json(200, {"synthetic_only": True,
                                     "selected_original_files_restored": True,
                                     "selected_newer_files_preserved": True,
                                     "selected_backup_and_source_files_unchanged": True,
                                     "pending_transaction": False,
                                     "migration_complete": state.read().get("status") == "complete"})
                except (AssertionError, OSError):
                    self._json(409, {"synthetic_only": True, "restoration_verified": False})

        server = LoopbackHTTPServer(("127.0.0.1", 0), FixtureHandler)
        print(json.dumps({"url": "http://127.0.0.1:%d/" % server.server_port,
                          "fixture_only": True}), flush=True)
        # The restore command embeds its guard inside a quoted argument, unlike
        # installer scripts. Substitute the same fixture snapshot before quoting.
        with patch("codex_migrate.restore.require_codex_closed_script", return_value=fixture.guard):
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if server:
            server.server_close()
        if dashboard:
            dashboard.close()
        fixture.doCleanups()


if __name__ == "__main__":
    main()
