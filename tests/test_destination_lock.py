"""Actual local processes and disposable files; no SSH or user workspaces."""

import os
from pathlib import Path
import select
import signal
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from codex_migrate.config import MigrationConfig
from codex_migrate.destination_lock import LOCK_NAME, locked_destination_script, locked_receiver_command
import test_backup as fixtures
from codex_migrate.components import ComponentExporter, SkillExport


class DestinationLockTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name).resolve() / "new person's home"
        self.home.mkdir()

    def run_script(self, script="echo ALLOWED", home=None):
        return subprocess.run(["/bin/zsh", "-f", "-s"],
                              input=locked_destination_script(str(home or self.home), script),
                              capture_output=True, text=True, timeout=5)

    def hold(self, home=None, body="echo READY; /bin/sleep 30"):
        process = subprocess.Popen(["/bin/zsh", "-f", "-s"],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, start_new_session=True)
        def cleanup():
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate(timeout=5)
        self.addCleanup(cleanup)
        process.stdin.write(locked_destination_script(str(home or self.home), body))
        process.stdin.close()
        process.stdin = None
        self.assertTrue(select.select([process.stdout], [], [], 5)[0], "lock holder did not start")
        self.assertEqual(process.stdout.readline().strip(), "READY")
        return process

    def test_lock_excludes_second_process_without_modifying_destination(self):
        self.hold()
        result = self.run_script()
        self.assertEqual(result.returncode, 75)
        self.assertEqual(result.stdout, "")
        self.assertIn("Another migration is using this destination", result.stderr)

    def test_descendant_keeps_lock_after_launcher_dies(self):
        # Model loss of the SSH shell while an inherited replacement/rollback
        # child is still active. Do not infer transaction death from its parent.
        holder = self.hold(body="/bin/sleep 30 &\necho READY\nwait\n")
        holder.kill()
        holder.wait(timeout=5)
        result = self.run_script()
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertIn("Another migration is using this destination", result.stderr)

    def test_failure_releases_kernel_lock_but_keeps_same_inode(self):
        result = self.run_script("exit 42")
        self.assertEqual(result.returncode, 42, result.stderr)
        lock = self.home / LOCK_NAME
        before = lock.stat()
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "ALLOWED\n")
        self.assertEqual(result.stderr, "")
        self.assertEqual(before.st_ino, lock.stat().st_ino)
        self.assertEqual(lock.stat().st_mode & 0o777, 0o600)
        self.assertEqual(lock.read_bytes(), b"")

    def test_unrelated_destination_is_not_blocked(self):
        self.hold()
        other = self.home.parent / "other"
        other.mkdir()
        result = self.run_script(home=other)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_receiver_command_preserves_binary_stdin(self):
        payload = bytes(range(256)) * 1024
        result = subprocess.run(["/bin/zsh", "-f", "-c",
                                 locked_receiver_command(str(self.home), "exec /bin/cat")],
                                input=payload, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, payload)
        self.assertEqual(result.stderr, b"")
        self.hold()
        result = subprocess.run(["/bin/zsh", "-f", "-c",
                                 locked_receiver_command(str(self.home), "exec /bin/cat")],
                                input=payload, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 75)
        self.assertEqual(result.stdout, b"")

    def test_unsafe_lock_files_fail_without_opening_target_content(self):
        lock = self.home / LOCK_NAME
        victim = self.home / "private"
        victim.write_text("private-content")
        victim.chmod(0o600)
        for kind in ("symlink", "hardlink", "directory", "fifo", "nonempty", "permissions"):
            with self.subTest(kind=kind):
                if kind == "symlink":
                    lock.symlink_to(victim)
                elif kind == "hardlink":
                    os.link(victim, lock)
                elif kind == "directory":
                    lock.mkdir()
                elif kind == "fifo":
                    os.mkfifo(lock, 0o600)
                else:
                    lock.write_text("private-lock" if kind == "nonempty" else "")
                    lock.chmod(0o600 if kind == "nonempty" else 0o644)
                try:
                    result = self.run_script()
                    self.assertEqual(result.returncode, 75, result.stderr)
                    self.assertEqual(result.stdout, "")
                    self.assertNotIn("private", result.stderr)
                    self.assertEqual(victim.read_text(), "private-content")
                finally:
                    lock.rmdir() if kind == "directory" else lock.unlink()

    def test_linked_home_is_not_followed(self):
        alias = self.home.parent / "alias"
        alias.symlink_to(self.home)
        result = self.run_script(home=alias)
        self.assertEqual(result.returncode, 75)
        self.assertFalse((self.home / LOCK_NAME).exists())

    def test_real_full_and_component_installers_respect_same_lock(self):
        fixture = fixtures.BackupTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        fixture.engine.transport = fixture.transport()
        self.hold(fixture.target)
        with self.assertRaisesRegex(RuntimeError, "Another migration is using this destination"):
            fixture.engine._install_and_verify()
        fixture.assert_originals_untouched()
        self.assertFalse(Path(fixture.state.read()["pending_backup"]).exists())
        with self.assertRaisesRegex(RuntimeError, "Another migration is using this destination"):
            fixture.engine._prepare_staging()
        with self.assertRaisesRegex(RuntimeError, "Another migration is using this destination"):
            fixture.engine._copy_all()
        fixture.assert_originals_untouched()
        exporter = ComponentExporter(fixture.config, ["personal-skills"])
        exporter.transport = fixture.transport()
        skill = fixture.source / ".agents/skills/example"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("source skill")
        item = SkillExport("example", str(skill), str(fixture.target / ".agents/skills/example"), "user")
        with self.assertRaisesRegex(RuntimeError, "Another migration is using this destination"):
            exporter._install([item], str(fixture.target / "unused-stage"), "a" * 32)
        # The legacy CLI export path must also lock its staging mkdir/marker,
        # before rsync or replacement. Only the network preflight is replaced.
        with patch.object(exporter, "_preflight"), self.assertRaisesRegex(
                RuntimeError, "Another migration is using this destination"):
            exporter.run()
        self.assertFalse((fixture.target / "Codex-Migrate-Component-Staging").exists())
        fixture.assert_originals_untouched()

    def test_reserved_lock_namespace_cannot_be_replaced(self):
        for name in (LOCK_NAME, LOCK_NAME.upper()):
            for field in ("staging_name", "backup_prefix"):
                with self.subTest(field=field, name=name), self.assertRaises(ValueError):
                    MigrationConfig(target="user@fixture.invalid", target_home=str(self.home),
                                    **{field: name}).validate()
            with self.subTest(workspace=name), self.assertRaises(ValueError):
                MigrationConfig(target="user@fixture.invalid", source_home=str(self.home),
                                target_home=str(self.home.parent / "other"),
                                workspace_roots=[str(self.home / name)]).validate()


if __name__ == "__main__":
    unittest.main()
