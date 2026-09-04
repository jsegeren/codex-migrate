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


def notarize(submission, profile, output):
    """Save the submission ID before waiting; never print credential diagnostics."""
    def request(*arguments):
        result = subprocess.run(
            ["xcrun", "notarytool", *map(str, arguments), "--keychain-profile", profile,
             "--output-format", "json"], cwd=ROOT, capture_output=True, text=True,
        )
        if result.returncode:
            raise ValueError("notarization command failed; inspect the saved submission before retrying")
        try:
            response = json.loads(result.stdout)
            identifier = str(uuid.UUID(response["id"]))
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ValueError("notarization returned an invalid receipt; release stopped") from None
        return response, identifier

    _, identifier = request("submit", submission, "--no-wait")
    record = {"id": identifier, "status": "Submitted"}
    receipt_path = output / "notary-submission.json"
    receipt_path.write_text(json.dumps(record, indent=2) + "\n")
    print("Notarization submission saved:", receipt_path, flush=True)
    response, waited_id = request("wait", identifier)
    if waited_id != identifier:
        raise ValueError("notarization submission ID changed; release stopped")
    status = response.get("status")
    record["status"] = status if status in ("Accepted", "Invalid", "Rejected") else "Unknown"
    receipt_path.write_text(json.dumps(record, indent=2) + "\n")
    if record["status"] != "Accepted":
        raise ValueError("notarization was not Accepted; no release archive created")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", action="store_true")
    parser.add_argument("--identity", help="Developer ID Application identity already in Keychain")
    parser.add_argument("--notary-profile", help="Existing notarytool Keychain profile")
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("macOS is required")
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
        print("Build mode:", "release (signed and notarized)" if args.release else "local test only; not for distribution")
        print("Built at:", datetime.now(timezone.utc).isoformat())
        print("Artifact:", artifact)


if __name__ == "__main__":
    main()
