import subprocess
import tempfile
import unittest
import os
from pathlib import Path
from types import SimpleNamespace

from codex_migrate.components import (
    ComponentExporter,
    discover_personal_skills,
    discover_workspace_skills,
)
from codex_migrate.config import MigrationConfig
from codex_migrate.migration import MigrationError


class ComponentTests(unittest.TestCase):
    def test_protected_case_aliases_and_identity_hardlinks_are_rejected_without_reading(self):
        for relative, link_kind in ((".CODEX/AUTH.JSON", "symlink"),
                                    (".CODEX/INSTALLATION_ID", "symlink"),
                                    (".SSH/key", "symlink"),
                                    (".codex/auth.json", "hardlink"),
                                    (".codex/installation_id", "hardlink")):
            with self.subTest(relative=relative, kind=link_kind), tempfile.TemporaryDirectory() as temporary:
                home = Path(temporary).resolve()
                skill = home / ".agents/skills/example"
                skill.mkdir(parents=True)
                (skill / "SKILL.md").write_text("disposable fixture")
                protected = home / relative
                protected.parent.mkdir(parents=True, exist_ok=True)
                protected.write_text("synthetic fixture, not authentication")
                if link_kind == "hardlink":
                    os.link(protected, skill / "reference")
                else:
                    (skill / "reference").symlink_to(protected)
                from unittest.mock import patch
                with patch.object(Path, "open", side_effect=AssertionError("No file contents may be opened")):
                    with self.assertRaisesRegex(MigrationError, "protected authentication"):
                        discover_personal_skills(str(home), "/Users/new-user")

    def test_case_ambiguous_personal_skill_names_fail_instead_of_overwriting(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary).resolve()
            for relative in (".codex/skills/Example", ".agents/skills/example"):
                skill = home / relative
                skill.mkdir(parents=True)
                (skill / "SKILL.md").write_text("disposable fixture")
            with self.assertRaisesRegex(MigrationError, "capitalization"):
                discover_personal_skills(str(home), "/Users/new-user")

    def test_personal_discovery_prefers_current_user_skill_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary).resolve()
            legacy = home / ".codex/skills/example"
            current = home / ".agents/skills/example"
            legacy.mkdir(parents=True)
            current.mkdir(parents=True)
            (legacy / "SKILL.md").write_text("legacy", encoding="utf-8")
            (current / "SKILL.md").write_text("current", encoding="utf-8")
            exports = discover_personal_skills(str(home), "/Users/new-user")
            self.assertEqual(len(exports), 1)
            self.assertEqual(exports[0].source, str(current))
            self.assertEqual(
                exports[0].destination,
                "/Users/new-user/.agents/skills/example",
            )

    def test_personal_discovery_follows_only_home_confined_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            home = root / "home"
            external = root / "external"
            skill_root = home / ".codex/skills"
            skill_root.mkdir(parents=True)
            external.mkdir()
            (external / "SKILL.md").write_text("outside", encoding="utf-8")
            (skill_root / "outside").symlink_to(external)
            with self.assertRaises(MigrationError):
                discover_personal_skills(str(home), "/Users/new-user")

    def test_personal_discovery_supports_home_confined_skill_root_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary).resolve()
            legacy = home / ".codex/skills"
            legacy_skill = legacy / "example"
            legacy_skill.mkdir(parents=True)
            (legacy_skill / "SKILL.md").write_text("example", encoding="utf-8")
            (home / ".agents").mkdir()
            (home / ".agents/skills").symlink_to(legacy)
            exports = discover_personal_skills(str(home), "/Users/new-user")
            self.assertEqual(len(exports), 1)
            self.assertEqual(exports[0].scope, "user")

    def test_personal_discovery_rejects_external_skill_root_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            home = root / "home"
            external = root / "external"
            (home / ".agents").mkdir(parents=True)
            external.mkdir()
            (home / ".agents/skills").symlink_to(external)
            with self.assertRaises(MigrationError):
                discover_personal_skills(str(home), "/Users/new-user")

    def test_personal_discovery_rejects_external_nested_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            home = root / "home"
            external = root / "secret"
            skill = home / ".agents/skills/example"
            skill.mkdir(parents=True)
            external.write_text("do not copy", encoding="utf-8")
            (skill / "SKILL.md").write_text("example", encoding="utf-8")
            (skill / "secret-link").symlink_to(external)
            with self.assertRaises(MigrationError):
                discover_personal_skills(str(home), "/Users/new-user")

    def test_apply_fails_before_transport_when_skill_would_be_partial(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            home = root / "home"
            external = root / "secret"
            skill = home / ".agents/skills/example"
            skill.mkdir(parents=True)
            external.write_text("do not copy", encoding="utf-8")
            (skill / "SKILL.md").write_text("example", encoding="utf-8")
            (skill / "required-helper").symlink_to(external)
            config = MigrationConfig(
                target="new-user@new-mac.local",
                target_home="/Users/new-user",
                source_home=str(home),
                apply=True,
            ).validate()
            exporter = ComponentExporter(config, ["personal-skills"])

            class NoTransport:
                def check(self):
                    raise AssertionError("unsafe skill must fail before transport")

            exporter.transport = NoTransport()
            with self.assertRaises(MigrationError):
                exporter.run()

    def test_rejects_in_home_directory_link_with_second_hop_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            home = root / "home"
            outside = root / "outside-secret"
            shared = home / "shared"
            skill = home / ".agents/skills/example"
            skill.mkdir(parents=True)
            shared.mkdir(parents=True)
            outside.write_text("do not copy", encoding="utf-8")
            (skill / "SKILL.md").write_text("example", encoding="utf-8")
            (shared / "nested-outside").symlink_to(outside)
            (skill / "helpers").symlink_to(shared)
            config = MigrationConfig(
                target="new-user@new-mac.local",
                target_home="/Users/new-user",
                source_home=str(home),
                apply=True,
            ).validate()
            exporter = ComponentExporter(config, ["personal-skills"])

            class NoTransport:
                def check(self):
                    raise AssertionError("nested directory link must fail before transport")

            exporter.transport = NoTransport()
            with self.assertRaises(MigrationError):
                exporter.run()

    def test_workspace_discovery_preserves_home_relative_destination(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary).resolve()
            skill = home / "Git/project/.agents/skills/project-tool"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("tool", encoding="utf-8")
            exports = discover_workspace_skills(
                str(home),
                "/Users/new-user",
                [str(home / "Git")],
            )
            self.assertEqual(len(exports), 1)
            self.assertEqual(
                exports[0].destination,
                "/Users/new-user/Git/project/.agents/skills/project-tool",
            )

    def test_planning_mode_does_not_connect_or_mutate(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary).resolve()
            skill = home / ".agents/skills/example"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("example", encoding="utf-8")
            config = MigrationConfig(
                target="new-user@new-mac.local",
                target_home="/Users/new-user",
                source_home=str(home),
            ).validate()
            exporter = ComponentExporter(config, ["personal-skills"])

            class NoTransport:
                def check(self):
                    raise AssertionError("planning mode must not connect")

            exporter.transport = NoTransport()
            result = exporter.run()
            self.assertFalse(result["applied"])
            self.assertEqual(result["item_count"], 1)

    def test_apply_stages_with_safe_links_and_builds_valid_rollback_script(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary).resolve()
            skill = home / ".agents/skills/example"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("example", encoding="utf-8")
            config = MigrationConfig(
                target="new-user@new-mac.local",
                target_home="/Users/new-user",
                source_home=str(home),
                apply=True,
            ).validate()
            exporter = ComponentExporter(config, ["personal-skills"])
            scripts = []
            processes = []

            class FakeProcess:
                def start(self):
                    processes.append("started")

            class FakeTransport:
                def reset_route(self):
                    pass

                def select_route(self, cancelled=None):
                    return "Disposable local fixture — SSH disabled"

                def check(self):
                    return "REMOTE_OK=1\nUSER=new-user\nHOME=/Users/new-user\nFILESYSTEM=apfs\n"

                def run_remote(self, script, timeout=60):
                    scripts.append(script)
                    if "printf 'INSTALLED=1" in script:
                        return SimpleNamespace(
                            stdout=(
                                "INSTALLED=1\nITEMS=1\n"
                                "BACKUP_VERIFIED=1\n"
                                "BACKUP=/Users/new-user/Codex-Migrate-Component-Backup-test\n"
                            )
                        )
                    return SimpleNamespace(stdout="")

                def rsync_process(self, source, destination, **options):
                    self.options = options
                    return FakeProcess()

            transport = FakeTransport()
            exporter.transport = transport
            result = exporter.run()
            self.assertTrue(result["applied"])
            self.assertEqual(processes, ["started"])
            self.assertTrue(transport.options["copy_links"])
            self.assertIn("rollback_needed=1", scripts[-1])
            self.assertIn("cp -P", scripts[-1])
            syntax = subprocess.run(
                ["/bin/zsh", "-n"],
                input=scripts[-1],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(syntax.returncode, 0, syntax.stderr)


if __name__ == "__main__":
    unittest.main()
