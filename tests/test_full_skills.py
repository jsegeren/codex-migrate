"""Real local rsync and APFS transaction fixtures; never connect to another Mac."""

import platform
import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path
from process_fixtures import closed_codex_script, fixture_prefix

from codex_migrate.config import MigrationConfig
from codex_migrate.migration import MigrationEngine, MigrationError
from codex_migrate.state import StateStore
from codex_migrate.transport import TransferProcess


class FullSkillTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / "old person"
        self.target = self.root / "new person"
        self.source.mkdir()
        self.target.mkdir()
        self.skill = self.source / ".agents/skills/example"
        self.skill.mkdir(parents=True)
        (self.skill / "SKILL.md").write_text("current skill")
        (self.skill / "empty folder").mkdir()
        helper = self.source / "helper's file.txt"
        helper.write_text("linked content")
        (self.skill / "helper link.txt").symlink_to(helper)
        legacy = self.source / ".codex/skills/example"
        legacy.mkdir(parents=True)
        (legacy / "SKILL.md").write_text("legacy overridden")
        sessions = self.source / ".codex/sessions"
        sessions.mkdir()
        (sessions / "chat.jsonl").write_text("{}\n")
        target_codex = self.target / ".codex"
        target_codex.mkdir()
        (target_codex / "auth.json").write_text("destination fixture login")
        (target_codex / "installation_id").write_text("destination fixture identity")
        (target_codex / "old.txt").write_text("old Codex state")
        self.destination_skill = self.target / ".agents/skills/example"
        self.destination_skill.mkdir(parents=True)
        (self.destination_skill / "SKILL.md").write_text("destination skill")
        (self.destination_skill / "old helper").write_text("old helper")
        unrelated = self.target / ".agents/skills/unrelated"
        unrelated.mkdir()
        (unrelated / "SKILL.md").write_text("keep unrelated")
        self.config = MigrationConfig(
            target="newperson@fixture.invalid", source_home=str(self.source),
            target_home=str(self.target), apply=True,
        ).validate()
        self.state = StateStore(self.config.state_dir)
        self.engine = MigrationEngine(self.config, self.state)

    def prepare(self, prefix=""):
        config = self.config
        class LocalTransport:
            def run_remote_cancellable(self, script, timeout, cancelled):
                if cancelled():
                    raise MigrationError("Fixture check cancelled")
                return self.run_remote(script, timeout)

            def cancel_all(self):
                pass

            def run_remote(self, script, timeout=60):
                result = subprocess.run(
                    ["/bin/zsh", "-s"], input=fixture_prefix(closed_codex_script(script), prefix),
                    text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    timeout=timeout,
                )
                if result.returncode:
                    raise RuntimeError("Fixture transaction failed (%d): %s" %
                                       (result.returncode, result.stderr))
                return result

            def rsync_process(self, source, destination, excludes=(), copy_links=False):
                options = ["/usr/bin/rsync", "-aE", "--delete-after"]
                if copy_links:
                    options.append("--copy-links")
                for pattern in excludes:
                    options.extend(["--exclude", pattern])
                return TransferProcess(options + [source + "/", destination + "/"])

            def remote_bytes(self, path):
                if path != config.target_staging:
                    raise AssertionError("Unexpected measurement outside staging")
                return 0

        self.engine.transport = LocalTransport()
        inventory = self.engine.inventory()
        self.state.update(inventory=inventory.as_dict())
        self.engine._prepare_staging()
        self.engine._copy_all()

    def assert_destination_original(self):
        self.assertEqual((self.destination_skill / "SKILL.md").read_text(), "destination skill")
        self.assertEqual((self.destination_skill / "old helper").read_text(), "old helper")
        self.assertEqual((self.target / ".codex/old.txt").read_text(), "old Codex state")
        self.assertEqual((self.target / ".codex/auth.json").read_text(), "destination fixture login")
        self.assertEqual((self.target / ".agents/skills/unrelated/SKILL.md").read_text(), "keep unrelated")

    def test_inventory_includes_personal_scope_and_materialized_size(self):
        inventory = self.engine.inventory()
        self.assertEqual(len(inventory.personal_skills), 1)
        self.assertEqual(inventory.personal_skills[0].source, str(self.skill))
        self.assertEqual(inventory.personal_skills[0].destination, str(self.destination_skill))
        self.assertGreater(inventory.personal_skill_bytes, 0)
        self.assertEqual(inventory.estimated_transfer_bytes,
                         inventory.codex_bytes + inventory.personal_skill_bytes)
        self.assertIn(str(self.destination_skill), self.engine._backup_targets())

    def test_overlapping_workspace_is_rejected(self):
        for root in (self.source / ".agents", self.skill, self.source / ".agents/skills"):
            with self.subTest(root=root):
                config = MigrationConfig(
                    target=self.config.target, source_home=str(self.source),
                    target_home=str(self.target), workspace_roots=[str(root)],
                )
                # Scope now fails at configuration, before inventory or SSH.
                with self.assertRaisesRegex(ValueError, "personal skills storage"):
                    MigrationEngine(config, self.state).inventory()

    def test_destination_storage_override_blocks_before_backup_or_replacement(self):
        self.prepare()
        config = self.target / ".codex/config.toml"
        config.write_text('sqlite_home = "PRIVATE_FIXTURE"')
        with self.assertRaisesRegex(RuntimeError, "sqlite_home configuration"):
            self.engine._install_and_verify()
        self.assertEqual((self.target / ".codex/old.txt").read_text(), "old Codex state")
        self.assertEqual((self.destination_skill / "SKILL.md").read_text(), "destination skill")
        self.assertEqual(list(self.target.glob("Codex-Migrate-Backup-*")), [])
        self.assertEqual(config.read_text(), 'sqlite_home = "PRIVATE_FIXTURE"')

    def test_staged_storage_override_blocks_before_replacement(self):
        self.prepare()
        staged = Path(self.config.target_staging) / ".codex/work.config.toml"
        staged.write_text('sqlite_home = "PRIVATE_FIXTURE"')
        with self.assertRaisesRegex(RuntimeError, "sqlite_home configuration"):
            self.engine._install_and_verify()
        self.assertTrue(staged.is_file())
        self.assertEqual((self.target / ".codex/old.txt").read_text(), "old Codex state")
        self.assertEqual(list(self.target.glob("Codex-Migrate-Backup-*")), [])

    def test_new_skill_after_inspection_requires_new_inspection(self):
        self.engine.inventory()
        extra = self.source / ".agents/skills/extra"
        extra.mkdir()
        (extra / "SKILL.md").write_text("extra")
        with self.assertRaisesRegex(MigrationError, "selection changed"):
            self.engine._transfers()

    def test_finalize_after_restart_does_not_expand_confirmed_skill_scope(self):
        inventory = self.engine.inventory()
        self.state.update(staged_personal_skills=[s.as_dict() for s in inventory.personal_skills])
        extra = self.source / ".agents/skills/new-after-staging"
        extra.mkdir()
        (extra / "SKILL.md").write_text("new skill")
        restarted = MigrationEngine(self.config, self.state)
        with self.assertRaisesRegex(MigrationError, "selection changed since staging"):
            restarted._run_finalize()

    def test_older_staging_without_skill_scope_requires_resume(self):
        with self.assertRaisesRegex(MigrationError, "no personal-skill scope record"):
            self.engine._run_finalize()

    def test_authentication_link_fails_before_any_transport(self):
        protected = self.source / ".codex/auth.json"
        protected.write_text("fixture only")
        (self.skill / "innocent-name").symlink_to(protected)
        with self.assertRaisesRegex(MigrationError, "protected authentication"):
            self.engine.inventory()

    def test_broken_nested_link_blocks_instead_of_omitting_skill(self):
        (self.skill / "missing-helper").symlink_to(self.source / "not-present")
        with self.assertRaisesRegex(MigrationError, "broken symbolic link"):
            self.engine.inventory()

    def test_relocated_ssh_material_is_still_protected(self):
        relocated = self.source / "relocated keys"
        relocated.mkdir()
        (relocated / "fixture-key").write_text("fixture only")
        (self.source / ".ssh").symlink_to(relocated)
        (self.skill / "innocent-name").symlink_to(relocated / "fixture-key")
        with self.assertRaisesRegex(MigrationError, "protected authentication"):
            self.engine.inventory()

    def test_root_metadata_does_not_hide_valid_skills(self):
        (self.skill.parent / ".DS_Store").write_text("fixture metadata")
        self.assertEqual(len(self.engine.inventory().personal_skills), 1)

    def test_unsupported_skill_name_is_not_silently_omitted(self):
        self.skill.rename(self.skill.with_name("skill with spaces"))
        with self.assertRaisesRegex(MigrationError, "Unsupported skill directory name"):
            self.engine.inventory()

    def test_dangling_skill_alias_is_not_silently_omitted(self):
        (self.skill.parent / "missing-alias").symlink_to(self.source / "absent")
        with self.assertRaisesRegex(MigrationError, "broken symbolic link"):
            self.engine.inventory()

    @unittest.skipUnless(platform.system() == "Darwin", "APFS transaction fixture")
    def test_full_flow_materializes_skills_and_preserves_unrelated_destination(self):
        self.prepare()
        receipt = self.engine._install_and_verify()
        self.assertEqual(receipt["personal_skills_verified"], 1)
        self.assertEqual((self.destination_skill / "SKILL.md").read_text(), "current skill")
        self.assertEqual((self.destination_skill / "helper link.txt").read_text(), "linked content")
        self.assertFalse((self.destination_skill / "helper link.txt").is_symlink())
        self.assertTrue((self.destination_skill / "empty folder").is_dir())
        self.assertEqual((self.target / ".agents/skills/unrelated/SKILL.md").read_text(), "keep unrelated")
        backup = Path(receipt["backup"])
        self.assertEqual((backup / "personal-skills/example/SKILL.md").read_text(), "destination skill")
        self.assertIn(str(self.destination_skill), (backup / "verification.json").read_text())
        self.assertTrue((self.skill / "helper link.txt").is_symlink())
        self.assertEqual((self.target / ".codex/auth.json").read_text(), "destination fixture login")

    @unittest.skipUnless(platform.system() == "Darwin", "APFS transaction fixture")
    def test_corrupt_staged_skill_blocks_before_destination_replacement(self):
        self.prepare()
        staged = Path(self.config.target_staging) / "personal-skills/example/SKILL.md"
        staged.write_text("corrupt staged copy")
        with self.assertRaises(RuntimeError):
            self.engine._install_and_verify()
        self.assert_destination_original()
        self.assertFalse(Path(self.state.read()["pending_backup"]).exists())

    @unittest.skipUnless(platform.system() == "Darwin", "APFS transaction fixture")
    def test_installed_skill_verification_failure_rolls_back_everything(self):
        prefix = "mv() { command mv \"$@\"; if test \"$2\" = %s; then printf corrupt > %s; fi; }\n" % (
            shlex.quote(str(self.destination_skill)),
            shlex.quote(str(self.destination_skill / "SKILL.md")),
        )
        self.prepare(prefix)
        with self.assertRaises(RuntimeError):
            self.engine._install_and_verify()
        self.assert_destination_original()
        self.assertTrue(Path(self.state.read()["pending_backup"]).is_dir())

    @unittest.skipUnless(platform.system() == "Darwin", "APFS transaction fixture")
    def test_destination_skill_alias_is_backed_up_without_following_it(self):
        self.prepare()
        other = self.destination_skill.with_name("original")
        self.destination_skill.rename(other)
        self.destination_skill.symlink_to(self.target / "missing")
        receipt = self.engine._install_and_verify()
        self.assertFalse(self.destination_skill.is_symlink())
        saved = Path(receipt["backup"]) / "personal-skills/example"
        self.assertTrue(saved.is_symlink())
        self.assertEqual(os.readlink(saved), str(self.target / "missing"))
        self.assertEqual((other / "SKILL.md").read_text(), "destination skill")

    @unittest.skipUnless(platform.system() == "Darwin", "APFS transaction fixture")
    def test_unexpected_special_file_blocks_staging_verification(self):
        self.prepare()
        os.mkfifo(str(Path(self.config.target_staging) / "personal-skills/example/unexpected"))
        with self.assertRaises(RuntimeError):
            self.engine._install_and_verify()
        self.assert_destination_original()


if __name__ == "__main__":
    unittest.main()
