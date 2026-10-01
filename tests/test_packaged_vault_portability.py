"""Failure cleanup and isolation guards for the packaged Mac recovery drill."""

import importlib.util
import hashlib
import json
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch


SPEC = importlib.util.spec_from_file_location(
    "packaged_vault_portability", Path(__file__).with_name("packaged_vault_portability.py"))
DRILL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DRILL)
KEY = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SNAPSHOT = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
REVISION = "a" * 40
PACKAGE = (Path("/engine"), Path("/helper"), REVISION)


class PackagedPortabilitySafetyTests(unittest.TestCase):
    def test_partial_startup_line_cannot_hang_deadline(self):
        process = subprocess.Popen([sys.executable, "-c",
            "import os,time; os.write(1,b'Codex Migrate dashboard: '); time.sleep(30)"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        started = time.monotonic()
        try:
            with self.assertRaisesRegex(AssertionError, "startup timed out"):
                DRILL.startup_line(process, timeout=0.2)
            self.assertLess(time.monotonic() - started, 3)
        finally:
            DRILL.stop_process(process)
        self.assertIsNotNone(process.returncode)

    def test_reader_nonzero_exit_is_not_accepted(self):
        process = MagicMock(returncode=7)
        process.poll.return_value = 7
        responses = []
        for body, content_type in ((b"SYNTHETIC-ARCHIVED-WORK", "application/json"),
                (b"SYNTHETIC-ARCHIVED-WORK", "text/markdown"),
                (b'{"closing":true}', "application/json")):
            response = io.BytesIO(body)
            response.headers = {"Content-Type": content_type}
            responses.append(response)
        with patch.object(DRILL.subprocess, "Popen", return_value=process), \
             patch.object(DRILL, "startup_line", return_value=
                 "Codex Migrate dashboard: http://127.0.0.1:1234/#token=synthetic"), \
             patch.object(DRILL, "urlopen", side_effect=responses):
            with self.assertRaisesRegex(AssertionError, "exited unsuccessfully"):
                DRILL.read_and_export(Path("/engine"), Path("/synthetic"))
        process.communicate.assert_called_once_with(timeout=10)

    def test_cleanup_tolerates_process_exit_race(self):
        process = MagicMock(pid=1234)
        process.poll.return_value = None
        with patch.object(DRILL.os, "killpg", side_effect=ProcessLookupError):
            DRILL.stop_process(process)
        process.communicate.assert_called_once_with(timeout=10)

    def bundle(self, root):
        bundle = root / "bundle"
        (bundle / "vault").mkdir(parents=True)
        (bundle / "vault/vault.json").write_text(json.dumps({"key_id": KEY}))
        manifest = bundle / "vault/manifests" / (SNAPSHOT + ".cvmanifest")
        manifest.parent.mkdir()
        manifest.write_bytes(b"synthetic encrypted manifest")
        (bundle / "fixture.json").write_text(json.dumps({
            "format": "codex-backup-packaged-drill", "version": 2, "key_id": KEY,
            "snapshot_id": SNAPSHOT,
            "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
            "source_revision": REVISION}))
        (bundle / "recovery-key.txt").write_text("CV1-" + "a" * 43 + "\n")
        return bundle

    def test_existing_receiver_key_is_never_imported_or_deleted(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle = self.bundle(Path(temporary))
            with patch.object(DRILL, "package", return_value=PACKAGE), \
                 patch.object(DRILL, "command", return_value=(0, b"")) as command:
                with self.assertRaisesRegex(AssertionError, "already has"):
                    DRILL.consume(Path("/app"), bundle)
            command.assert_called_once_with(
                ["/helper", "export-key", "--key-id", KEY], allow_failure=True)

    def test_failed_or_ambiguous_import_always_cleans_disposable_key(self):
        for failure in (AssertionError("test import failed"),
                        AssertionError("test import timed out"),
                        None):
            with self.subTest(failure=str(failure)), tempfile.TemporaryDirectory() as temporary:
                bundle = self.bundle(Path(temporary))
                calls = []

                def command(arguments, **kwargs):
                    calls.append(arguments)
                    if "export-key" in arguments or "verify" in arguments:
                        return 1, b""
                    if "import-key-verified" in arguments:
                        if kwargs.get("allow_failure"):
                            return 1, b""
                        if failure:
                            raise failure
                        return 0, b"{}"  # Reply without confirmed identity is ambiguous.
                    return 0, b"{}"

                with patch.object(DRILL, "package", return_value=PACKAGE), \
                     patch.object(DRILL, "command", side_effect=command):
                    with self.assertRaises(AssertionError):
                        DRILL.consume(Path("/app"), bundle)
                self.assertEqual(calls[-1], ["/helper", "delete-key", "--key-id", KEY])
                self.assertFalse(any("restore" in arguments for arguments in calls))

    def test_generated_artifact_marker_required_before_any_key_operation(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle = self.bundle(Path(temporary))
            (bundle / "fixture.json").write_text("{}")
            with patch.object(DRILL, "package", return_value=PACKAGE), \
                 patch.object(DRILL, "command") as command:
                with self.assertRaisesRegex(AssertionError, "disposable drill"):
                    DRILL.consume(Path("/app"), bundle)
                command.assert_not_called()

    def test_exact_restored_files_and_search_required_and_key_removed(self):
        for damaged in (False, True):
            with self.subTest(damaged=damaged), tempfile.TemporaryDirectory() as temporary:
                bundle = self.bundle(Path(temporary))
                calls = []
                verified = False

                def command(arguments, **kwargs):
                    nonlocal verified
                    calls.append(arguments)
                    if "export-key" in arguments:
                        return 1, b""
                    if "verify" in arguments:
                        status = 0 if verified else 1
                        verified = True
                        return status, b"{}"
                    if "import-key-verified" in arguments:
                        if kwargs.get("allow_failure"):
                            return 1, b""
                        return 0, json.dumps({"key_id": KEY, "imported": True}).encode()
                    if "restore" in arguments:
                        output = Path(arguments[arguments.index("--output") + 1])
                        for name, content in DRILL.FILES.items():
                            path = output / name
                            path.parent.mkdir(parents=True, exist_ok=True)
                            path.write_bytes(b"wrong bytes" if damaged else content)
                        (output / "restore-receipt.json").write_text("{}")
                    if "search" in arguments:
                        return 0, b'[{"collection":"active"}]'
                    return 0, b"{}"

                with patch.object(DRILL, "package", return_value=PACKAGE), \
                     patch.object(DRILL, "command", side_effect=command), \
                     patch.object(DRILL, "read_and_export") as exported:
                    if damaged:
                        with self.assertRaisesRegex(AssertionError, "do not match"):
                            DRILL.consume(Path("/app"), bundle)
                    else:
                        DRILL.consume(Path("/app"), bundle)
                        exported.assert_called_once()
                self.assertEqual(calls[-1], ["/helper", "delete-key", "--key-id", KEY])

    def test_producer_failure_removes_key_persisted_before_lost_reply(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary) / "bundle"
            calls = []

            def command(arguments, **kwargs):
                calls.append(arguments)
                if "backup" in arguments:
                    vault = bundle / "vault"
                    vault.mkdir()
                    (vault / "vault.json").write_text(json.dumps({"key_id": KEY}))
                    raise AssertionError("synthetic lost reply")
                return 0, b"{}"

            with patch.object(DRILL, "package", return_value=PACKAGE), \
                 patch.object(DRILL, "command", side_effect=command):
                with self.assertRaisesRegex(AssertionError, "lost reply"):
                    DRILL.produce(Path("/app"), bundle)
            self.assertEqual(calls[-1], ["/helper", "delete-key", "--key-id", KEY])

    def test_other_package_revision_refuses_before_key_access(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle = self.bundle(Path(temporary))
            with patch.object(DRILL, "package", return_value=(Path("/engine"), Path("/helper"), "b" * 40)), \
                 patch.object(DRILL, "command") as command:
                with self.assertRaisesRegex(AssertionError, "disposable drill"):
                    DRILL.consume(Path("/app"), bundle)
                command.assert_not_called()


if __name__ == "__main__":
    unittest.main()
