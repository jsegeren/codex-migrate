"""Early Git-runtime checks must not touch repositories or start a transfer."""

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from codex_migrate.config import MigrationConfig
from codex_migrate.errors import MigrationError
from codex_migrate.git_verification import require_runtime
from codex_migrate.inventory import collect
from codex_migrate.migration import MigrationEngine
from codex_migrate.state import StateStore


REPORT = {"format": 1, "git_version": "2.50.1", "repositories": []}


class GitReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name).resolve()
        (self.home / ".codex/sessions").mkdir(parents=True)
        self.config = MigrationConfig(source_home=str(self.home), target="fixture@fixture.invalid",
                                      target_home="/Users/fixture", state_dir=str(self.home / "state")).validate()
        self.state = StateStore(self.config.state_dir)
        self.engine = MigrationEngine(self.config, self.state)

    def test_real_source_runtime_check_needs_no_selected_read_roots(self):
        result = require_runtime(str(self.home))
        self.assertRegex(result, r"^[0-9]+\.[0-9]+\.[0-9]+$")
        self.assertEqual(list((self.home / ".codex/sessions").iterdir()), [])

    def test_local_check_passes_no_repository_read_scopes(self):
        with patch("codex_migrate.git_verification.probe_local", return_value=REPORT) as probe:
            self.assertEqual(require_runtime(str(self.home)), "2.50.1")
            self.assertEqual(probe.call_args.args[:3], (str(self.home), [], []))

    def test_destination_uses_strict_transport_with_empty_repo_scope(self):
        transport = Mock()
        transport.run_remote_cancellable.return_value = SimpleNamespace(stdout=json.dumps(REPORT))
        with patch("codex_migrate.git_verification.probe_script", return_value="SAFE_FIXTURE_SCRIPT") as probe:
            self.assertEqual(require_runtime("/Users/fixture", transport), "2.50.1")
            probe.assert_called_once_with("/Users/fixture", [], [])
            self.assertEqual(transport.run_remote_cancellable.call_args.args, ("SAFE_FIXTURE_SCRIPT",))

    def test_prelaunch_cancellation_never_starts_local_or_remote_check(self):
        with patch("codex_migrate.git_verification.probe_local") as local:
            with self.assertRaisesRegex(MigrationError, "stopped"):
                require_runtime(str(self.home), cancelled=lambda: True)
            local.assert_not_called()
        transport = Mock()
        with self.assertRaisesRegex(MigrationError, "stopped"):
            require_runtime("/Users/fixture", transport, lambda: True)
        transport.run_remote_cancellable.assert_not_called()

    def test_raw_failure_details_never_reach_message(self):
        for remote in (False, True):
            transport = Mock() if remote else None
            if transport:
                transport.run_remote_cancellable.side_effect = RuntimeError("PRIVATE_FIXTURE")
            with patch("codex_migrate.git_verification.probe_local", side_effect=MigrationError("PRIVATE_FIXTURE")):
                with self.assertRaises(MigrationError) as caught:
                    require_runtime(str(self.home), transport)
            self.assertNotIn("PRIVATE_FIXTURE", str(caught.exception))
            self.assertIn("destination" if remote else "source", str(caught.exception))
            self.assertIn("Transfer is blocked", str(caught.exception))

    def test_malformed_remote_result_is_not_readiness(self):
        transport = Mock()
        transport.run_remote_cancellable.return_value = SimpleNamespace(stdout='{"repositories": []}')
        with self.assertRaisesRegex(MigrationError, "destination"):
            require_runtime("/Users/fixture", transport)

    def inventory(self, count=1):
        report = collect(str(self.home), [])
        return SimpleNamespace(**{**report.__dict__, "git_repositories": count, "as_dict": report.as_dict})

    def test_source_unavailable_blocks_before_ssh_or_copy(self):
        self.engine.inventory = lambda: self.inventory()
        self.engine.transport = Mock()
        with patch("codex_migrate.migration.require_runtime", side_effect=MigrationError("Source runtime unavailable")):
            with self.assertRaisesRegex(MigrationError, "Source runtime unavailable"):
                self.engine.preflight()
        self.engine.transport.check.assert_not_called()
        self.engine.transport.rsync_process.assert_not_called()

    def test_destination_unavailable_blocks_before_backup_and_staging(self):
        self.engine.inventory = lambda: self.inventory()
        transport = self.engine.transport = Mock()
        transport.select_route.return_value = "Disposable test route"
        transport.check.return_value = "USER=fixture\nHOME=/Users/fixture\nFILESYSTEM=apfs\n"
        with patch("codex_migrate.migration.require_runtime", side_effect=["2.50.1", MigrationError("Destination runtime unavailable")]) as check:
            with self.assertRaisesRegex(MigrationError, "Destination runtime unavailable"):
                self.engine.preflight()
        self.assertEqual(check.call_count, 2)
        transport.rsync_process.assert_not_called()
        self.assertEqual(transport.run_remote.call_count, 1)  # existing Perl tool probe only
        self.assertFalse(self.state.read().get("staging_complete"))
        self.assertIsNone(self.state.read().get("pending_backup"))

    def test_home_identity_mismatch_precedes_destination_git_probe(self):
        self.engine.inventory = lambda: self.inventory()
        self.engine.transport = Mock()
        self.engine.transport.check.return_value = "USER=wrong\nHOME=/Users/wrong\nFILESYSTEM=apfs\n"
        with patch("codex_migrate.migration.require_runtime", return_value="2.50.1") as check:
            with self.assertRaisesRegex(MigrationError, "SSH user mismatch"):
                self.engine.preflight()
        self.assertEqual(check.call_count, 1)

    def test_no_repositories_does_not_require_git(self):
        self.engine.inventory = lambda: self.inventory(0)
        self.engine.transport = Mock()
        self.engine.transport.check.side_effect = MigrationError("Fixture stop after local checks")
        with patch("codex_migrate.migration.require_runtime") as check:
            with self.assertRaisesRegex(MigrationError, "Fixture stop"):
                self.engine.preflight()
            check.assert_not_called()
