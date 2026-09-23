"""Fail-closed receipts for the one-time Sparkle key-rotation disk image."""
import hashlib
import json
from pathlib import Path
import plistlib
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop"))
import package_rotation_dmg as rotation


class RotationDiskImageTests(unittest.TestCase):
    def fixture(self, root):
        output = root / "build/desktop-source"
        app = output / "Codex Migrate.app"
        info = app / "Contents/Info.plist"
        info.parent.mkdir(parents=True)
        info.write_bytes(plistlib.dumps({"SUPublicEDKey": rotation.ROTATED_PUBLIC_KEY,
                                         "CFBundleVersion": "17",
                                         "CFBundleShortVersionString": "0.1.0"}))
        archive = output / "Codex-Migrate-0.1.0-build17-arm64.zip"
        archive.write_bytes(b"PK\x03\x04fixture")
        receipt = {"build_mode": "release", "source_dirty": False,
                   "source_revision": "a" * 40,
                   "notarization": {"id": "12345678-1234-1234-1234-123456789abc", "status": "Accepted"},
                   "artifact": archive.name, "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                   "bundle_version": "17", "version": "0.1.0"}
        (output / "build-info.json").write_text(json.dumps(receipt))
        return output, app, receipt

    def test_source_requires_matching_new_key_and_completed_signed_release(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, app, receipt = self.fixture(root)
            with patch.object(rotation, "ROOT", root), patch.object(rotation, "run"), \
                    patch.object(rotation.subprocess, "run"):
                self.assertEqual(rotation.source_release(source), (app, receipt))
                for changed in [{"source_dirty": True}, {"notarization": {"status": "Submitted"}},
                                {"sha256": "0" * 64}]:
                    (source / "build-info.json").write_text(json.dumps({**receipt, **changed}))
                    with self.assertRaises(ValueError):
                        rotation.source_release(source)
                (source / "build-info.json").write_text(json.dumps(receipt))
                info = app / "Contents/Info.plist"
                info.write_bytes(plistlib.dumps({"SUPublicEDKey": "wrong",
                                                 "CFBundleVersion": "17",
                                                 "CFBundleShortVersionString": "0.1.0"}))
                with self.assertRaises(ValueError):
                    rotation.source_release(source)

    def test_output_requires_accepted_dmg_receipt_and_valid_udif(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            candidate = output / "rotation-candidate.dmg"
            image = bytearray(1024)
            image[-512:-508] = b"koly"
            candidate.write_bytes(image)
            receipt = {"artifact": "Codex-Migrate-0.1.0-build17-arm64.zip",
                       "sha256": "a" * 64}
            accepted = {"id": "abcdef12-1234-1234-1234-123456789abc", "status": "Accepted"}
            with patch.object(rotation, "run"):
                with self.assertRaises(ValueError):
                    rotation.finish(output, candidate, receipt, {**accepted, "status": "Submitted"})
                artifact = rotation.finish(output, candidate, receipt, accepted)
            self.assertEqual(artifact.suffix, ".dmg")
            saved = json.loads((output / "build-info.json").read_text())
            self.assertEqual(saved["diskImageNotarization"], accepted)
            self.assertEqual(saved["sha256"], hashlib.sha256(image).hexdigest())
            self.assertEqual(candidate.read_bytes(), image, "submission bytes must survive stapling")
            self.assertEqual(json.loads((output / "final-image.json").read_text()), {
                "source_sha256": receipt["sha256"], "notary_id": accepted["id"],
                "sha256": saved["sha256"]})

            # A crash after the final rename but before either receipt is
            # written must be recoverable without resubmitting to Apple.
            (output / "build-info.json").unlink()
            (output / "SHA256SUMS").unlink()
            with patch.object(rotation, "run"):
                self.assertEqual(rotation.finish(output, candidate, receipt, accepted), artifact)
            self.assertEqual(json.loads((output / "build-info.json").read_text())["sha256"], saved["sha256"])

            changed = bytearray(artifact.read_bytes())
            changed[0] = 1
            artifact.write_bytes(changed)
            with patch.object(rotation, "run"), self.assertRaisesRegex(ValueError, "changed after stapling"):
                rotation.finish(output, candidate, receipt, accepted)

    def test_failed_stapling_preserves_submitted_image_for_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            candidate = output / "rotation-candidate.dmg"
            image = bytearray(1024)
            image[-512:-508] = b"koly"
            candidate.write_bytes(image)
            receipt = {"artifact": "Codex-Migrate-0.1.0-build17-arm64.zip",
                       "sha256": "a" * 64}
            accepted = {"id": "abcdef12-1234-1234-1234-123456789abc", "status": "Accepted"}
            with patch.object(rotation, "run", side_effect=RuntimeError("staple interrupted")):
                with self.assertRaisesRegex(RuntimeError, "staple interrupted"):
                    rotation.finish(output, candidate, receipt, accepted)
            self.assertEqual(candidate.read_bytes(), image)
            self.assertFalse((output / "final-image.json").exists())
            with patch.object(rotation, "run"):
                self.assertTrue(rotation.finish(output, candidate, receipt, accepted).is_file())

    def test_resume_rejects_disk_image_changed_after_submission(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, app, receipt = self.fixture(root)
            output = root / "build/desktop-rotation-saved"
            output.mkdir()
            (output / "rotation-candidate.dmg").write_bytes(b"changed")
            (output / "source-build.json").write_text(json.dumps({
                "source_revision": receipt["source_revision"], "sha256": receipt["sha256"]}))
            (output / "submitted-image.json").write_text(json.dumps({"sha256": "0" * 64}))
            (output / "notary-submission.json").write_text(json.dumps({
                "id": "abcdef12-1234-1234-1234-123456789abc", "status": "Submitted"}))
            with patch.object(rotation, "ROOT", root), patch.object(rotation, "source_release", return_value=(app, receipt)), \
                    patch.object(rotation, "signed_team", return_value="1234567890"), \
                    patch.object(rotation, "same_developer_certificate"):
                with self.assertRaisesRegex(ValueError, "changed after notarization"):
                    rotation.package(source, "Developer ID Application: Test (1234567890)",
                                     profile="notary", resume=output)

    def test_completed_rotation_can_be_resumed_without_a_second_submission(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, app, receipt = self.fixture(root)
            output = root / "build/desktop-rotation-saved"
            output.mkdir()
            candidate = output / "rotation-candidate.dmg"
            image = bytearray(1024)
            image[-512:-508] = b"koly"
            candidate.write_bytes(image)
            (output / "source-build.json").write_text(json.dumps({
                "source_revision": receipt["source_revision"], "sha256": receipt["sha256"]}))
            (output / "submitted-image.json").write_text(json.dumps({
                "sha256": hashlib.sha256(image).hexdigest()}))
            (output / "notary-submission.json").write_text(json.dumps({
                "id": "abcdef12-1234-1234-1234-123456789abc", "status": "Accepted"}))
            with patch.object(rotation, "ROOT", root), \
                    patch.object(rotation, "source_release", return_value=(app, receipt)), \
                    patch.object(rotation, "signed_team", return_value="1234567890"), \
                    patch.object(rotation, "same_developer_certificate"), \
                    patch.object(rotation, "run"), \
                    patch.object(rotation, "notarize", side_effect=AssertionError("resubmitted")):
                first = rotation.package(source, "Developer ID Application: Test (1234567890)",
                                         profile="notary", resume=output)
                second = rotation.package(source, "Developer ID Application: Test (1234567890)",
                                          profile="notary", resume=output)
            self.assertEqual(first, second)
            self.assertEqual(candidate.read_bytes(), image)
            self.assertEqual(hashlib.sha256(first.read_bytes()).hexdigest(),
                             json.loads((output / "build-info.json").read_text())["sha256"])


if __name__ == "__main__":
    unittest.main()
