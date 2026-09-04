import tempfile
import unittest
from pathlib import Path

from codex_migrate.config import MigrationConfig, SSHOptions


class ConfigTests(unittest.TestCase):
    def test_valid_configuration_expands_and_deduplicates_workspaces(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "Git"
            workspace.mkdir()
            config = MigrationConfig(
                target="new-user@new-mac.local",
                target_home="/Users/new-user",
                source_home=str(root),
                workspace_roots=[str(workspace), str(workspace)],
            ).validate()
            self.assertEqual(config.workspace_roots, [str(workspace.resolve())])

    def test_nested_workspaces_are_collapsed_to_one_copy_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = root / "Git"
            child = parent / "project"
            child.mkdir(parents=True)
            config = MigrationConfig(
                target="new-user@new-mac.local",
                target_home="/Users/new-user",
                source_home=str(root),
                workspace_roots=[str(child), str(parent)],
            ).validate()
            self.assertEqual(config.workspace_roots, [str(parent.resolve())])

    def test_rejects_shell_control_characters_in_target(self):
        with self.assertRaises(ValueError):
            MigrationConfig(
                target="user@host;touch-bad",
                target_home="/Users/user",
            ).validate()

    def test_rejects_workspace_outside_source_home(self):
        with self.assertRaises(ValueError):
            MigrationConfig(
                target="user@host.local",
                target_home="/Users/user",
                source_home="/Users/source",
                workspace_roots=["/private/tmp/project"],
            ).validate()

    def test_rejects_parent_traversal_and_option_like_ssh_user(self):
        with self.assertRaises(ValueError):
            MigrationConfig(
                target="user@host.local",
                target_home="/Users/user",
                source_home="/Users/source",
                workspace_roots=["/Users/source/../private"],
            ).validate()

    def test_rejects_protected_reserved_and_state_workspace_roots(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary).resolve()
            rejected = [
                home / ".codex",
                home / ".codex/sessions",
                home / ".ssh",
                home / ".ssh/archive",
                home / "Codex-Migrate-Staging",
                home / "Codex-Migrate-Staging/project",
                home / "Codex-Migrate-Backup-old",
                home / ".local",
            ]
            for workspace in rejected:
                with self.subTest(workspace=workspace):
                    with self.assertRaises(ValueError):
                        MigrationConfig(
                            target="user@host.local",
                            target_home="/Users/user",
                            source_home=str(home),
                            workspace_roots=[str(workspace)],
                        ).validate()

    def test_rejects_state_inside_codex_or_ssh(self):
        for state_dir in ("/Users/source/.codex/migrate", "/Users/source/.ssh/migrate"):
            with self.subTest(state_dir=state_dir):
                with self.assertRaises(ValueError):
                    MigrationConfig(
                        target="user@host.local",
                        target_home="/Users/user",
                        source_home="/Users/source",
                        state_dir=state_dir,
                    ).validate()
        with self.assertRaises(ValueError):
            MigrationConfig(
                target="-oProxyCommand@host.local",
                target_home="/Users/user",
            ).validate()

    def test_public_dict_does_not_reveal_ssh_file_paths(self):
        config = MigrationConfig(
            target="user@host.local",
            target_home="/Users/user",
            ssh=SSHOptions(
                identity_file="/Users/source/.ssh/id_ed25519",
                known_hosts_file="/Users/source/.ssh/known_hosts",
            ),
        ).validate()
        public = config.to_public_dict()
        self.assertIs(public["ssh"]["identity_file"], True)
        self.assertIs(public["ssh"]["known_hosts_file"], True)

    def test_rejects_case_variants_of_protected_and_control_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary).resolve()
            for relative in (".CODEX", ".CodeX/sessions", ".SSH", ".Ssh/archive",
                             "codex-migrate-staging/project", "CODEX-MIGRATE-BACKUP-old",
                             ".LOCAL/state", ".local/STATE/codex-migrate/new"):
                with self.subTest(relative=relative), self.assertRaises(ValueError):
                    MigrationConfig(target="user@host.local", target_home="/Users/user",
                                    source_home=str(home),
                                    workspace_roots=[str(home / relative)]).validate()
            for relative in (".CODEX/migrate", ".SSH/migrate"):
                with self.subTest(state=relative), self.assertRaises(ValueError):
                    MigrationConfig(target="user@host.local", target_home="/Users/user",
                                    source_home=str(home), state_dir=str(home / relative)).validate()

    def test_rejects_control_names_that_overlap_protected_storage(self):
        for name in (".codex", ".CODEX", ".ssh", ".SSH", ".agents", ".local"):
            for field in ("staging_name", "backup_prefix"):
                with self.subTest(name=name, field=field), self.assertRaises(ValueError):
                    MigrationConfig(target="user@host.local", target_home="/Users/user",
                                    **{field: name}).validate()

    def test_rejects_case_or_normalization_ambiguous_workspace_roots(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary).resolve()
            for names in (("Git", "git"), ("Work/Café", "Work/Cafe\u0301"),
                          ("Projects", "projects/app")):
                with self.subTest(names=names), self.assertRaises(ValueError):
                    MigrationConfig(target="user@host.local", target_home="/Users/user",
                                    source_home=str(home),
                                    workspace_roots=[str(home / name) for name in names]).validate()

    def test_rejects_normalization_alias_of_control_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary).resolve()
            with self.assertRaises(ValueError):
                MigrationConfig(target="user@host.local", target_home="/Users/user",
                                source_home=str(home), state_dir=str(home / "Café/state"),
                                workspace_roots=[str(home / "Cafe\u0301")]).validate()

    def test_protected_storage_alias_targets_are_not_workspace_or_state(self):
        for protected in (".codex", ".ssh", ".agents/skills"):
            with self.subTest(protected=protected), tempfile.TemporaryDirectory() as temporary:
                home = Path(temporary).resolve()
                actual = home / "relocated"
                actual.mkdir()
                alias = home / protected
                alias.parent.mkdir(parents=True, exist_ok=True)
                alias.symlink_to(actual)
                for selection in (str(alias), str(actual)):
                    with self.assertRaises(ValueError):
                        MigrationConfig(target="user@host.local", target_home="/Users/user",
                                        source_home=str(home), workspace_roots=[selection]).validate()
                with self.assertRaises(ValueError):
                    MigrationConfig(target="user@host.local", target_home="/Users/user",
                                    source_home=str(home), state_dir=str(actual / "state")).validate()

    def test_shared_parent_alias_spelling_and_namespace_overlap_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary).resolve()
            with self.assertRaises(ValueError):
                MigrationConfig(target="user@host.local", target_home="/Users/user",
                                source_home=str(home),
                                workspace_roots=[str(home / "Work/a"), str(home / "work/b")]).validate()
        for staging in ("backup", "BACKUP-old"):
            with self.assertRaises(ValueError):
                MigrationConfig(target="user@host.local", target_home="/Users/user",
                                staging_name=staging, backup_prefix="Backup").validate()

    def test_relocated_default_state_resolves_before_protection_and_confinement(self):
        for target in ("protected", "outside"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                home = root / "home"
                home.mkdir()
                destination = home / ".ssh" if target == "protected" else root / "outside"
                destination.mkdir()
                (home / ".local").symlink_to(destination)
                with self.assertRaises(ValueError):
                    MigrationConfig(target="user@host.local", target_home="/Users/user",
                                    source_home=str(home)).validate()


if __name__ == "__main__":
    unittest.main()
