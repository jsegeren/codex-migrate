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
from codex_migrate.workspaces import freeze_tree


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
        self.assertEqual(record["format"], 2)
        self.assertTrue(all(item["existed"] for item in record["scope"]))
        for item in record["scope"]:
            self.assertEqual(item["backup_digest"], freeze_tree(item["backup"]))
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
        self.assertIsNone(workspace["backup_digest"])
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

    def test_backup_and_rollback_preserve_permission_bits(self):
        target = self.fixture.target / "Git"
        target.chmod(0o750)
        (target / "old.txt").chmod(0o640)
        self.inject(self.corrupt_installed)
        with self.assertRaisesRegex(RuntimeError, "rollback was verified"):
            self.engine._install_and_verify()
        self.assertEqual(target.stat().st_mode & 0o777, 0o750)
        self.assertEqual((target / "old.txt").stat().st_mode & 0o777, 0o640)

    def test_corrupted_backup_blocks_rollback_before_any_current_data_removal(self):
        def fault(script):
            backup = Path(self.fixture.state.read()["pending_backup"])
            return script.replace("\ncm_transaction installed || exit 78\n",
                "\nprintf CORRUPTED > " + shlex.quote(str(backup / "home-relative/Git/old.txt"))
                + "\ncm_transaction installed || exit 78\n")
        self.inject(fault)
        with self.assertRaisesRegex(RuntimeError, "rollback is unconfirmed") as error:
            self.engine._install_and_verify()
        self.assertNotIn("CORRUPTED", str(error.exception))
        self.assertEqual((self.fixture.target / "Git/new.txt").read_text(), "new-work")
        self.assertTrue((self.fixture.target / ".codex/sessions/chat.jsonl").exists())
        self.assertEqual((self.fixture.target / ".codex/auth.json").read_text(), "fixture-auth")
        self.assert_pending_blocks_writes()

    def frozen_fixture(self):
        """No real credentials or network: exercise the remote helper directly."""
        original = self.fixture.target / "Git"
        backup = self.fixture.target / "frozen-backup"
        backup.mkdir()
        shutil.copytree(original, backup / "Git", symlinks=True)
        plan = {"format": 2, "id": "b" * 32, "home": str(self.fixture.target),
                "backup": str(backup),
                "scope": [{"original": str(original), "backup": str(backup / "Git")}]}
        self.assertEqual(self.run_transaction("begin", plan).returncode, 0)
        return plan, backup / "Git"

    def run_transaction(self, mode, plan):
        return subprocess.run(["/usr/bin/perl", "-e", TRANSACTION_RUNNER, "--", mode, json.dumps(plan)],
                              capture_output=True, text=True, timeout=5)

    def test_frozen_evidence_detects_changed_content_names_modes_links_and_absence(self):
        original = self.fixture.target / "Git"
        (original / "empty").mkdir()
        (original / "alias").symlink_to("old.txt")
        plan, copy = self.frozen_fixture()
        mutations = {
            "bytes": lambda: (copy / "old.txt").write_text("PRIVATE_CHANGED"),
            "added": lambda: (copy / "new").write_text("PRIVATE_ADDED"),
            "deleted": lambda: (copy / "old.txt").unlink(),
            "file_mode": lambda: (copy / "old.txt").chmod(0o600),
            "root_mode": lambda: copy.chmod(0o700),
            "empty_directory": lambda: (copy / "empty").rmdir(),
            "link": lambda: ((copy / "alias").unlink(), (copy / "alias").symlink_to("changed")),
            "missing": lambda: shutil.rmtree(copy),
            "root_link": lambda: (shutil.rmtree(copy), copy.symlink_to(original)),
            "fifo": lambda: os.mkfifo(copy / "pipe"),
        }
        record = self.journal.read_bytes()
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                self.assertEqual(self.run_transaction("check-backup", plan).returncode, 0)
                mutate()
                result = self.run_transaction("check-backup", plan)
                self.assertEqual(result.returncode, 78)
                self.assertEqual(result.stdout, "")
                self.assertNotIn("PRIVATE", result.stderr)
                self.assertEqual(self.journal.read_bytes(), record)
                if copy.is_symlink():
                    copy.unlink()
                elif copy.exists():
                    shutil.rmtree(copy)
                shutil.copytree(original, copy, symlinks=True)

    def test_restored_must_match_frozen_digest_not_just_backup(self):
        plan, copy = self.frozen_fixture()
        (self.fixture.target / "Git/old.txt").write_text("PRIVATE_CHANGED")
        result = self.run_transaction("restored", plan)
        self.assertEqual(result.returncode, 78)
        self.assertFalse((copy.parent / "transaction-receipt.json").exists())
        self.assertTrue(self.journal.exists())

    def test_unexpected_backup_for_previously_absent_item_is_rejected(self):
        backup = self.fixture.target / "absent-backup"
        backup.mkdir()
        original = self.fixture.target / "absent-original"
        copy = backup / "absent"
        plan = {"format": 2, "id": "d" * 32, "home": str(self.fixture.target),
                "backup": str(backup),
                "scope": [{"original": str(original), "backup": str(copy)}]}
        self.assertEqual(self.run_transaction("begin", plan).returncode, 0)
        self.assertEqual(self.run_transaction("check-backup", plan).returncode, 0)
        copy.mkdir()
        self.assertEqual(self.run_transaction("check-backup", plan).returncode, 78)
        self.assertTrue(self.journal.exists())
        self.assertFalse(original.exists())

    def test_old_or_missing_fingerprint_record_cannot_authorize_restore(self):
        plan, copy = self.frozen_fixture()
        original = json.loads(self.journal.read_text())
        for kind in ("legacy", "missing", "invalid", "false_existence"):
            with self.subTest(kind=kind):
                record = json.loads(json.dumps(original))
                if kind == "legacy":
                    record["format"] = 1
                elif kind == "missing":
                    del record["scope"][0]["backup_digest"]
                elif kind == "invalid":
                    record["scope"][0]["backup_digest"] = "PRIVATE_INVALID"
                else:
                    record["scope"][0]["existed"] = "true"
                self.journal.write_text(json.dumps(record))
                result = self.run_transaction("check-backup", plan)
                self.assertEqual(result.returncode, 78)
                self.assertNotIn("PRIVATE", result.stderr)
                self.assertTrue((copy / "old.txt").exists())

    def test_reading_frozen_evidence_does_not_follow_linked_backup_parent(self):
        plan, copy = self.frozen_fixture()
        moved = self.fixture.target / "moved-backup"
        copy.parent.rename(moved)
        copy.parent.symlink_to(moved)
        result = self.run_transaction("check-backup", plan)
        self.assertEqual(result.returncode, 78)
        self.assertTrue(self.journal.exists())

    def test_unicode_home_backup_and_item_paths_keep_json_and_filesystem_identity(self):
        for label in ("café", "测试", "e\u0301"):
            with self.subTest(label=label):
                home = self.fixture.target / label
                original = home / "données-测试"
                original.mkdir(parents=True)
                (original / "empty-é").mkdir()
                (original / "naïve\n测试").write_text("fixture unicode contents")
                (original / "lien-é").symlink_to("naïve\n测试")
                backup = home / "sauvegarde-测试"
                backup.mkdir()
                copy = backup / "copie-é"
                shutil.copytree(original, copy, symlinks=True)
                plan = {"format": 2, "id": "c" * 32, "home": str(home),
                        "backup": str(backup),
                        "scope": [{"original": str(original), "backup": str(copy)}]}
                for mode in ("begin", "check-backup", "restored", "clear"):
                    result = self.run_transaction(mode, plan)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, "")
                record = json.loads((backup / "transaction-receipt.json").read_text())
                self.assertEqual(record["home"], str(home))
                self.assertEqual(record["scope"][0]["backup_digest"], freeze_tree(str(copy)))
                self.assertFalse((home / TRANSACTION_NAME).exists())

    def test_failed_rollback_keeps_pending_and_does_not_claim_verified(self):
        codex = shlex.quote(str(self.fixture.target / ".codex"))
        def fault(script):
            script = self.corrupt_installed(script)
            # Fail only rollback cloning, not the initial backup or identity copy.
            return script.replace("cp -c -Rp ", "fixture_cp -c -Rp ").replace(
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
