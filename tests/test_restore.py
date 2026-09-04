"""Actual restore/interrupt/resume operations use disposable APFS data only."""

from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch

import test_recovery as fixtures
from process_fixtures import closed_codex_script
from codex_migrate.errors import MigrationError
from codex_migrate.processes import require_codex_closed_script
from codex_migrate.restore import RESTORE_RUNNER, restore_recovery
from codex_migrate.transaction import TRANSACTION_RUNNER


class RestoreTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RecoveryTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.record = self.fixture.interrupt()
        self.home = self.fixture.home
        self.backup = Path(self.record["backup"])
        self.root = self.backup / ("recovery-" + self.record["id"])
        self.inspection = self.fixture.inspect()
        self.config = self.fixture.fixture.config
        # Guard executes in its own child shell; substitute only its process
        # snapshot. Real owner/non-root checks stay in place.
        self.guard = closed_codex_script(require_codex_closed_script(str(self.home)))
        self.transport = self.fixture.engine.transport

    def restore(self, runner=RESTORE_RUNNER, guard=None, config=None):
        with patch("codex_migrate.restore.RESTORE_RUNNER", runner), \
             patch("codex_migrate.restore.require_codex_closed_script", return_value=guard or self.guard):
            return restore_recovery(config or self.config, self.transport, self.inspection)

    def newer_work(self):
        codex = self.home / ".codex"
        codex.mkdir()
        (codex / "auth.json").write_text("new-fixture-auth")
        (codex / "installation_id").write_text("new-fixture-id")
        (codex / "new-work.txt").write_text("new conversation fixture")
        (self.home / "Git/new-work.txt").write_text("newer Git work")

    def assert_restored(self, newer=False):
        self.assertEqual((self.home / ".codex/old.txt").read_text(), "original")
        self.assertEqual((self.home / "Git/old.txt").read_text(), "original-work")
        self.assertFalse(self.fixture.journal.exists())
        self.assertTrue((self.root / "complete.json").exists())
        prefix = "new-" if newer else ""
        self.assertEqual((self.home / ".codex/auth.json").read_text(), prefix + "fixture-auth")
        self.assertEqual((self.home / ".codex/installation_id").read_text(), prefix + "fixture-id")
        if newer:
            self.assertEqual((self.root / "current/0/new-work.txt").read_text(), "new conversation fixture")
            self.assertEqual((self.root / "current/1/new-work.txt").read_text(), "newer Git work")
            self.assertFalse((self.home / ".codex/new-work.txt").exists())
        # Original destination backup and source are never changed.
        self.assertEqual((self.backup / ".codex/auth.json").read_text(), "fixture-auth")
        self.assertEqual((self.fixture.fixture.source / "Git/new.txt").read_text(), "new-work")

    def test_restore_missing_codex_and_preserve_existing_workspace(self):
        result = self.restore()
        self.assertEqual(result["status"], "restored")
        self.assert_restored()
        self.assertEqual((self.root / "current/1/old.txt").read_text(), "original-work")
        self.assertNotIn("digest", json.dumps(result))
        self.assertNotIn("fixture-auth", json.dumps(result))

    def test_newer_destination_files_and_identity_are_preserved(self):
        self.newer_work()
        self.restore()
        self.assert_restored(newer=True)

    def test_current_logout_or_identity_reset_is_not_undone(self):
        self.newer_work()
        (self.home / ".codex/auth.json").unlink()
        (self.home / ".codex/installation_id").unlink()
        self.restore()
        self.assertFalse((self.home / ".codex/auth.json").exists())
        self.assertFalse((self.home / ".codex/installation_id").exists())
        self.assertTrue((self.home / ".codex/old.txt").exists())
        self.assertTrue((self.backup / ".codex/auth.json").exists())

    def test_apply_and_exact_inspected_scope_are_required(self):
        with patch.object(self.transport, "run_remote") as remote:
            with self.assertRaisesRegex(MigrationError, "explicit --apply"):
                self.restore(config=replace(self.config, apply=False))
            remote.assert_not_called()
        self.inspection["transaction_id"] = "f" * 32
        with self.assertRaises(MigrationError):
            self.restore()
        self.assertFalse(self.root.exists())
        self.assertTrue(self.fixture.journal.exists())

    def test_process_guard_blocks_without_recovery_writes(self):
        with self.assertRaises(MigrationError):
            self.restore(guard="exit 70")
        self.assertFalse(self.root.exists())
        self.assertTrue(self.fixture.journal.exists())

    def test_low_space_stops_before_preparation(self):
        runner = RESTORE_RUNNER.replace("$fields[3] * 1024 >= $required or fail();", "fail();")
        with self.assertRaises(MigrationError):
            self.restore(runner)
        self.assertFalse(self.root.exists())
        self.assertFalse((self.home / ".codex").exists())

    def test_changed_backup_blocks_restoration(self):
        (self.backup / ".codex/old.txt").write_text("corrupted fixture")
        with self.assertRaises(MigrationError):
            self.restore()
        self.assertFalse(self.root.exists())
        self.assertFalse((self.home / ".codex").exists())

    def test_absent_old_codex_root_cannot_remove_new_login(self):
        # Unsupported evidence can describe a previously absent Codex root.
        # Retain even the fixture backup while constructing that scenario.
        (self.backup / ".codex").rename(self.backup / "retained-fixture-copy")
        item = self.record["scope"][0]
        self.assertEqual(item["original"], str(self.home / ".codex"))
        item.update(existed=False, backup_digest=None)
        self.fixture.journal.write_text(json.dumps(self.record))
        self.inspection = self.fixture.inspect()
        self.newer_work()
        with self.assertRaises(MigrationError):
            self.restore()
        self.assertEqual((self.home / ".codex/auth.json").read_text(), "new-fixture-auth")
        self.assertFalse(self.root.exists())

    def test_identity_alias_blocks_without_following_it(self):
        self.newer_work()
        auth = self.home / ".codex/auth.json"
        auth.unlink()
        auth.symlink_to(self.home / "Git/old.txt")
        with self.assertRaises(MigrationError):
            self.restore()
        self.assertTrue(auth.is_symlink())
        self.assertFalse(self.root.exists())
        self.assertEqual((self.home / "Git/old.txt").read_text(), "original-work")

    def test_resume_after_preserving_current_entry(self):
        self.newer_work()
        runner = RESTORE_RUNNER.replace("move_new($original, $saved, $ready_path);",
                                        "move_new($original, $saved, $ready_path); kill 9, $$;")
        with self.assertRaises(MigrationError):
            self.restore(runner)
        self.assertTrue(self.fixture.journal.exists())
        self.assertFalse((self.home / ".codex").exists())
        self.assertTrue((self.root / "current/0/new-work.txt").exists())
        self.restore()
        self.assert_restored(newer=True)

    def test_resume_after_installing_restored_entry(self):
        self.newer_work()
        runner = RESTORE_RUNNER.replace("move_new($prepared, $original, $ready_path);",
                                        "move_new($prepared, $original, $ready_path); kill 9, $$;")
        with self.assertRaises(MigrationError):
            self.restore(runner)
        self.assertTrue(self.fixture.journal.exists())
        self.restore()
        self.assert_restored(newer=True)

    def test_resume_after_plan_is_saved(self):
        self.newer_work()
        runner = RESTORE_RUNNER.replace("owned_directory($root . '/prepared', 1);",
                                        "kill 9, $$; owned_directory($root . '/prepared', 1);")
        with self.assertRaises(MigrationError):
            self.restore(runner)
        self.assertTrue((self.root / "plan.json").exists())
        self.restore()
        self.assert_restored(newer=True)

    def test_resume_after_candidate_copy_keeps_incomplete_copy(self):
        self.newer_work()
        runner = RESTORE_RUNNER.replace("verify_frozen($item, $candidate);",
                                        "kill 9, $$; verify_frozen($item, $candidate);")
        with self.assertRaises(MigrationError):
            self.restore(runner)
        self.restore()
        self.assert_restored(newer=True)
        self.assertTrue((self.root / "incomplete/0/old.txt").exists())

    def test_changed_original_after_preparation_blocks_all_moves(self):
        self.newer_work()
        runner = RESTORE_RUNNER.replace("# This check runs again", "kill 9, $$;\n# This check runs again")
        with self.assertRaises(MigrationError):
            self.restore(runner)
        (self.home / "Git/new-work.txt").write_text("latest work")
        with self.assertRaises(MigrationError):
            self.restore()
        self.assertFalse(list((self.root / "current").iterdir()))
        self.assertEqual((self.home / "Git/new-work.txt").read_text(), "latest work")

    def test_recreated_original_after_move_is_never_overwritten(self):
        self.newer_work()
        runner = RESTORE_RUNNER.replace("move_new($original, $saved, $ready_path);",
                                        "move_new($original, $saved, $ready_path); kill 9, $$;")
        with self.assertRaises(MigrationError):
            self.restore(runner)
        (self.home / ".codex").mkdir()
        (self.home / ".codex/latest.txt").write_text("work after interruption")
        with self.assertRaises(MigrationError):
            self.restore()
        self.assertEqual((self.home / ".codex/latest.txt").read_text(), "work after interruption")
        self.assertTrue((self.root / "current/0/new-work.txt").exists())

    def test_resume_after_complete_record_before_journal_cleanup(self):
        self.newer_work()
        runner = RESTORE_RUNNER.replace("unlink(filesystem_path($journal)) or fail();", "kill 9, $$;")
        with self.assertRaises(MigrationError):
            self.restore(runner)
        self.assertTrue((self.root / "complete.json").exists())
        self.assertTrue(self.fixture.journal.exists())
        self.restore()
        self.assert_restored(newer=True)

    def test_process_reopened_during_validation_blocks_rename(self):
        self.newer_work()
        marker = self.home / "fixture-writer-open"
        runner = RESTORE_RUNNER.replace(
            "if ($old->{existed} && !present($saved)) {",
            "open(my $marker, '>', filesystem_path($home . '/fixture-writer-open')) or fail(); close($marker);\n"
            "    if ($old->{existed} && !present($saved)) {")
        with self.assertRaises(MigrationError):
            self.restore(runner, guard=self.guard + '\ntest ! -e "' + str(marker) + '"\n')
        self.assertTrue((self.home / ".codex/new-work.txt").exists())
        self.assertFalse(list((self.root / "current").iterdir()))

    def test_resuming_reflushes_ready_before_any_current_move(self):
        self.newer_work()
        # Die with ready.json visible, before save_new syncs its parent/device.
        runner = RESTORE_RUNNER.replace("flush_parent($path);\n    defined fcntl($fh, 51, 0)",
            "kill 9, $$ if $path =~ m{/ready[.]json$};\n    flush_parent($path);\n    defined fcntl($fh, 51, 0)")
        with self.assertRaises(MigrationError):
            self.restore(runner)
        self.assertTrue((self.root / "ready.json").exists())
        # Prove a failed replay barrier blocks current-path mutation.
        blocked = RESTORE_RUNNER.replace("my $fh = handle($evidence);",
            "fail() if $evidence =~ m{/ready[.]json$};\n    my $fh = handle($evidence);")
        with self.assertRaises(MigrationError):
            self.restore(blocked)
        self.assertFalse(list((self.root / "current").iterdir()))
        self.restore()
        self.assert_restored(newer=True)

    def test_incomplete_metadata_write_is_preserved_and_retried(self):
        self.newer_work()
        runner = RESTORE_RUNNER.replace("$fh->sync or fail();\n    exclusive_rename($temp, $path)",
                                        "$fh->sync or fail(); kill 9, $$;\n    exclusive_rename($temp, $path)")
        with self.assertRaises(MigrationError):
            self.restore(runner)
        self.assertFalse((self.root / "plan.json").exists())
        self.restore()
        self.assert_restored(newer=True)
        self.assertTrue((self.root / "incomplete/0").is_file())

    def test_damaged_prepared_or_preserved_data_fails_closed(self):
        self.newer_work()
        runner = RESTORE_RUNNER.replace("move_new($original, $saved, $ready_path);",
                                        "move_new($original, $saved, $ready_path); kill 9, $$;")
        with self.assertRaises(MigrationError):
            self.restore(runner)
        for relative in ("prepared/0/old.txt", "current/0/new-work.txt"):
            path = self.root / relative
            original = path.read_bytes()
            path.write_bytes(b"changed fixture")
            with self.assertRaises(MigrationError):
                self.restore()
            self.assertTrue(self.fixture.journal.exists())
            self.assertFalse((self.home / ".codex").exists())
            path.write_bytes(original)
        self.restore()
        self.assert_restored(newer=True)

    def test_unknown_recovery_folder_is_not_adopted(self):
        self.root.mkdir(mode=0o700)
        (self.root / "important.txt").write_text("unrelated fixture")
        with self.assertRaises(MigrationError):
            self.restore()
        self.assertEqual((self.root / "important.txt").read_text(), "unrelated fixture")
        self.assertFalse((self.root / "plan.json").exists())

    def test_skill_link_absent_original_file_and_unicode_mapping(self):
        # A second, independent disposable recovery account; no prior fixture
        # journal is overwritten to invent a different scope.
        home = self.home / "café-测试"
        originals = home / ".agents/skills"
        originals.mkdir(parents=True)
        referent = home / "untouched"
        referent.mkdir()
        (referent / "SKILL.md").write_text("not in replacement scope")
        link = originals / "lié"
        link.symlink_to(referent)
        ordinary = originals / "fichier"
        ordinary.write_text("old regular file")
        ordinary.chmod(0o640)
        missing = originals / "missing"
        backup = home / "sauvegarde"
        backup.mkdir(mode=0o700)
        (backup / "0").symlink_to(referent)
        shutil.copy2(ordinary, backup / "1")
        (home / ".codex-migrate-destination.lock").touch(mode=0o600)
        mappings = [{"original": str(p), "backup": str(backup / str(i))}
                    for i, p in enumerate((link, ordinary, missing))]
        plan = {"format": 2, "id": "b" * 32, "home": str(home), "backup": str(backup), "scope": mappings}
        begin = subprocess.run(["/usr/bin/perl", "-e", TRANSACTION_RUNNER, "--", "begin", json.dumps(plan)],
                               capture_output=True, text=True, timeout=5)
        self.assertEqual(begin.returncode, 0, begin.stderr)
        link.unlink()
        link.mkdir()
        (link / "SKILL.md").write_text("newer materialized skill")
        ordinary.write_text("newer regular file")
        missing.mkdir()
        (missing / "new.txt").write_text("new skill with no prior backup")
        from codex_migrate.recovery import inspect_recovery
        config = replace(self.config, target_home=str(home))
        inspection = inspect_recovery(config, self.transport)
        with patch("codex_migrate.restore.require_codex_closed_script",
                   return_value=closed_codex_script(require_codex_closed_script(str(home)))):
            race = RESTORE_RUNNER.replace("exclusive_rename($from, $to);",
                "if ($from =~ m{/prepared/0$}) {\n"
                "  open(my $newer, '>', filesystem_path($to)) or fail();\n"
                "  print $newer 'work created during rename'; close($newer);\n"
                "}\n    exclusive_rename($from, $to);")
            with patch("codex_migrate.restore.RESTORE_RUNNER", race):
                with self.assertRaises(MigrationError):
                    restore_recovery(config, self.transport, inspection)
            # Atomic exclusive rename must retain both the new file and the
            # prepared old symlink, even when it appears AFTER every check.
            self.assertEqual(link.read_text(), "work created during rename")
            recovery = backup / ("recovery-" + "b" * 32)
            self.assertTrue((recovery / "prepared/0").is_symlink())
            self.assertEqual((recovery / "current/0/SKILL.md").read_text(), "newer materialized skill")
            # Explicit fixture-only preservation resolves the new conflict.
            link.rename(home / "race-work-preserved")
            result = restore_recovery(config, self.transport, inspection)
        self.assertEqual(result["status"], "restored")
        self.assertTrue(link.is_symlink())
        self.assertEqual(os.readlink(link), str(referent))
        self.assertEqual(ordinary.read_text(), "old regular file")
        self.assertEqual(ordinary.stat().st_mode & 0o777, 0o640)
        self.assertFalse(missing.exists())
        saved = Path(result["preserved"])
        self.assertEqual((saved / "0/SKILL.md").read_text(), "newer materialized skill")
        self.assertEqual((saved / "1").read_text(), "newer regular file")
        self.assertEqual((saved / "2/new.txt").read_text(), "new skill with no prior backup")
        self.assertEqual((referent / "SKILL.md").read_text(), "not in replacement scope")
        self.assertEqual((home / "race-work-preserved").read_text(), "work created during rename")


if __name__ == "__main__":
    unittest.main()
