import platform
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from codex_migrate.errors import MigrationError
from codex_migrate.processes import codex_running, process_state_script, require_codex_closed_script


class LocalProcessResultTests(unittest.TestCase):
    def test_only_successful_explicit_results_are_accepted(self):
        for output, status, expected in (("OPEN\n", 0, True), ("CLOSED\n", 0, False),
                                         ("", 0, None), ("CLOSED\n", 1, None),
                                         ("UNKNOWN", 0, None), ("OPEN\nCLOSED", 0, None)):
            with self.subTest(output=output, status=status), patch(
                "codex_migrate.processes.subprocess.run",
                return_value=SimpleNamespace(stdout=output, returncode=status),
            ) as run:
                if expected is None:
                    with self.assertRaises(MigrationError):
                        codex_running("/Users/test")
                else:
                    self.assertEqual(codex_running("/Users/test"), expected)
                self.assertEqual(run.call_args.args[0], ["/bin/zsh", "-f", "-s"])
                self.assertEqual(run.call_args.kwargs["timeout"], 15)

    def test_process_launch_and_decode_failures_block(self):
        for error in (OSError("private path"), subprocess.TimeoutExpired("ps", 15),
                      UnicodeError("private process name")):
            with self.subTest(error=type(error)), patch(
                "codex_migrate.processes.subprocess.run", side_effect=error
            ):
                with self.assertRaisesRegex(MigrationError, "finalization is blocked") as raised:
                    codex_running()
                self.assertNotIn("private", str(raised.exception))


@unittest.skipUnless(platform.system() == "Darwin", "macOS process guard")
class ProcessScriptTests(unittest.TestCase):
    def probe(self, rows="501 /bin/zsh\n", uid="501", real_uid="501", home_uid="501",
              ps_status=0, id_status=0, stat_status=0, require_closed=False):
        with tempfile.TemporaryDirectory(prefix="codex-process-") as directory:
            home = Path(directory) / "test home ' quoted"
            home.mkdir()
            script = (require_codex_closed_script if require_closed else process_state_script)(str(home))
            script = script.replace("/usr/bin/id", "fixture_id")
            script = script.replace("/usr/bin/stat", "fixture_stat")
            script = script.replace("/bin/ps", "fixture_ps")
            prefix = """fixture_id() {
  if test "$1" = -ru; then printf '%%s\\n' %s; else printf '%%s\\n' %s; fi
  return %d
}
fixture_stat() { printf '%%s\\n' %s; return %d; }
fixture_ps() { printf '%%s' %s; return %d; }
""" % (shlex.quote(real_uid), shlex.quote(uid), id_status,
       shlex.quote(home_uid), stat_status, shlex.quote(rows), ps_status)
            return subprocess.run(["/bin/zsh", "-f", "-s"],
                                  input=prefix + script + "\nprintf 'GUARD_PASSED\\n'\n",
                                  text=True, capture_output=True, timeout=15)

    def assert_blocked(self, result):
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("GUARD_PASSED", result.stdout)
        self.assertNotIn("CLOSED", result.stdout)

    def test_app_and_cli_executable_names_ignore_install_location(self):
        for name in ("ChatGPT", "Codex", "codex"):
            result = self.probe(rows="501 /Applications/Custom Location/" + name + "\n")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "OPEN\nGUARD_PASSED\n")

    def test_other_accounts_do_not_block_and_similar_names_do_not_match(self):
        result = self.probe(rows="-2 /usr/sbin/distnoted\n502 /Applications/Codex\n502 /bin/codex\n"
                           "501 /Applications/Codex Migrate\n501 /bin/codex-migrate-engine\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "CLOSED\nGUARD_PASSED\n")

    def test_failed_process_listing_even_with_valid_output_blocks(self):
        self.assert_blocked(self.probe(ps_status=1))

    def test_empty_malformed_or_missing_account_snapshot_blocks(self):
        for rows in ("", "garbage\n", "501\n", "other /bin/Codex\n", "502 /bin/zsh\n"):
            with self.subTest(rows=rows):
                self.assert_blocked(self.probe(rows=rows))

    def test_identity_errors_root_and_other_home_ownership_block(self):
        for options in ({"uid": ""}, {"uid": "bad"}, {"id_status": 1},
                        {"stat_status": 1}, {"home_uid": "502"}, {"home_uid": ""},
                        {"real_uid": "502"}, {"uid": "0", "real_uid": "0", "home_uid": "0"}):
            with self.subTest(options=options):
                self.assert_blocked(self.probe(**options))

    def test_install_guard_blocks_open_and_unknown_but_allows_other_user(self):
        self.assert_blocked(self.probe(rows="501 /bin/codex\n", require_closed=True))
        self.assert_blocked(self.probe(ps_status=1, require_closed=True))
        result = self.probe(rows="501 /bin/zsh\n502 /bin/Codex\n", require_closed=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "GUARD_PASSED\n")
