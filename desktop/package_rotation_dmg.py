"""Package the one-time Sparkle key-rotation release as a signed disk image.

Sparkle requires a Developer ID signed DMG to rotate an EdDSA key when
SUVerifyUpdateBeforeExtraction is enabled. This command consumes an already
signed, notarized release app from desktop/build.py; it never edits that app.
An interrupted Apple submission is resumed from its saved ID, never repeated.
"""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import tempfile

from build import ROOT, notary_auth_options, notarize, run, wait_for_notarization


ROTATED_PUBLIC_KEY = "yFTFQ4PptkxpiW2K402K8NaMKsvfyG6tUffSqtRxrKg="
# Leaf certificate of the notarized, currently live build 16. Sparkle permits
# changing the EdDSA key or the Apple signing certificate, but not both.
LIVE_DEVELOPER_ID_CERT_SHA256 = "010c8d00870c1165e3a7c08f8a5a4a554818ede6d94cfab33470ae8b5597bf1b"


def signed_team(app):
    result = subprocess.run(["codesign", "--display", "--verbose=4", str(app)],
                            cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        raise ValueError("source app signing identity cannot be inspected")
    match = re.search(r"^TeamIdentifier=([A-Z0-9]{10})$", result.stderr, re.MULTILINE)
    if not match:
        raise ValueError("source app has no Developer ID team")
    return match.group(1)


def same_developer_certificate(app):
    with tempfile.TemporaryDirectory(prefix="codex-migrate-cert-") as temporary:
        result = subprocess.run(["codesign", "--display", "--extract-certificates", str(app)],
                                cwd=temporary, capture_output=True, text=True)
        certificate = Path(temporary) / "codesign0"
        if result.returncode or not certificate.is_file():
            raise ValueError("source app signing certificate cannot be inspected")
        if hashlib.sha256(certificate.read_bytes()).hexdigest() != LIVE_DEVELOPER_ID_CERT_SHA256:
            raise ValueError("Apple signing certificate changed along with Sparkle key")


def source_release(directory):
    build_root = (ROOT / "build").resolve()
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir() or directory.resolve().parent != build_root:
        raise ValueError("source must be a direct build directory")
    app = directory / "Codex Migrate.app"
    receipt_path = directory / "build-info.json"
    if app.is_symlink() or not app.is_dir() or receipt_path.is_symlink() or not receipt_path.is_file():
        raise ValueError("signed release app or receipt is missing")
    receipt = json.loads(receipt_path.read_text())
    if (receipt.get("build_mode") != "release" or receipt.get("source_dirty") is not False or
            receipt.get("notarization", {}).get("status") != "Accepted" or
            not re.fullmatch(r"[a-f0-9]{40}", receipt.get("source_revision", "")) or
            not re.fullmatch(r"Codex-Migrate-\d+\.\d+\.\d+-build[1-9]\d*-(?:arm64|x86_64)\.zip",
                             receipt.get("artifact", ""))):
        raise ValueError("source is not a completed signed release")
    archive = directory / receipt["artifact"]
    if archive.is_symlink() or not archive.is_file() or hashlib.sha256(archive.read_bytes()).hexdigest() != receipt.get("sha256"):
        raise ValueError("source release ZIP does not match its receipt")
    with (app / "Contents/Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    if (info.get("SUPublicEDKey") != ROTATED_PUBLIC_KEY or
            info.get("CFBundleVersion") != receipt.get("bundle_version") or
            info.get("CFBundleShortVersionString") != receipt.get("version")):
        raise ValueError("source app does not embed the rotated key and receipt version")
    run("codesign", "--verify", "--deep", "--strict", app)
    run("xcrun", "stapler", "validate", app)
    run("spctl", "--assess", "--type", "execute", "--verbose=2", app)
    subprocess.run(["git", "cat-file", "-e", receipt["source_revision"] + "^{commit}"],
                   cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    return app, receipt


def finish(output, candidate, receipt, notary):
    if notary.get("status") != "Accepted":
        raise ValueError("disk image notarization was not Accepted")
    run("xcrun", "stapler", "staple", candidate)
    run("xcrun", "stapler", "validate", candidate)
    run("codesign", "--verify", "--verbose=2", candidate)
    run("spctl", "--assess", "--type", "open", "--context", "context:primary-signature", candidate)
    filename = receipt["artifact"].removesuffix(".zip") + ".dmg"
    artifact = output / filename
    if artifact.exists() or (output / "build-info.json").exists():
        raise ValueError("disk image has already been finalized")
    image = candidate.read_bytes()
    if len(image) < 512 or len(image) > 100 * 1024 * 1024 or image[-512:-508] != b"koly":
        raise ValueError("signed disk image has an invalid UDIF trailer or size")
    digest = hashlib.sha256(image).hexdigest()
    final_receipt = {**receipt, "artifact": filename, "sha256": digest,
                     "diskImageNotarization": notary}
    (output / "build-info.json").write_text(json.dumps(final_receipt, indent=2) + "\n")
    (output / "SHA256SUMS").write_text(digest + "  " + filename + "\n")
    candidate.rename(artifact)
    return artifact


def package(source_directory, identity, profile=None, keychain=None,
            api_key=None, key_id=None, issuer=None, resume=None):
    notary_auth_options(profile, keychain, api_key, key_id, issuer)
    if not identity.startswith("Developer ID Application:"):
        raise ValueError("a Developer ID Application identity is required")
    app, receipt = source_release(source_directory)
    if not identity.endswith(f"({signed_team(app)})"):
        raise ValueError("disk image must use the source app's Developer ID team")
    same_developer_certificate(app)
    build_root = ROOT / "build"
    if resume:
        output = Path(resume)
        if (output.is_symlink() or not output.is_dir() or output.resolve().parent != build_root.resolve()
                or not output.name.startswith("desktop-rotation-")):
            raise ValueError("resume must name a saved rotation build directory")
        candidate = output / "rotation-candidate.dmg"
        record_path = output / "notary-submission.json"
        source_record = output / "source-build.json"
        image_record = output / "submitted-image.json"
        if (candidate.is_symlink() or not candidate.is_file() or record_path.is_symlink() or
                not record_path.is_file() or source_record.is_symlink() or not source_record.is_file() or
                image_record.is_symlink() or not image_record.is_file()):
            raise ValueError("saved disk image or submission ID is missing")
        saved = json.loads(source_record.read_text())
        if saved != {"source_revision": receipt["source_revision"], "sha256": receipt["sha256"]}:
            raise ValueError("resume source release does not match the original submission")
        if json.loads(image_record.read_text()) != {"sha256": hashlib.sha256(candidate.read_bytes()).hexdigest()}:
            raise ValueError("saved disk image changed after notarization submission")
        record = json.loads(record_path.read_text())
        if record.get("status") == "Submitted":
            record = wait_for_notarization(record["id"], profile, record_path,
                                           keychain=keychain, api_key=api_key,
                                           key_id=key_id, issuer=issuer)
    else:
        output = Path(tempfile.mkdtemp(prefix="desktop-rotation-", dir=build_root))
        candidate = output / "rotation-candidate.dmg"
        staging = output / "staging"
        (output / "source-build.json").write_text(json.dumps({
            "source_revision": receipt["source_revision"], "sha256": receipt["sha256"]}) + "\n")
        staging.mkdir()
        shutil.copytree(app, staging / app.name, symlinks=True)
        (staging / "Applications").symlink_to("/Applications")
        run("hdiutil", "create", "-volname", "Codex Migrate", "-srcfolder", staging,
            "-format", "UDZO", candidate)
        shutil.rmtree(staging)
        run("codesign", "--force", "--sign", identity, "--timestamp", candidate)
        run("codesign", "--verify", "--verbose=2", candidate)
        (output / "submitted-image.json").write_text(json.dumps({
            "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest()}) + "\n")
        record = notarize(candidate, profile, output, keychain, api_key, key_id, issuer)
    artifact = finish(output, candidate, receipt, record)
    print("Signed, notarized rotation disk image:", artifact)
    return artifact


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-build-dir", required=True)
    parser.add_argument("--identity", required=True)
    parser.add_argument("--notary-profile")
    parser.add_argument("--notary-keychain")
    parser.add_argument("--notary-api-key")
    parser.add_argument("--notary-key-id")
    parser.add_argument("--notary-issuer")
    parser.add_argument("--resume-output-dir")
    args = parser.parse_args()
    package(args.source_build_dir, args.identity, args.notary_profile, args.notary_keychain,
            args.notary_api_key, args.notary_key_id, args.notary_issuer,
            args.resume_output_dir)


if __name__ == "__main__":
    main()
