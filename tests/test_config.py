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


if __name__ == "__main__":
    unittest.main()
