"""Crash and rollback fault injection using disposable local APFS fixtures."""

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import unittest
from unittest.mock import patch

import test_backup as fixtures
from codex_migrate.components import ComponentExporter, SkillExport
from codex_migrate.destination_lock import locked_destination_script, locked_receiver_command
from codex_migrate.transaction import TRANSACTION_NAME, TRANSACTION_RUNNER, pending_check_script, recovery_preflight_script


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.BackupTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.engine = self.fixture.engine
        self.engine.transport = self.fixture.transport()
        self.journal = self.fixture.target / TRANSACTION_NAME

    def inject(self, transform):
        original = self.engine.transport.run_remote
        self.engine.transport.run_remote = lambda script, timeout=60: original(transform(script), timeout)

    def assert_pending_blocks_writes(self):
        for command, kwargs in (
            (["/bin/zsh", "-f", "-s"], {"input": pending_check_script(str(self.fixture.target))}),
            (["/bin/zsh", "-f", "-s"], {"input": locked_destination_script(str(self.fixture.target), "echo MUST_NOT_RUN")}),
            (["/bin/zsh", "-f", "-c", locked_receiver_command(str(self.fixture.target), "echo MUST_NOT_RUN")], {}),
        ):
            result = subprocess.run(command, capture_output=True, text=True, timeout=5, **kwargs)
            self.assertEqual(result.returncode, 78, result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertIn("unfinished destination installation", result.stderr)

    def test_full_success_archives_receipt_and_clears_pending(self):
        receipt = self.engine._install_and_verify()
        self.assertFalse(self.journal.exists())
        record = json.loads((Path(receipt["backup"]) / "transaction-receipt.json").read_text())
        self.assertEqual(record["phase"], "installed")
        self.assertTrue(all(item["existed"] for item in record["scope"]))
        self.assertNotIn("fixture-auth", json.dumps(record))
        self.assertEqual((self.fixture.target / ".codex/auth.json").read_text(), "fixture-auth")

    def test_recovery_preflight_is_read_only_and_checks_required_modules(self):
        script = recovery_preflight_script(str(self.fixture.target))
        result = subprocess.run(["/bin/zsh", "-f", "-s"], input=script,
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.journal.exists())
        result = subprocess.run(["/bin/zsh", "-f", "-s"],
                                input=script.replace("-MJSON::PP", "-MNoSuchFixtureModule"),
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 78)
        self.assertIn("recovery tools are unavailable", result.stderr)
        self.assertNotIn("Can't locate", result.stderr)
        self.fixture.assert_originals_untouched()

    def test_missing_original_workspace_is_recorded_without_fabricated_backup(self):
        shutil.rmtree(self.fixture.target / "Git")
        receipt = self.engine._install_and_verify()
        record = json.loads((Path(receipt["backup"]) / "transaction-receipt.json").read_text())
        workspace = next(item for item in record["scope"] if item["original"].endswith("/Git"))
        self.assertFalse(workspace["existed"])
        self.assertFalse(Path(workspace["backup"]).exists())
        self.assertFalse(self.journal.exists())

    def test_full_sigkill_after_removal_keeps_durable_record_and_backup(self):
        codex = shlex.quote(str(self.fixture.target / ".codex"))
        self.inject(lambda script: script.replace("rm -rf " + codex + "\nmv ",
                                                 "rm -rf " + codex + "\nkill -KILL $$\nmv "))
        with self.assertRaises(RuntimeError):
            self.engine._install_and_verify()
        self.assertFalse((self.fixture.target / ".codex").exists())
        record = json.loads(self.journal.read_text())
        self.assertEqual(record["phase"], "replacing")
        self.assertEqual(self.journal.stat().st_mode & 0o777, 0o600)
        self.assertEqual((Path(record["backup"]) / ".codex/old.txt").read_text(), "original")
        self.assertEqual((self.fixture.source / "Git/new.txt").read_text(), "new-work")
        self.assert_pending_blocks_writes()

    def test_component_sigkill_before_move_keeps_backup_and_blocks_full_retry(self):
        skill = self.fixture.source / ".agents/skills/example"
        target = self.fixture.target / ".agents/skills/example"
        skill.mkdir(parents=True)
        target.mkdir(parents=True)
        (skill / "SKILL.md").write_text("new skill")
        (target / "SKILL.md").write_text("old skill")
        stage = self.fixture.target / "component-stage"
        shutil.copytree(skill, stage / "items/0")
        (stage / ".codex-migrate-owner").write_text("a" * 32)
        item = SkillExport("example", str(skill), str(target), "user")
        exporter = ComponentExporter(self.fixture.config, ["personal-skills"])
        exporter.transport = self.engine.transport
        quoted = shlex.quote(str(target))
        self.inject(lambda script: script.replace("rm -rf " + quoted + "\nmv ",
                                                 "rm -rf " + quoted + "\nkill -KILL $$\nmv "))
        with self.assertRaises(RuntimeError):
            exporter._install([item], str(stage), "a" * 32)
        self.assertFalse(target.exists())
        record = json.loads(self.journal.read_text())
        self.assertEqual((Path(record["backup"]) / "items/0/SKILL.md").read_text(), "old skill")
        self.assert_pending_blocks_writes()

    def corrupt_installed(self, script):
        codex = shlex.quote(str(self.fixture.target / ".codex"))
        staging = shlex.quote(str(self.fixture.stage / ".codex"))
        needle = "mv " + staging + " " + codex
        return script.replace(needle, needle + "\nprintf changed > " + codex + "/sessions/chat.jsonl")

    def test_normal_rollback_is_verified_and_archived(self):
        self.inject(self.corrupt_installed)
        with self.assertRaisesRegex(RuntimeError, "rollback was verified"):
            self.engine._install_and_verify()
        self.assertFalse(self.journal.exists())
        backup = Path(self.fixture.state.read()["pending_backup"])
        self.assertEqual(json.loads((backup / "transaction-receipt.json").read_text())["phase"], "restored")
        self.assertEqual((self.fixture.target / ".codex/old.txt").read_text(), "original")

    def test_failed_rollback_keeps_pending_and_does_not_claim_verified(self):
        codex = shlex.quote(str(self.fixture.target / ".codex"))
        def fault(script):
            script = self.corrupt_installed(script)
            # Fail only rollback cloning, not the initial backup or identity copy.
            return script.replace("cp -c -R ", "fixture_cp -c -R ").replace(
                "setopt NULL_GLOB", "setopt NULL_GLOB\nfixture_cp() { if test \"${4-}\" = " + codex
                + "; then return 74; fi; command cp \"$@\"; }")
        self.inject(fault)
        with self.assertRaisesRegex(RuntimeError, "rollback is unconfirmed") as error:
            self.engine._install_and_verify()
        self.assertNotIn("rollback was verified", str(error.exception))
        self.assertTrue(self.journal.exists())
        self.assert_pending_blocks_writes()

    def test_durability_failure_blocks_before_removal(self):
        self.inject(lambda script: script.replace("defined fcntl($fh, 51, 0) or fail();", "fail();"))
        with self.assertRaisesRegex(RuntimeError, "recovery evidence"):
            self.engine._install_and_verify()
        self.fixture.assert_originals_untouched()
        self.assert_pending_blocks_writes()

    def test_codex_reopened_during_durable_backup_blocks_removal(self):
        original = self.engine.transport.run_remote
        # The normal fixture replaces ps before execution. Add a competing
        # fixture definition just after the journal's successful publication.
        definition = ("fixture_ps() { if test -e " + shlex.quote(str(self.journal))
                      + "; then n=codex; else n=zsh; fi; printf '%s /bin/%s\\n' \"$(/usr/bin/id -u)\" \"$n\"; }\n")
        def fault(script, timeout=60):
            script = script.replace("cm_transaction begin || exit 78\n",
                                    "cm_transaction begin || exit 78\n" + definition)
            return original(script, timeout)
        self.engine.transport.run_remote = fault
        with self.assertRaisesRegex(RuntimeError, "Codex is running"):
            self.engine._install_and_verify()
        self.fixture.assert_originals_untouched()
        self.assert_pending_blocks_writes()

    def test_final_clear_failure_never_triggers_rollback_after_durable_install(self):
        self.inject(lambda script: script.replace("unlink($journal) or fail();",
                                                 "unlink($journal) or fail(); fail();"))
        with self.assertRaisesRegex(RuntimeError, "recovery evidence") as error:
            self.engine._install_and_verify()
        self.assertNotIn("rollback was verified", str(error.exception))
        self.assertFalse(self.journal.exists())
        self.assertTrue((self.fixture.target / "Git/new.txt").exists())
        backup = Path(self.fixture.state.read()["pending_backup"])
        self.assertEqual(json.loads((backup / "transaction-receipt.json").read_text())["phase"], "installed")

    def test_installed_evidence_failure_runs_verified_full_rollback(self):
        runner = TRANSACTION_RUNNER.replace("$record->{phase} = $mode;",
                    "if ($mode eq 'installed') { fail(); }\n$record->{phase} = $mode;")
        with patch("codex_migrate.transaction.TRANSACTION_RUNNER", runner):
            with self.assertRaisesRegex(RuntimeError, "rollback was verified"):
                self.engine._install_and_verify()
        self.assertFalse(self.journal.exists())
        self.assertEqual((self.fixture.target / ".codex/old.txt").read_text(), "original")
        self.assertEqual((self.fixture.target / "Git/old.txt").read_text(), "original-work")
        backup = Path(self.fixture.state.read()["pending_backup"])
        self.assertEqual(json.loads((backup / "transaction-receipt.json").read_text())["phase"], "restored")

    def test_installed_evidence_failure_runs_verified_component_rollback(self):
        skill = self.fixture.source / ".agents/skills/example"
        target = self.fixture.target / ".agents/skills/example"
        skill.mkdir(parents=True)
        target.mkdir(parents=True)
        (skill / "SKILL.md").write_text("new skill")
        (target / "SKILL.md").write_text("old skill")
        stage = self.fixture.target / "component-stage"
        backup = self.fixture.target / "component-backup"
        shutil.copytree(skill, stage / "items/0")
        (stage / ".codex-migrate-owner").write_text("a" * 32)
        exporter = ComponentExporter(self.fixture.config, ["personal-skills"])
        exporter.transport = self.engine.transport
        item = SkillExport("example", str(skill), str(target), "user")
        runner = TRANSACTION_RUNNER.replace("$record->{phase} = $mode;",
                    "if ($mode eq 'installed') { fail(); }\n$record->{phase} = $mode;")
        with patch("codex_migrate.transaction.TRANSACTION_RUNNER", runner):
            with self.assertRaisesRegex(RuntimeError, "rollback was verified"):
                exporter._install([item], str(stage), "a" * 32, backup=str(backup))
        self.assertFalse(self.journal.exists())
        self.assertEqual((target / "SKILL.md").read_text(), "old skill")
        self.assertEqual(json.loads((backup / "transaction-receipt.json").read_text())["phase"], "restored")

    def test_corrupted_journal_does_not_leak_content_or_clear_recovery(self):
        def fault(script):
            return script.replace("\ncm_transaction installed || exit 78\n",
                "\nprintf PRIVATE_SENTINEL > " + shlex.quote(str(self.journal)) + "\ncm_transaction installed || exit 78\n")
        self.inject(fault)
        with self.assertRaisesRegex(RuntimeError, "recovery evidence") as error:
            self.engine._install_and_verify()
        self.assertNotIn("PRIVATE_SENTINEL", str(error.exception))
        self.assertTrue(self.journal.exists())
        self.assert_pending_blocks_writes()

    def test_malformed_or_linked_pending_record_never_allows_writes(self):
        outside = self.fixture.root / "not-created"
        for kind in ("corrupt", "symlink", "directory", "fifo"):
            with self.subTest(kind=kind):
                if kind == "corrupt":
                    self.journal.write_text("PRIVATE invalid journal")
                elif kind == "symlink":
                    self.journal.symlink_to(outside)
                elif kind == "directory":
                    self.journal.mkdir()
                else:
                    os.mkfifo(self.journal, 0o600)
                try:
                    self.assert_pending_blocks_writes()
                    self.assertFalse(outside.exists())
                finally:
                    self.journal.rmdir() if kind == "directory" else self.journal.unlink()


if __name__ == "__main__":
    unittest.main()
