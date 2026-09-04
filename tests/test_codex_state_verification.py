"""Retained Codex state checks with disposable data and real local rsync/APFS."""
import os
from pathlib import Path
import platform
import shlex
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import test_full_skills as fixtures
from codex_migrate.errors import MigrationError
from codex_migrate.exclusions import CODEX_EXCLUDES
from codex_migrate.workspaces import freeze_tree, tree_check


@unittest.skipUnless(platform.system() == "Darwin", "APFS installation fixture")
class CodexStateTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.FullSkillTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.source = self.fixture.source / ".codex"
        self.staged = Path(self.fixture.config.target_staging) / ".codex"
        self.installed = self.fixture.target / ".codex"
        self.retained = ("config.toml", ".codex-global-state.json", "AGENTS.md",
                         "rules/default.rules", "automations/example/automation.toml")
        for name in self.retained:
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("retained fixture " + name)
        with sqlite3.connect(self.source / "state.sqlite") as db:
            db.execute("create table fixture(value text)")
            db.execute("insert into fixture values ('original')")

    def test_corrupt_config_organization_rules_and_automations_block_replacement(self):
        for name in self.retained:
            with self.subTest(name=name):
                self.fixture.prepare()
                (self.staged / name).write_text("changed fixture")
                with self.assertRaisesRegex(RuntimeError, "Codex state content verification failed before"):
                    self.fixture.engine._install_and_verify()
                self.fixture.assert_destination_original()

    def test_valid_but_changed_database_is_not_a_success(self):
        self.fixture.prepare()
        with sqlite3.connect(self.staged / "state.sqlite") as db:
            db.execute("update fixture set value='changed'")
            self.assertEqual(db.execute("pragma quick_check").fetchone()[0], "ok")
        with self.assertRaisesRegex(RuntimeError, "Codex state content verification failed before"):
            self.fixture.engine._install_and_verify()
        self.fixture.assert_destination_original()

    def test_post_install_state_corruption_rolls_back(self):
        prefix = "mv() { command mv \"$@\"; if test \"$2\" = %s; then printf changed > %s; fi; }\n" % (
            shlex.quote(str(self.installed)), shlex.quote(str(self.installed / "config.toml")))
        self.fixture.prepare(prefix)
        with self.assertRaisesRegex(RuntimeError, "Codex state content verification failed after"):
            self.fixture.engine._install_and_verify()
        self.fixture.assert_destination_original()

    def test_added_missing_and_renamed_state_block_replacement(self):
        for change in ("add", "remove", "rename"):
            with self.subTest(change=change):
                self.fixture.prepare()
                path = self.staged / "AGENTS.md"
                if change == "add":
                    (self.staged / "unexpected.txt").write_text("unexpected")
                elif change == "remove":
                    path.unlink()
                else:
                    path.rename(self.staged / "renamed.md")
                with self.assertRaisesRegex(RuntimeError, "Codex state content verification failed before"):
                    self.fixture.engine._install_and_verify()
                self.fixture.assert_destination_original()

    def test_post_install_valid_database_change_rolls_back(self):
        prefix = "mv() { command mv \"$@\"; if test \"$2\" = %s; then /usr/bin/sqlite3 %s %s; fi; }\n" % (
            shlex.quote(str(self.installed)), shlex.quote(str(self.installed / "state.sqlite")),
            shlex.quote("update fixture set value='changed'"))
        self.fixture.prepare(prefix)
        with self.assertRaisesRegex(RuntimeError, "Codex state content verification failed after"):
            self.fixture.engine._install_and_verify()
        self.fixture.assert_destination_original()

    def test_source_snapshot_is_frozen_for_both_checks(self):
        self.fixture.prepare()
        prepared = self.fixture.engine._prepare_install()
        for root in (self.source, self.staged):
            (root / "config.toml").write_text("same late mutation")
        with self.assertRaisesRegex(RuntimeError, "Codex state content verification failed before"):
            self.fixture.engine._install_and_verify(prepared)
        self.fixture.assert_destination_original()

    def test_identity_fifo_is_not_read_or_copied_and_destination_login_is_kept(self):
        os.mkfifo(self.source / "auth.json")
        os.mkfifo(self.source / "installation_id")
        self.fixture.prepare()
        self.assertFalse((self.staged / "auth.json").exists())
        receipt = self.fixture.engine._install_and_verify()
        self.assertTrue(receipt["codex_state_content_verified"])
        self.assertEqual((self.installed / "auth.json").read_text(), "destination fixture login")
        self.assertEqual((self.installed / "installation_id").read_text(), "destination fixture identity")

    def test_noncanonical_identity_name_blocks_before_copy_or_hash(self):
        (self.source / "Auth.json").write_text("fixture identity must not copy")
        with self.assertRaisesRegex(MigrationError, "noncanonical capitalization"):
            self.fixture.engine._transfers()
        with self.assertRaisesRegex(MigrationError, "noncanonical capitalization"):
            freeze_tree(str(self.source), codex=True)
        with patch.object(self.fixture.engine.transport, "check", side_effect=AssertionError("SSH must not run")):
            with self.assertRaisesRegex(MigrationError, "noncanonical capitalization"):
                self.fixture.engine.preflight()

    def test_unexpected_staged_identity_symlink_blocks_without_following_it(self):
        self.fixture.prepare()
        outside = self.fixture.root / "must not create"
        (self.staged / "auth.json").symlink_to(outside)
        with self.assertRaises(RuntimeError):
            self.fixture.engine._install_and_verify()
        self.assertFalse(outside.exists())
        self.fixture.assert_destination_original()

    def test_receipt_requires_state_content_verification(self):
        self.fixture.prepare()
        original = self.fixture.engine.transport.run_remote
        def missing(script, timeout=60):
            result = original(script, timeout)
            result.stdout = result.stdout.replace("CODEX_STATE_CONTENT_VERIFIED=1\n", "")
            return result
        self.fixture.engine.transport.run_remote = missing
        with self.assertRaisesRegex(MigrationError, "Codex state content verification receipt"):
            self.fixture.engine._install_and_verify()


