"""Failure cleanup and isolation guards for the packaged Mac recovery drill."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "packaged_vault_portability", Path(__file__).with_name("packaged_vault_portability.py"))
DRILL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DRILL)
KEY = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
REVISION = "a" * 40
PACKAGE = (Path("/engine"), Path("/helper"), REVISION)


class PackagedPortabilitySafetyTests(unittest.TestCase):
    def bundle(self, root):
        bundle = root / "bundle"
        (bundle / "vault").mkdir(parents=True)
        (bundle / "vault/vault.json").write_text(json.dumps({"key_id": KEY}))
        (bundle / "fixture.json").write_text(json.dumps({
            "format": "codex-backup-packaged-drill", "version": 1, "key_id": KEY,
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
                    if "import-key" in arguments:
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
                    if "import-key" in arguments:
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
                     patch.object(DRILL, "command", side_effect=command):
                    if damaged:
                        with self.assertRaisesRegex(AssertionError, "do not match"):
                            DRILL.consume(Path("/app"), bundle)
                    else:
                        DRILL.consume(Path("/app"), bundle)
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
