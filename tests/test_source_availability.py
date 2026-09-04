"""Synthetic SF_DATALESS metadata on disposable files; not provider certification."""

from contextlib import contextmanager, ExitStack
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from codex_migrate.errors import MigrationError
from codex_migrate.source_availability import check_info, require_local, walk_local, SF_DATALESS
from codex_migrate.filename_safety import check_tree_names
from codex_migrate.inventory import collect
from codex_migrate.storage_scope import require_source_storage
from codex_migrate.skills import discover_personal_skills, discover_workspace_skills
from codex_migrate.workspaces import freeze_tree
from codex_migrate.git_inventory import inspect_git
from codex_migrate.conversations import conversation_verification_script


@contextmanager
def dataless(path):
    info = path.lstat()
    identity = (info.st_dev, info.st_ino)
    def injected(value):
        if (value.st_dev, value.st_ino) == identity:
            return check_info(SimpleNamespace(st_flags=SF_DATALESS))
        return check_info(value)
    with ExitStack() as stack:
        for module in ("source_availability", "filename_safety", "inventory", "skills"):
            stack.enter_context(patch("codex_migrate." + module + ".check_info", injected))
        yield


class SourceAvailabilityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        (self.home / ".codex/sessions").mkdir(parents=True)
        self.workspace = self.home / "Git/repo"
        self.workspace.mkdir(parents=True)

    def file(self, path, data=b"fixture"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def assert_offline(self, operation):
        with self.assertRaisesRegex(MigrationError, "not downloaded locally") as error:
            operation()
        self.assertNotIn(str(self.home), str(error.exception))

    def test_flag_check_and_sparse_file(self):
        with self.assertRaises(MigrationError):
            check_info(SimpleNamespace(st_flags=SF_DATALESS | 1))
        check_info(SimpleNamespace(st_flags=1))
        sparse = self.workspace / "sparse"
        with sparse.open("wb") as stream:
            stream.truncate(8 * 1024 * 1024)
        require_local(sparse)
        check_tree_names(self.workspace)
        self.assertEqual(len(freeze_tree(str(self.workspace))), 64)

    def test_root_stops_before_enumeration(self):
        with dataless(self.workspace), patch("os.scandir", side_effect=AssertionError("No enumeration")):
            self.assert_offline(lambda: check_tree_names(self.workspace))
            self.assert_offline(lambda: list(walk_local(self.workspace)))

    def test_nested_directory_checked_before_enumeration_and_pruning_respected(self):
        child = self.workspace / "offline"
        child.mkdir()
        real_scan = os.scandir
        def scan(path):
            if Path(path) == child:
                raise AssertionError("No offline directory enumeration")
            return real_scan(path)
        with dataless(child), patch("os.scandir", scan):
            self.assert_offline(lambda: list(walk_local(self.workspace)))
            for _current, directories, _files in walk_local(self.workspace):
                directories[:] = []

    def test_retained_file_blocks_inventory_without_content_reads(self):
        for file in (self.file(self.home / ".codex/sessions/chat.jsonl"),
                     self.file(self.workspace / "unfinished")):
            with self.subTest(file=file.name), dataless(file), patch.object(Path, "open", side_effect=AssertionError("No read")):
                self.assert_offline(lambda: collect(str(self.home), [str(self.workspace)]))

    def test_config_blocks_before_screening_process(self):
        for name in ("config.toml", "work.config.toml", "CONFIG.TOML", "Work.CONFIG.TOML"):
            file = self.file(self.home / ".codex" / name)
            with self.subTest(name=name), dataless(file), patch("codex_migrate.storage_scope.subprocess.Popen", side_effect=AssertionError("No process")):
                self.assert_offline(lambda: require_source_storage(str(self.home)))

    def test_excluded_state_and_preserved_links_do_not_open_targets(self):
        codex = self.home / ".codex"
        for name in ("auth.json", "installation_id", "logs_1.sqlite", "logs"):
            path = codex / name
            if name == "logs":
                path.mkdir()
            else:
                self.file(path)
            with dataless(path):
                check_tree_names(codex, codex=True)
        external = self.file(self.home / "external")
        (self.workspace / "link").symlink_to(external)
        with dataless(external):
            check_tree_names(self.workspace)

    def test_directory_only_exclusion_does_not_skip_regular_file(self):
        file = self.file(self.home / ".codex/logs")
        with dataless(file):
            self.assert_offline(lambda: check_tree_names(self.home / ".codex", codex=True))

    def test_skill_root_file_and_materialized_link_target(self):
        skill = self.home / ".agents/skills/example"
        definition = self.file(skill / "SKILL.md")
        target = self.file(self.home / "skill-content")
        (skill / "reference").symlink_to(target)
        for path in (skill.parent, skill, definition, target):
            with dataless(path):
                self.assert_offline(lambda: discover_personal_skills(str(self.home), str(self.home)))
        workspace_skill = self.workspace / ".agents/skills/example"
        self.file(workspace_skill / "SKILL.md")
        with dataless(workspace_skill):
            self.assert_offline(lambda: discover_workspace_skills(str(self.home), str(self.home), [str(self.workspace)]))

    def test_git_pointer_and_transcript_reject_before_open(self):
        gitfile = self.file(self.workspace / ".git", b"gitdir: metadata\n")
        with dataless(gitfile), patch("os.open", side_effect=AssertionError("No content open")):
            self.assert_offline(lambda: inspect_git(str(self.home), [str(self.workspace)], lambda: None))
        transcript = self.file(self.home / ".codex/sessions/chat.jsonl")
        with dataless(transcript), patch("os.open", side_effect=AssertionError("No transcript open")):
            self.assert_offline(lambda: conversation_verification_script(str(self.home / ".codex")))

    def test_freeze_rechecks_before_content_process(self):
        file = self.file(self.workspace / "late-eviction")
        check_tree_names(self.workspace)
        with dataless(file), patch("codex_migrate.workspaces.subprocess.Popen", side_effect=AssertionError("No hashing")):
            self.assert_offline(lambda: freeze_tree(str(self.workspace)))

    def test_resume_rechecks_before_copy_and_preserves_destination(self):
        import test_full_skills as fixtures
        fixture = fixtures.FullSkillTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.prepare()
        with dataless(Path(fixture.config.source_codex) / "sessions"), patch.object(
                fixture.engine.transport, "rsync_process", side_effect=AssertionError("No copy")):
            self.assert_offline(fixture.engine._copy_all)
        fixture.assert_destination_original()
        self.assertTrue(Path(fixture.config.target_staging).is_dir())

    def test_metadata_error_and_cancellation_are_not_silently_ignored(self):
        with patch.object(Path, "lstat", side_effect=OSError("PRIVATE")):
            with self.assertRaisesRegex(MigrationError, "availability could not be checked") as error:
                require_local(self.workspace)
            self.assertNotIn("PRIVATE", str(error.exception))
        def cancel():
            raise InterruptedError("stop")
        with self.assertRaises(InterruptedError):
            check_tree_names(self.workspace, cancel)