class CodexFilterTests(unittest.TestCase):
    def test_real_rsync_filter_equivalence_including_directory_file_and_link(self):
        for kind in ("directory", "file", "link"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                source = base / "source"
                target = base / "target"
                source.mkdir()
                # Root-anchored filters must not omit similarly named descendants.
                for name in ("nested/logs/retained", "nested/auth.json", "sqlite/keep.sqlite",
                             "sqlite/logs_fixture.sqlite", "nested/sqlite/logs_fixture.sqlite",
                             "logs_new\nline.sqlite", "temporary\nname.sock", "config.toml",
                             "..codex-global-state.json.tmp-fixture"):
                    path = source / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("fixture " + name)
                for name in ("logs", "cache", "ipc", "tmp"):
                    path = source / name
                    if kind == "directory":
                        path.mkdir()
                        (path / "excluded").write_text("not retained")
                    elif kind == "file":
                        path.write_text("retained")
                    else:
                        path.symlink_to("nested", target_is_directory=True)
                os.mkfifo(source / "auth.json")
                os.mkfifo(source / "installation_id")
                args = ["/usr/bin/rsync", "-a"]
                for pattern in CODEX_EXCLUDES:
                    args.extend(["--exclude", pattern])
                subprocess.run(args + [str(source) + "/", str(target) + "/"],
                               check=True, capture_output=True, timeout=15)
                digest = freeze_tree(str(source), codex=True)
                self.assertEqual(digest, freeze_tree(str(target), codex=True))
                target.chmod(0o700)
                self.assertEqual(digest, freeze_tree(str(target), codex=True))
                for name in ("nested/auth.json", "nested/logs/retained", "nested/sqlite/logs_fixture.sqlite"):
                    retained = target / name
                    before = retained.read_bytes()
                    retained.write_bytes(b"different retained bytes")
                    self.assertNotEqual(digest, freeze_tree(str(target), codex=True))
                    retained.write_bytes(before)
                (target / "config.toml").chmod(0o700)
                self.assertNotEqual(digest, freeze_tree(str(target), codex=True))
                self.assertFalse((target / "logs_new\nline.sqlite").exists())
                self.assertFalse((target / "temporary\nname.sock").exists())
                self.assertTrue((target / "nested/auth.json").exists())
                self.assertEqual((target / "logs").exists(), kind != "directory")

    def test_remote_codex_mode_rejects_failed_hasher(self):
        script = "codex_state_digest() { return 74; }\nverify() {\nlocal workspace_digest\n" + tree_check("fixture", "a" * 64, codex=True) + "\n}\nverify\n"
        result = subprocess.run(["/bin/zsh", "-s"], input=script, text=True,
                                capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 74)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
