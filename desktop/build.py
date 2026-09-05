"""Build a self-contained native app; release mode fails closed on signing.

Run with the isolated build environment's Python, never a customer's Python.
Each build has its own output directory. No previous artifacts are overwritten.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    subprocess.run([str(arg) for arg in args], check=True, cwd=ROOT)


def source_receipt(release=False):
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
    ).strip()
    dirty = bool(subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=normal"],
        cwd=ROOT, text=True,
    ).strip())
    if release and dirty:
        raise ValueError("release requires a clean committed source tree")
    return {"source_revision": revision, "source_dirty": dirty,
            "architecture": platform.machine(),
            "build_mode": "release" if release else "local-test",
            "built_at": datetime.now(timezone.utc).isoformat()}


def bundle_version():
    with (ROOT / "desktop/Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    version = info.get("CFBundleShortVersionString", "")
    build = info.get("CFBundleVersion", "")
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("app version must have three numeric components")
    if not isinstance(build, str) or not re.fullmatch(r"[1-9][0-9]*", build):
        raise ValueError("app build number must be a positive integer")
    return {"version": version, "bundle_version": build}


def artifact_name(receipt):
    suffix = "" if receipt["build_mode"] == "release" else "-LOCAL-UNSIGNED"
    return ("Codex-Migrate-" + receipt["version"] + "-build" + receipt["bundle_version"]
            + "-" + receipt["architecture"] + suffix + ".zip")


def notary_request(profile, *arguments):
    result = subprocess.run(
        ["xcrun", "notarytool", *map(str, arguments), "--keychain-profile", profile,
         "--output-format", "json"], cwd=ROOT, capture_output=True, text=True,
    )
    if result.returncode:
        raise ValueError("notarization command failed; inspect the saved submission before retrying")
    try:
        response = json.loads(result.stdout)
        if not isinstance(response, dict):
            raise TypeError
        identifier = str(uuid.UUID(response["id"]))
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ValueError("notarization returned an invalid receipt; release stopped") from None
    return response, identifier


def wait_for_notarization(identifier, profile, receipt_path):
    response, waited_id = notary_request(profile, "wait", identifier)
    if waited_id != identifier:
        raise ValueError("notarization submission ID changed; release stopped")
    status = response.get("status")
    record = {
        "id": identifier,
        "status": status if status in ("Accepted", "Invalid", "Rejected") else "Unknown",
    }
    receipt_path.write_text(json.dumps(record, indent=2) + "\n")
    if record["status"] != "Accepted":
        raise ValueError("notarization was not Accepted; no release archive created")
    return record


def notarize(submission, profile, output):
    """Save the submission ID before waiting; never print credential diagnostics."""

    _, identifier = notary_request(profile, "submit", submission, "--no-wait")
    record = {"id": identifier, "status": "Submitted"}
    receipt_path = output / "notary-submission.json"
    receipt_path.write_text(json.dumps(record, indent=2) + "\n")
    print("Notarization submission saved:", receipt_path, flush=True)
    return wait_for_notarization(identifier, profile, receipt_path)


def publish_artifact(app, output, receipt, scratch):
    artifact = output / artifact_name(receipt)
    candidate = scratch / artifact.name
    run("ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", app, candidate)
    checksum = hashlib.sha256()
    with candidate.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    digest = checksum.hexdigest()
    (output / "SHA256SUMS").write_text(digest + "  " + artifact.name + "\n")
    receipt.update(artifact=artifact.name, sha256=digest)
    (output / "build-info.json").write_text(json.dumps(receipt, indent=2) + "\n")
    # Expose the downloadable filename only once all completion metadata
    # exists. Failed copy/hash/receipt writes leave no public-looking ZIP.
    candidate.replace(artifact)
    return artifact


def resume_state(output):
    build_root = (ROOT / "build").resolve()
    output = Path(output)
    if output.is_symlink() or not output.is_dir() or output.resolve().parent != build_root:
        raise ValueError("resume path must be an existing direct build/desktop-* directory")
    if not output.name.startswith("desktop-"):
        raise ValueError("resume path must be an existing direct build/desktop-* directory")
    app = output / "Codex Migrate.app"
    info_path = app / "Contents/Info.plist"
    embedded_path = app / "Contents/Resources/build-info.json"
    notary_path = output / "notary-submission.json"
    if (app.is_symlink() or not app.is_dir() or info_path.is_symlink()
            or not info_path.is_file() or embedded_path.is_symlink()
            or not embedded_path.is_file()):
        raise ValueError("saved release app or embedded build receipt is missing or unsafe")
    if notary_path.is_symlink() or not notary_path.is_file():
        raise ValueError("saved notarization submission receipt is missing or unsafe")
    completion_paths = (output / "build-info.json", output / "SHA256SUMS")
    if any(path.is_symlink() or path.exists() for path in completion_paths) \
            or list(output.glob("Codex-Migrate-*.zip")):
        raise ValueError("saved release already has completion output; refusing to overwrite it")
    try:
        receipt = json.loads(embedded_path.read_text())
        notary = json.loads(notary_path.read_text())
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError("saved release receipt is unreadable or invalid") from None
    required = {
        "source_revision", "source_dirty", "architecture", "build_mode",
        "built_at", "version", "bundle_version",
    }
    if not isinstance(receipt, dict) or set(receipt) != required:
        raise ValueError("embedded build receipt has an unsupported shape")
    if not isinstance(receipt["source_revision"], str) or not re.fullmatch(
            r"[0-9a-f]{40}|[0-9a-f]{64}", receipt["source_revision"]):
        raise ValueError("embedded build receipt has an invalid source revision")
    if receipt["source_dirty"] is not False or receipt["build_mode"] != "release":
        raise ValueError("saved app is not a clean release build")
    if receipt["architecture"] not in ("arm64", "x86_64"):
        raise ValueError("embedded build receipt has an unsupported architecture")
    if not isinstance(receipt["built_at"], str):
        raise ValueError("embedded build receipt has an invalid build time")
    if not isinstance(receipt["version"], str) or not re.fullmatch(
            r"[0-9]+\.[0-9]+\.[0-9]+", receipt["version"]):
        raise ValueError("embedded build receipt has an invalid app version")
    if not isinstance(receipt["bundle_version"], str) or not re.fullmatch(
            r"[1-9][0-9]*", receipt["bundle_version"]):
        raise ValueError("embedded build receipt has an invalid build number")
    if not isinstance(notary, dict) or set(notary) != {"id", "status"}:
        raise ValueError("saved notarization submission receipt has an unsupported shape")
    try:
        identifier = str(uuid.UUID(notary["id"]))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("saved notarization submission ID is invalid") from None
    if notary["status"] in ("Invalid", "Rejected"):
        raise ValueError("saved notarization submission was rejected; it cannot be resumed")
    if notary["status"] not in ("Submitted", "Unknown", "Accepted"):
        raise ValueError("saved notarization submission status is invalid")
    try:
        with info_path.open("rb") as stream:
            info = plistlib.load(stream)
    except (OSError, plistlib.InvalidFileException):
        raise ValueError("saved app Info.plist is unreadable or invalid") from None
    if not isinstance(info, dict):
        raise ValueError("saved app Info.plist is unreadable or invalid")
    if (info.get("CFBundleShortVersionString") != receipt["version"]
            or info.get("CFBundleVersion") != receipt["bundle_version"]):
        raise ValueError("saved app and embedded build receipt versions do not match")
    return output, app, receipt, notary_path, identifier


def resume_notarization(output, profile):
    output, app, receipt, notary_path, identifier = resume_state(output)
    source = subprocess.run(
        ["git", "show", receipt["source_revision"] + ":desktop/Info.plist"],
        cwd=ROOT, capture_output=True,
    )
    if source.returncode:
        raise ValueError("saved release source revision is not available in this repository")
    try:
        source_info = plistlib.loads(source.stdout)
    except (TypeError, plistlib.InvalidFileException):
        raise ValueError("saved release source revision has an invalid app manifest") from None
    if (not isinstance(source_info, dict)
            or source_info.get("CFBundleShortVersionString") != receipt["version"]
            or source_info.get("CFBundleVersion") != receipt["bundle_version"]):
        raise ValueError("saved release source and embedded app versions do not match")
    run("codesign", "--verify", "--deep", "--strict", app)
    receipt["notarization"] = wait_for_notarization(identifier, profile, notary_path)
    run("xcrun", "stapler", "staple", app)
    run("xcrun", "stapler", "validate", app)
    run("spctl", "--assess", "--type", "execute", "--verbose=2", app)
    with tempfile.TemporaryDirectory(prefix="resume-", dir=ROOT / "build") as scratch:
        artifact = publish_artifact(app, output, receipt, Path(scratch))
    print("Build mode: release (signed and notarized)")
    print("Resumed notarization submission:", identifier)
    print("Artifact:", artifact)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", action="store_true")
    parser.add_argument("--identity", help="Developer ID Application identity already in Keychain")
    parser.add_argument("--notary-profile", help="Existing notarytool Keychain profile")
    parser.add_argument("--resume-notarization", metavar="BUILD_DIRECTORY",
                        help="finish the saved Apple submission in a partial release build")
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("macOS is required")
    if args.resume_notarization:
        if args.release or args.identity:
            parser.error("resume-notarization cannot rebuild or re-sign the saved app")
        if not args.notary_profile:
            parser.error("resume-notarization requires --notary-profile")
        try:
            resume_notarization(args.resume_notarization, args.notary_profile)
        except ValueError as error:
            parser.error(str(error))
        return
    if args.release and (not args.identity or not args.notary_profile):
        parser.error("release requires --identity and --notary-profile; no unsigned release fallback")
    if args.identity and not args.identity.startswith("Developer ID Application:"):
        parser.error("identity must be a Developer ID Application identity")
    arch = platform.machine()
    if arch not in ("arm64", "x86_64"):
        parser.error("unsupported architecture")
    try:
        receipt = source_receipt(args.release)
        receipt.update(bundle_version())
    except ValueError as error:
        parser.error(str(error))
    build_root = ROOT / "build"
    build_root.mkdir(exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="desktop-", dir=build_root))
    with tempfile.TemporaryDirectory(prefix="packaging-", dir=build_root) as scratch:
        scratch = Path(scratch)
        command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--onedir",
                   "--name", "codex-migrate-engine", "--paths", ROOT / "src",
                   "--distpath", scratch / "dist", "--workpath", scratch / "work",
                   "--specpath", scratch, "--target-arch", arch]
        if args.identity:
            command += ["--codesign-identity", args.identity]
        run(*command, ROOT / "desktop/engine_entry.py")
        app = output / "Codex Migrate.app"
        contents = app / "Contents"
        executable = contents / "MacOS/CodexMigrate"
        resources = contents / "Resources"
        executable.parent.mkdir(parents=True)
        resources.mkdir()
        shutil.copytree(scratch / "dist/codex-migrate-engine", resources / "engine", symlinks=True)
        shutil.copy2(ROOT / "desktop/Info.plist", contents / "Info.plist")
        shutil.copy2(ROOT / "LICENSE", resources / "LICENSE.txt")
        shutil.copy2(ROOT / "docs/desktop-setup.md", resources / "Read me.md")
        for document in ("recovery.md", "security-model.md", "support.md"):
            shutil.copy2(ROOT / "docs" / document, resources / document)
        (resources / "build-info.json").write_text(json.dumps(receipt, indent=2) + "\n")
        run("xcrun", "swiftc", "-parse-as-library", "-O", "-target", arch + "-apple-macos13.0",
            ROOT / "desktop/CodexMigrate.swift", ROOT / "desktop/SavedSetup.swift", "-o", executable)
        signing = ["codesign", "--force", "--sign", args.identity or "-"]
        if args.identity:
            signing += ["--options", "runtime", "--timestamp"]
        run(*signing, app)
        run("codesign", "--verify", "--deep", "--strict", app)
        engine_version = subprocess.check_output(
            [str(resources / "engine/codex-migrate-engine"), "--version"], cwd=ROOT, text=True,
        ).strip()
        if engine_version != receipt["version"]:
            raise ValueError("packaged engine and app versions do not match")
        if args.release:
            current_source = source_receipt(release=True)
            if current_source["source_revision"] != receipt["source_revision"]:
                raise ValueError("source revision changed during build; release stopped")
            submission = scratch / "submission.zip"
            run("ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", app, submission)
            receipt["notarization"] = notarize(submission, args.notary_profile, output)
            run("xcrun", "stapler", "staple", app)
            run("xcrun", "stapler", "validate", app)
            run("spctl", "--assess", "--type", "execute", "--verbose=2", app)
        artifact = publish_artifact(app, output, receipt, scratch)
        print("Build mode:", "release (signed and notarized)" if args.release else "local test only; not for distribution")
        print("Built at:", datetime.now(timezone.utc).isoformat())
        print("Artifact:", artifact)


if __name__ == "__main__":
    main()
