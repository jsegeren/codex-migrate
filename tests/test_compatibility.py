"""Real symlink syscalls in disposable directories, never /Users or sudo."""

import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from codex_migrate.compatibility import RUNNER, check_compatibility, compatibility_command


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.new = self.root / "new"
        self.new.mkdir()
        self.old = self.root / "old"
        self.records = [{"dsAttrTypeStandard:UniqueID": [str(os.getuid())],
                         "dsAttrTypeStandard:RecordName": ["person"],
                         "dsAttrTypeStandard:NFSHomeDirectory": [str(self.new)]}]

    def run_script(self, mode="inspect", before_create="", records=None, runner=RUNNER, apply=True):
        # Only the Users root, root ownership/privilege guards and account
        # provider are substituted. Actual lstat/stat/symlink remain intact.
        # Production accepts no fixture override or environment switch.
        account_file = self.root / "accounts.json"
        account_file.write_text(json.dumps(self.records if records is None else records))
        script = runner.replace("my $users_root = '/Users';", "my $users_root = " + json.dumps(str(self.root)) + ";")
        script = script.replace("$parent[4] == 0", "$parent[4] == $<")
        script = script.replace("$< == 0 && $> == 0", "$< == $home[4] && $> == $home[4]")
        start = script.index("open(my $accounts, '-|'")
        end = script.index(" or fail();", start)
        script = script[:start] + "open(my $accounts, '<', " + json.dumps(str(account_file)) + ")" + script[end:]
        script = script.replace("symlink(fs($new), fs($old)) or fail();", before_create + "\nsymlink(fs($new), fs($old)) or fail();")
        return subprocess.run(["/usr/bin/perl", "-e", script, "--", mode, str(self.old), str(self.new), "person"] + (["--apply"] if mode == "create" and apply else []),
                              capture_output=True, text=True, timeout=10)

    def status(self, **kwargs):
        result = self.run_script(**kwargs)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)["status"]

    def test_same_missing_created_and_rechecked(self):
        self.assertEqual(self.status(), "missing")
        self.assertFalse(self.old.exists())
        self.assertEqual(self.status(mode="create"), "mapped")
        self.assertEqual(os.readlink(self.old), str(self.new))
        self.assertEqual(self.status(), "mapped")
        self.old = self.new
        self.assertEqual(self.status(), "not_needed")

    def test_creation_requires_explicit_apply(self):
        self.assertNotEqual(self.run_script(mode="create", apply=False).returncode, 0)
        self.assertFalse(self.old.exists())

    def test_existing_entries_are_never_overwritten_or_nested(self):
        makers = (lambda: self.old.mkdir(), lambda: self.old.write_text("keep"),
                  lambda: os.mkfifo(self.old), lambda: self.old.symlink_to("missing"),
                  lambda: self.old.symlink_to(self.old), lambda: self.old.symlink_to(self.root))
        for maker in makers:
            maker()
            before = self.old.lstat()
            self.assertEqual(self.status(mode="create"), "conflict")
            self.assertEqual(self.old.lstat().st_ino, before.st_ino)
            if self.old.is_dir() and not self.old.is_symlink():
                self.assertEqual(list(self.old.iterdir()), [])
                self.old.rmdir()
            else:
                self.old.unlink()

    def test_late_directory_or_link_cannot_nest_or_replace(self):
        for injection in ("mkdir(fs($old)) or fail();", "symlink('untouched', fs($old)) or fail();"):
            result = self.run_script(mode="create", before_create=injection)
            self.assertNotEqual(result.returncode, 0)
            if self.old.is_symlink():
                self.assertEqual(os.readlink(self.old), "untouched")
                self.old.unlink()
            else:
                self.assertEqual(list(self.old.iterdir()), [])
                self.old.rmdir()

    def test_other_account_claim_blocks_even_when_home_is_missing(self):
        self.records.append({"dsAttrTypeStandard:UniqueID": [str(os.getuid() + 1)],
                             "dsAttrTypeStandard:RecordName": ["other"],
                             "dsAttrTypeStandard:NFSHomeDirectory": [str(self.old)]})
        self.assertEqual(self.status(mode="create"), "conflict")
        self.assertFalse(self.old.exists())

    def test_unicode_quotes_spaces_and_shell_characters(self):
        self.old = self.root / "old é ' $(touch SHOULD_NOT_EXIST)"
        renamed = self.root / "new 雪 ' ; value"
        self.new.rename(renamed)
        self.new = renamed
        self.records[0]["dsAttrTypeStandard:NFSHomeDirectory"] = [str(renamed)]
        self.assertEqual(self.status(mode="create"), "mapped")
        self.assertEqual(self.status(), "mapped")
        self.assertEqual(os.readlink(self.old), str(renamed))
        self.assertFalse((self.root / "SHOULD_NOT_EXIST").exists())

    def test_bad_account_evidence_and_aliased_target_fail_closed(self):
        for records in ([], {}, [{"private": "PRIVATE"}], self.records + [{"dsAttrTypeStandard:UniqueID": ["bad"]}]):
            result = self.run_script(mode="create", records=records)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("PRIVATE", result.stderr)
            self.assertFalse(self.old.exists())
        real = self.root / "real"
        self.new.rename(real)
        self.new.symlink_to(real)
        self.assertNotEqual(self.run_script(mode="create").returncode, 0)
        self.assertFalse(self.old.exists())

    def test_custom_paths_offer_no_privileged_command(self):
        config = SimpleNamespace(source_home="/Volumes/old/person", target_home="/Users/person", target="person@host")
        report = dict(status="missing", source_home=config.source_home, target_home=config.target_home)
        self.assertIsNone(compatibility_command(config, report))
        config.source_home = "/Users/old"
        report["source_home"] = config.source_home
        command = compatibility_command(config, report)
        self.assertTrue(command.startswith("sudo /usr/bin/env "))
        self.assertNotIn("ln -s", command)
        self.assertEqual(shlex.split(command)[-5:], ["create", "/Users/old", "/Users/person", "person", "--apply"])
        for status in ("mapped", "conflict", "unverified", "unsupported"):
            report["status"] = status
            self.assertIsNone(compatibility_command(config, report))

    def test_remote_failure_or_malformed_report_is_unverified_not_success(self):
        config = SimpleNamespace(source_home="/Users/old", target_home="/Users/person", target="person@host")
        transport = SimpleNamespace(run_remote=lambda *args, **kwargs: None)
        for result in ("PRIVATE", '{"status":"mapped","extra":"PRIVATE"}', '{}', '[]', 'x' * 1025):
            with patch.object(transport, "run_remote", return_value=SimpleNamespace(stdout=result)):
                report = check_compatibility(config, transport)
            self.assertEqual(report["status"], "unverified")
            self.assertNotIn("PRIVATE", str(report))


if __name__ == "__main__":
    unittest.main()
