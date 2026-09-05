"""In-process Foundation defaults only: never install profiles or write preferences."""
import json
import subprocess
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

from codex_migrate.errors import MigrationError
from codex_migrate.managed_preferences import PROBE, managed_preferences_script
from codex_migrate.storage_scope import require_source_storage


def fixture_probe(values=None):
    # A unique suite avoids the real account's Codex preferences. Registration
    # defaults exist only in this short-lived process; no persistent setter runs.
    domain = "org.codexmigrate.fixture." + uuid.uuid4().hex
    probe = PROBE.replace('"com.openai.codex"', json.dumps(domain))
    if values is not None:
        probe = probe.replace('const keys = ', 'prefs.registerDefaults($(' + json.dumps(values) + '));\n        const keys = ')
    return probe


class ManagedPreferenceTests(unittest.TestCase):
    def run_guard(self, probe, *, deadline=10):
        with patch("codex_migrate.managed_preferences.PROBE", probe):
            script = managed_preferences_script().replace("alarm 10;", "alarm %d;" % deadline)
        result = subprocess.run(["/bin/zsh", "-f", "-s"], input=script,
                                capture_output=True, text=True, timeout=deadline + 5)
        self.assertEqual(result.stdout, "")
        self.assertNotIn("PRIVATE_FIXTURE", result.stderr)
        return result

    def test_absent_keys_allow_continuation_without_reading_account_domain(self):
        result = self.run_guard(fixture_probe())
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")

    def test_each_present_key_blocks_including_false_and_empty_values(self):
        for key in ("config_toml_base64", "requirements_toml_base64"):
            for value in ("PRIVATE_FIXTURE", "", False, 0, {"private": "PRIVATE_FIXTURE"}):
                with self.subTest(key=key, kind=type(value).__name__):
                    result = self.run_guard(fixture_probe({key: value}))
                    self.assertEqual(result.returncode, 68)
                    self.assertIn("administrator", result.stderr)
                    self.assertIn("do not disable", result.stderr)

    def test_unrelated_preferences_are_not_a_management_signal(self):
        result = self.run_guard(fixture_probe({"unrelated": "PRIVATE_FIXTURE"}))
        self.assertEqual(result.returncode, 0)

    def test_framework_error_and_invalid_probe_output_are_unknown_not_absent(self):
        for probe in (
            PROBE.replace('ObjC.import("Foundation");', 'throw new Error("PRIVATE_FIXTURE");'),
            'function run() { return "ABSENT\\nPRIVATE_FIXTURE"; }',
            'function run() { return ""; }',
            'PRIVATE_FIXTURE invalid syntax !',
        ):
            with self.subTest(probe=probe[:20]):
                result = self.run_guard(probe)
                self.assertEqual(result.returncode, 69)
                self.assertIn("could not be checked", result.stderr)

    def test_deadline_terminates_slow_probe_and_preserves_unknown(self):
        started = time.monotonic()
        result = self.run_guard('function run() { delay(30); return "ABSENT"; }', deadline=1)
        self.assertEqual(result.returncode, 69)
        self.assertLess(time.monotonic() - started, 5)

    def test_check_does_not_convert_or_decode_policy_payload(self):
        self.assertNotIn("ObjC.unwrap", PROBE)
        self.assertNotIn("base64Encoded", PROBE)
        self.assertNotIn("registerDefaults", PROBE)
        self.assertNotIn("setObject", PROBE)
        self.assertIn("objectForKey(key).isNil()", PROBE)

    def test_source_preferences_are_not_attributed_to_another_home(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".codex").mkdir()
            with patch("codex_migrate.storage_scope.managed_preferences_script", side_effect=AssertionError("Wrong account")):
                require_source_storage(str(home))

    def test_matching_source_account_stops_before_inventory(self):
        from codex_migrate.inventory import collect
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".codex/sessions").mkdir(parents=True)
            with patch("codex_migrate.storage_scope.pwd.getpwuid") as account, \
                 patch("codex_migrate.managed_preferences.PROBE", fixture_probe({"config_toml_base64": "PRIVATE_FIXTURE"})), \
                 patch("codex_migrate.inventory._tree_summary", side_effect=AssertionError("No content inventory")):
                account.return_value.pw_dir = str(home)
                with self.assertRaisesRegex(MigrationError, "Managed Codex preferences were detected"):
                    collect(str(home), [])

    def test_matching_source_unknown_is_not_a_successful_storage_check(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".codex").mkdir()
            with patch("codex_migrate.storage_scope.pwd.getpwuid") as account, \
                 patch("codex_migrate.managed_preferences.PROBE", 'function run() { return "UNKNOWN"; }'):
                account.return_value.pw_dir = str(home)
                with self.assertRaisesRegex(MigrationError, "could not be checked"):
                    require_source_storage(str(home))

    def test_source_cancellation_reaps_a_running_preference_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".codex").mkdir()
            children = []
            original = subprocess.Popen
            calls = 0
            def launch(*args, **kwargs):
                child = original(*args, **kwargs)
                children.append(child)
                return child
            def checkpoint():
                nonlocal calls
                calls += 1
                if calls >= 4:
                    raise MigrationError("Stopped fixture preference check")
            with patch("codex_migrate.storage_scope.pwd.getpwuid") as account, \
                 patch("codex_migrate.managed_preferences.PROBE", 'function run() { delay(30); return "ABSENT"; }'), \
                 patch("codex_migrate.storage_scope.subprocess.Popen", side_effect=launch):
                account.return_value.pw_dir = str(home)
                with self.assertRaisesRegex(MigrationError, "Stopped fixture preference check"):
                    require_source_storage(str(home), checkpoint)
            self.assertEqual(len(children), 1)
            self.assertIsNotNone(children[0].poll())

    def test_late_source_preference_keeps_staging_and_destination(self):
        import test_full_skills as fixtures
        fixture = fixtures.FullSkillTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.prepare()
        with patch("codex_migrate.storage_scope.pwd.getpwuid") as account, \
             patch("codex_migrate.managed_preferences.PROBE", fixture_probe({"requirements_toml_base64": "PRIVATE_FIXTURE"})), \
             patch.object(fixture.engine.transport, "rsync_process", side_effect=AssertionError("No copy")):
            account.return_value.pw_dir = str(fixture.source)
            for action in (fixture.engine._copy_all, fixture.engine._prepare_install):
                with self.assertRaisesRegex(MigrationError, "Managed Codex preferences were detected"):
                    action()
        fixture.assert_destination_original()
        self.assertTrue(Path(fixture.config.target_staging).exists())

    def test_destination_preflight_stops_before_staging_or_backup(self):
        import test_full_skills as fixtures
        fixture = fixtures.FullSkillTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        transport = fixture.engine.transport = Mock()
        transport.select_route.return_value = "Disposable test route"
        transport.check.return_value = "USER=newperson\nHOME=" + str(fixture.target) + "\nFILESYSTEM=apfs\n"
        def check(script, timeout, cancelled):
            self.assertFalse(cancelled())
            result = subprocess.run(["/bin/zsh", "-f", "-s"], input=script,
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 68)
            self.assertNotIn("PRIVATE_FIXTURE", result.stderr)
            raise MigrationError("Fixture preferences require review")
        transport.run_remote_cancellable.side_effect = check
        with patch("codex_migrate.migration.check_compatibility", return_value={"status": "mapped"}), \
             patch("codex_migrate.managed_preferences.PROBE", fixture_probe({"config_toml_base64": "PRIVATE_FIXTURE"})):
            with self.assertRaisesRegex(MigrationError, "Fixture preferences require review"):
                fixture.engine.preflight()
        transport.run_remote_cancellable.assert_called_once()
        transport.rsync_process.assert_not_called()
        self.assertFalse(Path(fixture.config.target_staging).exists())
        fixture.assert_destination_original()

    def test_late_destination_preference_blocks_prepared_install(self):
        import test_full_skills as fixtures
        fixture = fixtures.FullSkillTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.prepare()
        prepared = fixture.engine._prepare_install()
        for probe, message in (
            (fixture_probe({"requirements_toml_base64": "PRIVATE_FIXTURE"}), "Managed Codex preferences were detected"),
            ('function run() { return "UNKNOWN"; }', "could not be checked"),
        ):
            with patch("codex_migrate.managed_preferences.PROBE", probe):
                with self.assertRaisesRegex(RuntimeError, message):
                    fixture.engine._install_and_verify(prepared)
        fixture.assert_destination_original()
        self.assertEqual(list(fixture.target.glob("Codex-Migrate-Backup-*")), [])
        self.assertTrue(Path(fixture.config.target_staging).exists())
