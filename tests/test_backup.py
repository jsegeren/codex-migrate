import json
import platform
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from process_fixtures import closed_codex_script, fixture_prefix

from codex_migrate.backup import BACKUP_FUNCTIONS, MIN_RESERVE_BYTES
from codex_migrate.components import ComponentExporter, SkillExport
from codex_migrate.config import MigrationConfig
from codex_migrate.migration import MigrationEngine, MigrationError
from codex_migrate.state import StateStore


@unittest.skipUnless(platform.system() == "Darwin", "APFS fixture tests")
class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "source"
        self.target = self.root / "target"
        for home in (self.source, self.target):
            (home / ".codex/sessions").mkdir(parents=True)
            (home / "Git").mkdir()
        (self.source / ".codex/sessions/chat.jsonl").write_text("{}\n")
        (self.source / "Git/new.txt").write_text("new-work")
        (self.target / ".codex/auth.json").write_text("fixture-auth")
        (self.target / ".codex/installation_id").write_text("fixture-id")
        (self.target / ".codex/old.txt").write_text("original")
        (self.target / "Git/old.txt").write_text("original-work")
        self.config = MigrationConfig(
            target="person@fixture.local", source_home=str(self.source),
            target_home=str(self.target), workspace_roots=[str(self.source / "Git")],
            apply=True,
        ).validate()
        self.state = StateStore(self.config.state_dir)
        self.engine = MigrationEngine(self.config, self.state)
        self.state.update(migration_id="a" * 32)
        self.stage = Path(self.config.target_staging)
        shutil.copytree(self.source / ".codex", self.stage / ".codex")
        shutil.copytree(self.source / "Git", self.stage / "home-relative/Git")
        (self.stage / ".codex-migrate-owner").write_text("a" * 32 + "\n")

    def tearDown(self):
        self.temp.cleanup()

    def transport(self, fault=None):
        state = self.state
        codex = str(self.target / ".codex")
        class LocalTransport:
            def run_remote(self, script, timeout=60):
                script = closed_codex_script(script)
                prefix = ""
                if fault in ("process_error", "process_open", "process_reopened"):
                    script = script.replace("fixture_ps() {", "fixture_ps_base() {", 1)
                    if fault == "process_error":
                        prefix += "fixture_ps() { return 74; }\n"
                    elif fault == "process_open":
                        prefix += "fixture_ps() { printf '%s /bin/codex\\n' \"$(/usr/bin/id -u)\"; }\n"
                    else:
                        prefix += "fixture_ps() { if test -d %s; then n=codex; else n=zsh; fi; printf '%%s /bin/%%s\\n' \"$(/usr/bin/id -u)\" \"$n\"; }\n" % shlex.quote(state.read()["pending_backup"])
                elif fault == "space":
                    prefix += "fake_df() { printf 'disk 100 100 0 100%% mount\\n'; }\n"
                    script = script.replace("/bin/df", "fake_df")
                elif fault == "space_after_backup":
                    prefix += "fake_df() { if test -d %s; then n=0; else n=9999999999; fi; printf 'disk 100 0 %%s 0%%%% mount\\n' \"$n\"; }\n" % shlex.quote(state.read()["pending_backup"])
                    script = script.replace("/bin/df", "fake_df")
                elif fault == "copy":
                    prefix += "cp() { echo 'Injected backup copy failure' >&2; return 74; }\n"
                elif fault == "corruption":
                    backup = state.read()["pending_backup"]
                    check = "verify_backup " + shlex.quote(codex)
                    script = script.replace(check,
                        "printf 'modified' > " + shlex.quote(backup + "/.codex/old.txt")
                        + "\n" + check, 1)
                result = subprocess.run(["/bin/zsh", "-s"], input=fixture_prefix(script, prefix),
                                        capture_output=True, text=True, timeout=timeout)
                if result.returncode:
                    raise RuntimeError(result.stderr or "Fixture script failed")
                return result
        return LocalTransport()

    def assert_originals_untouched(self):
        self.assertEqual((self.target / ".codex/old.txt").read_text(), "original")
        self.assertEqual((self.target / "Git/old.txt").read_text(), "original-work")
        self.assertTrue((self.stage / ".codex/sessions/chat.jsonl").exists())
        self.assertFalse((self.target / "Git/new.txt").exists())

    def test_unknown_process_state_blocks_before_backup(self):
        self.engine.transport = self.transport("process_error")
        with self.assertRaisesRegex(RuntimeError, "Cannot verify Codex process state"):
            self.engine._install_and_verify()
        self.assert_originals_untouched()
        self.assertFalse(Path(self.state.read()["pending_backup"]).exists())

    def test_open_destination_cli_blocks_before_backup(self):
        self.engine.transport = self.transport("process_open")
        with self.assertRaisesRegex(RuntimeError, "Codex is running"):
            self.engine._install_and_verify()
        self.assert_originals_untouched()
        self.assertFalse(Path(self.state.read()["pending_backup"]).exists())

    def test_codex_reopening_during_backup_blocks_replacement(self):
        self.engine.transport = self.transport("process_reopened")
        with self.assertRaisesRegex(RuntimeError, "Codex is running"):
            self.engine._install_and_verify()
        self.assert_originals_untouched()
        self.assertTrue((Path(self.state.read()["pending_backup"]) / "verification.json").exists())

    def test_low_space_blocks_before_backup_or_replacement(self):
        self.engine.transport = self.transport("space")
        with self.assertRaisesRegex(RuntimeError, "Not enough destination space"):
            self.engine._install_and_verify()
        self.assert_originals_untouched()
        self.assertFalse(Path(self.state.read()["pending_backup"]).exists())

    def test_failed_backup_copy_preserves_originals_and_staging(self):
        self.engine.transport = self.transport("copy")
        with self.assertRaisesRegex(RuntimeError, "Injected backup"):
            self.engine._install_and_verify()
        self.assert_originals_untouched()
        self.assertFalse((Path(self.state.read()["pending_backup"]) / "verification.json").exists())

    def test_space_consumed_during_backup_blocks_before_replacement(self):
        self.engine.transport = self.transport("space_after_backup")
        with self.assertRaisesRegex(RuntimeError, "Not enough destination space"):
            self.engine._install_and_verify()
        self.assert_originals_untouched()
        self.assertFalse((Path(self.state.read()["pending_backup"]) / "verification.json").exists())

    def test_corrupt_backup_blocks_before_replacement(self):
        self.engine.transport = self.transport("corruption")
        with self.assertRaisesRegex(RuntimeError, "Backup verification found differences"):
            self.engine._install_and_verify()
        self.assert_originals_untouched()
        self.assertFalse((Path(self.state.read()["pending_backup"]) / "verification.json").exists())

    def test_success_writes_verified_recovery_map(self):
        self.engine.transport = self.transport()
        receipt = self.engine._install_and_verify()
        self.assertTrue(receipt["backup_verified"])
        saved = json.loads((Path(receipt["backup"]) / "verification.json").read_text())
        self.assertTrue(saved["backup_verified"])
        self.assertEqual(len(saved["scope"]), 2)
        self.assertEqual(saved["scope"][0]["original"], str(self.target / ".codex"))
        self.assertNotIn("fixture-auth", json.dumps(saved))
        self.assertEqual((self.source / "Git/new.txt").read_text(), "new-work")

    def test_verifier_detects_extra_files_and_changed_symlinks_without_printing_names(self):
        original = self.root / "original"
        copied = self.root / "copied"
        original.mkdir()
        copied.mkdir()
        (original / "link").symlink_to("first")
        (copied / "link").symlink_to("second")
        (copied / "private-extra-name").write_text("private-content")
        result = subprocess.run(["/bin/zsh", "-s"], input="set -eu\n" + BACKUP_FUNCTIONS
            + "verify_backup %s %s\n" % (shlex.quote(str(original)), shlex.quote(str(copied))),
            capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("private", result.stdout + result.stderr)

    def test_component_low_space_blocks_before_replacement(self):
        skill = self.source / ".agents/skills/example"
        destination = self.target / ".agents/skills/example"
        skill.mkdir(parents=True)
        destination.mkdir(parents=True)
        (skill / "SKILL.md").write_text("new")
        (destination / "SKILL.md").write_text("old")
        exporter = ComponentExporter(self.config, ["personal-skills"])
        exporter.transport = self.transport("space")
        item = SkillExport("example", str(skill), str(destination), "user")
        stage = self.target / "component-stage"
        shutil.copytree(skill, stage / "items/0")
        (stage / ".codex-migrate-owner").write_text("a" * 32)
        with self.assertRaisesRegex(RuntimeError, "Not enough destination space"):
            exporter._install([item], str(stage), "a" * 32)
        self.assertEqual((destination / "SKILL.md").read_text(), "old")
        self.assertTrue((stage / "items/0/SKILL.md").exists())

    def test_component_low_space_blocks_before_staging(self):
        skill = self.source / ".agents/skills/example"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("new")
        exporter = ComponentExporter(self.config, ["personal-skills"])
        exporter.transport = self.transport("space")
        with patch.object(exporter, "_preflight"):
            with self.assertRaisesRegex(RuntimeError, "Not enough destination space"):
                exporter.run()
        self.assertFalse((self.target / "Codex-Migrate-Component-Staging").exists())

    def test_component_reopened_codex_blocks_replacement_after_backup(self):
        skill = self.source / ".agents/skills/example"
        destination = self.target / ".agents/skills/example"
        skill.mkdir(parents=True)
        destination.mkdir(parents=True)
        (skill / "SKILL.md").write_text("new")
        (destination / "SKILL.md").write_text("old")
        stage = self.target / "component-stage"
        backup = self.target / "component-backup"
        self.state.update(pending_backup=str(backup))
        shutil.copytree(skill, stage / "items/0")
        (stage / ".codex-migrate-owner").write_text("a" * 32)
        exporter = ComponentExporter(self.config, ["personal-skills"])
        exporter.transport = self.transport("process_reopened")
        with self.assertRaisesRegex(RuntimeError, "Codex is running"):
            exporter._install([SkillExport("example", str(skill), str(destination), "user")],
                              str(stage), "a" * 32, backup=str(backup))
        self.assertEqual((destination / "SKILL.md").read_text(), "old")
        self.assertTrue((stage / "items/0/SKILL.md").exists())
        self.assertTrue((backup / "verification.json").exists())

    def test_component_preserves_existing_symlink_in_verified_backup(self):
        skill = self.source / ".agents/skills/example"
        destination = self.target / ".agents/skills/example"
        skill.mkdir(parents=True)
        destination.parent.mkdir(parents=True)
        (skill / "SKILL.md").write_text("new")
        destination.symlink_to("missing-old-link-target")
        stage = self.target / "component-stage"
        shutil.copytree(skill, stage / "items/0")
        (stage / ".codex-migrate-owner").write_text("a" * 32)
        exporter = ComponentExporter(self.config, ["personal-skills"])
        exporter.transport = self.transport()
        receipt = exporter._install([SkillExport("example", str(skill), str(destination), "user")],
                                    str(stage), "a" * 32)
        self.assertTrue(receipt["backup_verified"])
        self.assertTrue((Path(receipt["backup"]) / "items/0").is_symlink())
        self.assertEqual((destination / "SKILL.md").read_text(), "new")

    def test_preflight_counts_backup_bytes_and_records_blocked_space(self):
        engine = self.engine
        inventory = engine.inventory()
        class Transport:
            def check(inner):
                return "USER=person\nHOME=%s\nFILESYSTEM=apfs\n" % self.target
            def run_remote(inner, script, timeout=60):
                return SimpleNamespace(stdout="10000\n" if "backup_size" in script
                                       else "TARGET_CODEX_READY=1\n")
            def remote_free_bytes(inner, path):
                return MIN_RESERVE_BYTES + inventory.estimated_transfer_bytes
        engine.transport = Transport()
        with self.assertRaisesRegex(MigrationError, "Installation blocked"):
            engine.preflight()
        self.assertEqual(self.state.read()["space_check"], "blocked")
        self.assertEqual(self.state.read()["backup_bytes_required"], 10000)


if __name__ == "__main__":
    unittest.main()
