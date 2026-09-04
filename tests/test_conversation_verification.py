"""Disposable transcript corruption tests; no real conversations are read."""

import platform
import os
import shlex
import subprocess
import unittest

import test_full_skills as fixtures
from codex_migrate.conversations import conversation_verification_script
from codex_migrate.errors import MigrationError


@unittest.skipUnless(platform.system() == "Darwin", "APFS transaction fixtures")
class ConversationVerificationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.FullSkillTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_same_count_staged_corruption_blocks_before_replacement(self):
        self.fixture.prepare()
        staged = self.fixture.target / "Codex-Migrate-Staging/.codex/sessions/chat.jsonl"
        staged.write_text('{"wrong":"transcript"}\n')
        with self.assertRaisesRegex(RuntimeError, "Conversation content verification failed"):
            self.fixture.engine._install_and_verify()
        self.fixture.assert_destination_original()

    def test_same_count_wrong_transcript_name_is_rejected(self):
        self.fixture.prepare()
        staged = self.fixture.target / "Codex-Migrate-Staging/.codex/sessions/chat.jsonl"
        staged.rename(staged.with_name("different-chat.jsonl"))
        with self.assertRaisesRegex(RuntimeError, "Conversation content verification failed"):
            self.fixture.engine._install_and_verify()
        self.fixture.assert_destination_original()

    def test_archived_content_is_verified_too(self):
        archived = self.fixture.source / ".codex/archived_sessions"
        archived.mkdir()
        (archived / "archived.jsonl").write_text('{"archived":true}\n')
        self.fixture.prepare()
        staged = self.fixture.target / "Codex-Migrate-Staging/.codex/archived_sessions/archived.jsonl"
        staged.write_text('{"different":true}\n')
        with self.assertRaisesRegex(RuntimeError, "Conversation content verification failed"):
            self.fixture.engine._install_and_verify()
        self.fixture.assert_destination_original()

    def test_extra_transcript_is_not_accepted(self):
        self.fixture.prepare()
        staged = self.fixture.target / "Codex-Migrate-Staging/.codex/sessions/extra.jsonl"
        staged.write_text('{}\n')
        with self.assertRaisesRegex(RuntimeError, "Conversation content verification failed"):
            self.fixture.engine._install_and_verify()
        self.fixture.assert_destination_original()

    def test_newline_and_shell_characters_in_filename_are_supported(self):
        transcript = self.fixture.source / ".codex/sessions/chat.jsonl"
        transcript.rename(transcript.with_name("chat's $literal\nname.jsonl"))
        self.fixture.prepare()
        receipt = self.fixture.engine._install_and_verify()
        self.assertTrue(receipt["conversation_content_verified"])
        self.assertEqual(receipt["active_sessions"], 1)
        self.assertEqual((self.fixture.target / ".codex/sessions" / "chat's $literal\nname.jsonl").read_text(), '{}\n')

    def test_source_transcript_links_are_not_followed(self):
        transcript = self.fixture.source / ".codex/sessions/chat.jsonl"
        transcript.unlink()
        transcript.symlink_to(self.fixture.target / ".codex/auth.json")
        with self.assertRaisesRegex(MigrationError, "symbolic links"):
            conversation_verification_script(str(self.fixture.source / ".codex"))

    def test_special_transcript_file_fails_without_blocking(self):
        transcript = self.fixture.source / ".codex/sessions/fifo.jsonl"
        os.mkfifo(transcript)
        with self.assertRaisesRegex(MigrationError, "not a regular file"):
            conversation_verification_script(str(self.fixture.source / ".codex"))

    def test_extra_staged_fifo_is_rejected(self):
        self.fixture.prepare()
        extra = self.fixture.target / "Codex-Migrate-Staging/.codex/sessions/extra.jsonl"
        os.mkfifo(extra)
        with self.assertRaisesRegex(RuntimeError, "Conversation content verification failed"):
            self.fixture.engine._install_and_verify()
        self.fixture.assert_destination_original()

    def test_extra_installed_fifo_triggers_rollback(self):
        codex = self.fixture.target / ".codex"
        prefix = "mv() { command mv \"$@\"; if test \"$2\" = %s; then mkfifo %s; fi; }\n" % (
            shlex.quote(str(codex)), shlex.quote(str(codex / "sessions/extra.jsonl")))
        self.fixture.prepare(prefix)
        with self.assertRaisesRegex(RuntimeError, "Conversation content verification failed"):
            self.fixture.engine._install_and_verify()
        self.fixture.assert_destination_original()

    def test_failed_remote_scan_cannot_validate_an_empty_tree(self):
        (self.fixture.source / ".codex/sessions/chat.jsonl").unlink()
        checks = conversation_verification_script(str(self.fixture.source / ".codex"))
        checks = checks.replace("/usr/bin/find", "failed_scan")
        script = "set -o pipefail\nfailed_scan() { return 65; }\nverify() {\n%s\n}\nverify %s\n" % (
            checks, shlex.quote(str(self.fixture.source / ".codex")))
        result = subprocess.run(["/bin/zsh", "-s"], input=script, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 74)
        self.assertEqual(result.stdout, "")

    def test_missing_verification_receipt_cannot_claim_success(self):
        self.fixture.prepare()
        transport = self.fixture.engine.transport
        original = transport.run_remote

        def missing_receipt(script, timeout=60):
            result = original(script, timeout)
            result.stdout = result.stdout.replace("CONVERSATION_CONTENT_VERIFIED=1\n", "")
            return result

        transport.run_remote = missing_receipt
        with self.assertRaisesRegex(MigrationError, "Conversation content verification receipt is missing"):
            self.fixture.engine._install_and_verify()

    def test_checks_do_not_contain_transcript_content_or_login_paths(self):
        transcript = self.fixture.source / ".codex/sessions/chat.jsonl"
        transcript.write_text('{"message":"private fixture text"}\n')
        (self.fixture.source / ".codex/auth.json").write_text("fixture login")
        checks = conversation_verification_script(str(self.fixture.source / ".codex"))
        self.assertNotIn("private fixture text", checks)
        self.assertNotIn("fixture login", checks)
        self.assertNotIn("auth.json", checks)
        self.assertNotIn("installation_id", checks)

    def test_same_count_installed_corruption_triggers_rollback(self):
        codex = self.fixture.target / ".codex"
        prefix = "mv() { command mv \"$@\"; if test \"$2\" = %s; then printf corrupt > %s; fi; }\n" % (
            shlex.quote(str(codex)), shlex.quote(str(codex / "sessions/chat.jsonl")))
        self.fixture.prepare(prefix)
        with self.assertRaisesRegex(RuntimeError, "Conversation content verification failed"):
            self.fixture.engine._install_and_verify()
        self.fixture.assert_destination_original()


if __name__ == "__main__":
    unittest.main()
