"""Release orchestration proofs; these do not contact Apple or certify signing."""
import importlib.util
import json
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "release_build", Path(__file__).resolve().parents[1] / "desktop/build.py")
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)
SUBMISSION = "2efe2717-52ef-43a5-96dc-0797e4ca1041"


def response(status="Accepted", identifier=SUBMISSION, returncode=0):
    return subprocess.CompletedProcess([], returncode, json.dumps(
        {"id": identifier, "status": status, "message": "do not retain diagnostic"}), "")


class ReleaseBuildTests(unittest.TestCase):
    def test_versioned_artifact_names_distinguish_unsigned_builds(self):
        receipt = dict(version="0.1.0", bundle_version="1", architecture="arm64",
                       build_mode="release")
        self.assertEqual(build.artifact_name(receipt), "Codex-Migrate-0.1.0-build1-arm64.zip")
        receipt["build_mode"] = "local-test"
        self.assertEqual(build.artifact_name(receipt),
                         "Codex-Migrate-0.1.0-build1-arm64-LOCAL-UNSIGNED.zip")

    def test_bundle_versions_are_validated_before_build(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(build, "ROOT", Path(temporary)):
            path = Path(temporary) / "desktop/Info.plist"
            path.parent.mkdir()
            for version, number, valid in (("0.1.0", "1", True), ("../bad", "1", False),
                                          ("0.1", "1", False), ("0.1.0", "0", False),
                                          ("0.1.0", 1, False)):
                with self.subTest(version=version, number=number):
                    path.write_bytes(plistlib.dumps(dict(CFBundleShortVersionString=version,
                                                         CFBundleVersion=number)))
                    if valid:
                        self.assertEqual(build.bundle_version(), dict(version=version, bundle_version=number))
                    else:
                        with self.assertRaises(ValueError):
                            build.bundle_version()

    def test_notary_submission_saved_before_wait_and_only_accepted_passes(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            calls = []

            def invoke(command, **kwargs):
                calls.append(command)
                self.assertTrue(kwargs["capture_output"])
                self.assertIn("--output-format", command)
                if command[2] == "wait":
                    self.assertEqual(json.loads((output / "notary-submission.json").read_text()),
                                     {"id": SUBMISSION, "status": "Submitted"})
                return response()

            with patch.object(build.subprocess, "run", side_effect=invoke):
                self.assertEqual(build.notarize(output / "app.zip", "private-profile", output),
                                 {"id": SUBMISSION, "status": "Accepted"})
            self.assertEqual([command[2] for command in calls], ["submit", "wait"])
            self.assertIn("--no-wait", calls[0])
            saved = (output / "notary-submission.json").read_text()
            self.assertNotIn("private-profile", saved)
            self.assertNotIn("diagnostic", saved)

    def test_notary_rejection_ambiguity_and_failure_never_pass(self):
        for result in (response("Invalid"), response("Rejected"), response("In Progress"),
                       response("Accepted", "ffffffff-ffff-ffff-ffff-ffffffffffff"),
                       response(returncode=1),
                       subprocess.CompletedProcess([], 0, "not JSON secret", "secret"),
                       subprocess.CompletedProcess([], 0, "[]", "")):
            with self.subTest(result=result), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary)
                with patch.object(build.subprocess, "run", side_effect=[response(), result]):
                    with self.assertRaises(ValueError) as error:
                        build.notarize(output / "app.zip", "private-profile", output)
                self.assertNotIn("secret", str(error.exception))
                saved = json.loads((output / "notary-submission.json").read_text())
                self.assertEqual(saved["id"], SUBMISSION)
                self.assertNotEqual(saved["status"], "Accepted")

    def test_failed_submit_does_not_wait_or_create_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with patch.object(build.subprocess, "run", return_value=response(returncode=1)) as run:
                with self.assertRaises(ValueError):
                    build.notarize(output / "app.zip", "profile", output)
            self.assertEqual(run.call_count, 1)
            self.assertFalse((output / "notary-submission.json").exists())

    def test_packaging_release_gate_order_and_failure_stop(self):
        for failure in (None, "sign", "verify-signature", "version", "source", "notarize", "staple", "validate", "assess",
                        "archive", "checksum", "receipt", "publish"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "desktop").mkdir()
                (root / "docs").mkdir()
                (root / "desktop/Info.plist").write_bytes(plistlib.dumps(
                    dict(CFBundleShortVersionString="0.1.0", CFBundleVersion="1")))
                for name in ("LICENSE", "docs/desktop-setup.md", "docs/recovery.md", "docs/security-model.md", "docs/support.md"):
                    (root / name).write_text("fixture")
                calls = []

                def run(*arguments):
                    command = list(map(str, arguments))
                    calls.append(command)
                    if "PyInstaller" in command:
                        engine = Path(command[command.index("--distpath") + 1]) / "codex-migrate-engine"
                        engine.mkdir(parents=True)
                        (engine / "codex-migrate-engine").write_text("fixture")
                    if failure == "sign" and command[:2] == ["codesign", "--force"]:
                        raise subprocess.CalledProcessError(1, command)
                    if failure == "verify-signature" and command[:2] == ["codesign", "--verify"]:
                        raise subprocess.CalledProcessError(1, command)
                    if failure in ("staple", "validate") and command[:3] == ["xcrun", "stapler", failure]:
                        raise subprocess.CalledProcessError(1, command)
                    if failure == "assess" and command[0] == "spctl":
                        raise subprocess.CalledProcessError(1, command)
                    if command[0] == "ditto":
                        Path(command[-1]).write_bytes(b"fixture archive")
                        if failure == "archive" and Path(command[-1]).name.startswith("Codex-Migrate-"):
                            raise subprocess.CalledProcessError(1, command)

                def notarize(*args):
                    calls.append(["notarize"])
                    if failure == "notarize":
                        raise ValueError("not Accepted")
                    return {"id": SUBMISSION, "status": "Accepted"}

                receipt = dict(source_revision="abc", source_dirty=False, architecture="arm64", build_mode="release")
                second_receipt = dict(receipt, source_revision="changed" if failure == "source" else "abc")
                original_hash = build.hashlib.sha256
                original_write = Path.write_text
                original_replace = Path.replace

                def checksum():
                    if failure == "checksum":
                        raise OSError("fixture checksum failure")
                    return original_hash()

                def write(path, *args, **kwargs):
                    if failure == "receipt" and path.name == "build-info.json" and path.parent.name.startswith("desktop-"):
                        raise OSError("fixture receipt failure")
                    return original_write(path, *args, **kwargs)

                def publish(path, destination):
                    if failure == "publish":
                        raise OSError("fixture publish failure")
                    self.assertTrue((destination.parent / "SHA256SUMS").is_file())
                    self.assertTrue((destination.parent / "build-info.json").is_file())
                    self.assertFalse(destination.exists())
                    return original_replace(path, destination)

                with patch.object(build, "ROOT", root), patch.object(build.sys, "platform", "darwin"), \
                     patch.object(build.platform, "machine", return_value="arm64"), \
                     patch.object(build.sys, "argv", ["build.py", "--release", "--identity",
                                                    "Developer ID Application: Fixture", "--notary-profile", "profile"]), \
                     patch.object(build, "source_receipt", side_effect=[receipt, second_receipt]), \
                     patch.object(build, "run", side_effect=run), \
                     patch.object(build, "notarize", side_effect=notarize), \
                     patch.object(build.hashlib, "sha256", side_effect=checksum), \
                     patch.object(Path, "write_text", new=write), \
                     patch.object(Path, "replace", new=publish), \
                     patch.object(build.subprocess, "check_output", return_value="9.9.9" if failure == "version" else "0.1.0"):
                    if failure:
                        with self.assertRaises((ValueError, OSError, subprocess.CalledProcessError)):
                            build.main()
                    else:
                        build.main()
                artifacts = list((root / "build").glob("desktop-*/*.zip"))
                self.assertEqual(len(artifacts), 0 if failure else 1)
                if not failure:
                    archive = artifacts[0]
                    self.assertEqual(archive.name, "Codex-Migrate-0.1.0-build1-arm64.zip")
                    saved = json.loads((archive.parent / "build-info.json").read_text())
                    self.assertEqual(saved["notarization"]["status"], "Accepted")
                    self.assertIn(archive.name, (archive.parent / "SHA256SUMS").read_text())
                    order = [c[:3] for c in calls]
                    self.assertLess(order.index(["notarize"]), order.index(["xcrun", "stapler", "staple"]))
                    self.assertLess(order.index(["xcrun", "stapler", "validate"]),
                                    next(i for i, c in enumerate(calls) if c[0] == "spctl"))


if __name__ == "__main__":
    unittest.main()
