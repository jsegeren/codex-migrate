"""Real filesystem-denial probes; not a substitute for macOS TCC/picker tests."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class PackagedPermissionDenialTests(unittest.TestCase):
    def check_denied_directory(self, relative):
        if os.getuid() == 0:
            self.skipTest("Requires an unprivileged account")
        with tempfile.TemporaryDirectory(prefix="codex-migrate-permission-") as temporary:
            home = Path(temporary)
            (home / ".codex/sessions").mkdir(parents=True)
            (home / ".codex/sessions/fixture.jsonl").write_text("{}\n")
            workspace = home / "workspace"
            workspace.mkdir()
            blocked = home / relative
            blocked.mkdir(parents=True, exist_ok=True)
            sentinel = blocked / "permission-sentinel.txt"
            contents = b"Invented fixture only; must not be changed.\n"
            sentinel.write_bytes(contents)
            command = [os.environ["CODEX_MIGRATE_TEST_ENGINE"]] if os.environ.get("CODEX_MIGRATE_TEST_ENGINE") else [sys.executable, "-m", "codex_migrate"]
            env = dict(os.environ)
            if os.environ.get("CODEX_MIGRATE_TEST_ENGINE"):
                env = {k: v for k, v in env.items() if not k.startswith(("PYTHON", "DYLD_"))}
                env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
            else:
                env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
            blocked.chmod(0)
            try:
                with self.assertRaises(PermissionError):
                    list(blocked.iterdir())
                result = subprocess.run(command + ["inventory", "--source-home", str(home),
                    "--workspace", str(workspace), "--json"], cwd=temporary,
                    env=env, capture_output=True, timeout=60)
                self.assertNotIn(contents.strip(), result.stdout + result.stderr)
                self.assertNotIn(b"Traceback", result.stderr)
                if result.returncode == 0:
                    report = json.loads(result.stdout)
                    self.assertTrue(report["unreadable_paths"], "Denied data must never appear fully readable")
                else:
                    self.assertEqual(result.stdout, b"")
                    self.assertTrue(result.stderr.strip(), "Refusal needs an actionable error")
            finally:
                blocked.chmod(0o700)
            self.assertEqual(sentinel.read_bytes(), contents)
            self.assertEqual((home / ".codex/sessions/fixture.jsonl").read_text(), "{}\n")
            self.assertFalse((home / ".codex-migrate-transaction.json").exists())

    def test_actual_denied_workspace_directory(self):
        self.check_denied_directory("workspace/locked")

    def test_actual_denied_codex_directory(self):
        self.check_denied_directory(".codex/sessions/locked")


if __name__ == "__main__":
    unittest.main()
