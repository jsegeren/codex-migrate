"""Prepare a disposable build-16 client for the private paid build-17 canary.

This never edits the shipped archive, live appcast, or release catalog. It
contains no purchase credential. Use only with the bounded Production canary
documented in docs/in-app-updates.md; this is not release acceptance.
"""

import argparse
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
OLD_SOURCE = "c6d2bdf81e7093a044886dd35e1b97ed8ce40ea3"
CURRENT_SOURCE = "fe1ebea10e51ea2a999d6dfe32e8f21c9dfd2b25"
OLD_SHA256 = "60eff4dcb07088d01c966587e808f21d5fa74b8afb4eba45ed326543f07241f7"
OLD_PUBLIC_KEY = "xm7MLPjJBQcWcm2t8rXSoOoPk5ENifmVZPI52GwUoHs="
CANARY_ID = "codex-migrate-build17-vault-integrated-arm64"
CANARY_SHA256 = "62615a110984a933cd1dd11ad95440be374228294e14e745bf9b1768f7d02118"
CANARY_SIGNATURE = "LmfjnSfRymcMZo5a+Y02Vpj77dNUPwmGU+u64NIS1HUb8+/npoGDArtOKSsw0JeSVQM2NTLaUJG78mq5VWGPCQ=="
ARCHIVE = ROOT / "build/live-build16/Codex-Migrate-0.1.0-build16-arm64.zip"
CANDIDATE_DMG = ROOT / "build/desktop-rotation-n_p3sxag/Codex-Migrate-0.1.0-build17-arm64.dmg"
HEADER_HOOK = 'request.setValue("Bearer \\(token)", forHTTPHeaderField: "Authorization")'
TOKEN_LOOKUP = '    static func savedToken() -> String? {\n'
HELPER_START = '        _ = updaterController\n        startHelper()\n'
CANARY_TOKEN_LOOKUP = '''    // Disposable test client only: consume a private token from a closed stdin pipe.
    // Nothing is written to Keychain, argv, the environment, the helper, or disk.
    private static let pipedCanaryToken: String? = {
        guard let value = String(data: FileHandle.standardInput.readDataToEndOfFile(), encoding: .utf8) else { return nil }
        return token(from: value)
    }()

    static func savedToken() -> String? {
        if let token = pipedCanaryToken { return token }
'''


def run(*args, timeout=180):
    subprocess.run([str(arg) for arg in args], check=True, timeout=timeout)


def canary():
    releases = json.loads((ROOT / "commerce/releases.json").read_text())
    selected = releases[CANARY_ID]
    if selected.get("accepted") is not False or selected.get("testingOnly") is not True:
        raise ValueError("canary is no longer a sandbox-only, unaccepted candidate")
    if selected.get("source") != CURRENT_SOURCE:
        raise ValueError("candidate source changed")
    if selected.get("sha256") != CANARY_SHA256:
        raise ValueError("candidate artifact changed")
    if (selected.get("size") != 11224541 or
            selected.get("sparkleSignature") != CANARY_SIGNATURE or
            selected.get("pathname") != f"sandbox/{CANARY_SHA256}/Codex-Migrate-0.1.0-build17-arm64.dmg" or
            selected.get("diskImageNotarization") != {
                "status": "Accepted", "id": "d27e3814-d9d2-4227-8d4d-9c09565ee5d2"}):
        raise ValueError("candidate signature or size changed")
    return selected


def appcast_xml(selected, archive_url="https://migrate.segeren.com/api/update-archive",
                signature_override=None):
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            '<rss version="2.0" xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">'
            '<channel><title>Codex Migrate private canary</title>'
            '<item><title>Codex Migrate 0.1.0 (build 17)</title>'
            '<sparkle:version>17</sparkle:version>'
            '<sparkle:shortVersionString>0.1.0</sparkle:shortVersionString>'
            '<sparkle:minimumSystemVersion>13.0.0</sparkle:minimumSystemVersion>'
            '<sparkle:hardwareRequirements>arm64</sparkle:hardwareRequirements>'
            f'<enclosure url="{archive_url}" '
            f'sparkle:edSignature="{signature_override or selected["sparkleSignature"]}" '
            f'length="{selected["size"]}" type="application/x-apple-diskimage"/>'
            '</item></channel></rss>\n').encode()


def add_canary_header(source):
    if source.count(HEADER_HOOK) != 1 or "X-Codex-Migrate-Canary" in source:
        raise ValueError("archived updater request hook changed")
    return source.replace(
        HEADER_HOOK,
        HEADER_HOOK + '\n        request.setValue("' + CANARY_ID
        + '", forHTTPHeaderField: "X-Codex-Migrate-Canary")')


def add_background_check(source):
    if source.count(HELPER_START) != 1 or "checkForUpdatesInBackground" in source:
        raise ValueError("archived startup hook changed")
    return source.replace(HELPER_START, HELPER_START + '''        // Disposable test client only: exercise the background paid update path once.
        DispatchQueue.main.asyncAfter(deadline: .now() + .seconds(3)) {
            self.updaterController.updater.checkForUpdatesInBackground()
        }
''')


def add_piped_test_token(source):
    if source.count(TOKEN_LOOKUP) != 1 or "pipedCanaryToken" in source:
        raise ValueError("archived entitlement lookup changed")
    return source.replace(TOKEN_LOOKUP, CANARY_TOKEN_LOOKUP)


def prepare(output, port, identity, local_archive=False, current_app=None):
    selected = canary()
    if current_app is not None and not local_archive:
        raise ValueError("current-source synthetic client requires local-only archive mode")
    if output.exists() or output.is_symlink() or output.parent.resolve() != (ROOT / "build").resolve():
        raise ValueError("output must be a new direct child of build/")
    if current_app is None and hashlib.sha256(ARCHIVE.read_bytes()).hexdigest() != OLD_SHA256:
        raise ValueError("live build-16 archive checksum mismatch")
    if (CANDIDATE_DMG.stat().st_size != selected["size"] or
            hashlib.sha256(CANDIDATE_DMG.read_bytes()).hexdigest() != selected["sha256"]):
        raise ValueError("local canary DMG does not match the sandbox catalog")
    if not 1024 <= port <= 65535:
        raise ValueError("choose a dedicated loopback port from 1024 to 65535")
    if current_app is not None:
        current_app = current_app.resolve(strict=True)
        receipt = json.loads((current_app / "Contents/Resources/build-info.json").read_text())
        with (current_app / "Contents/Info.plist").open("rb") as stream:
            current_info = plistlib.load(stream)
        if (receipt.get("source_revision") != CURRENT_SOURCE or
                receipt.get("bundle_version") != "17" or
                current_info.get("CFBundleVersion") != "17"):
            raise ValueError("current-source base app does not match exact build 17")
        run("codesign", "--verify", "--deep", "--strict", current_app)
    output.mkdir(mode=0o700)
    app = output / "Codex Migrate.app"
    if current_app is None:
        run("ditto", "-x", "-k", ARCHIVE, output)
    else:
        run("ditto", current_app, app)
    receipt = json.loads((app / "Contents/Resources/build-info.json").read_text())
    if receipt.get("source_revision") != (CURRENT_SOURCE if current_app else OLD_SOURCE):
        raise ValueError("app source receipt does not match selected test client")
    info_path = app / "Contents/Info.plist"
    with info_path.open("rb") as stream:
        info = plistlib.load(stream)
    if (info.get("CFBundleVersion") != ("17" if current_app else "16") or
            (current_app is None and info.get("SUPublicEDKey") != OLD_PUBLIC_KEY) or
            info.get("SUFeedURL") != "https://migrate.segeren.com/api/appcast"):
        raise ValueError("base app identity/feed does not match the selected build")
    if current_app is not None:
        # A disposable current-code client must appear older to exercise
        # build 17's own automatic-idle path against the exact signed DMG.
        # It is never notarized or delivered to buyers.
        info["CFBundleVersion"] = "16"
        info["SUPublicEDKey"] = OLD_PUBLIC_KEY
    info["SUFeedURL"] = f"http://127.0.0.1:{port}/appcast"
    with info_path.open("wb") as stream:
        plistlib.dump(info, stream)

    frameworks = app / "Contents/Frameworks"
    executable = app / "Contents/MacOS/CodexMigrate"
    with tempfile.TemporaryDirectory(prefix="paid-canary-source-", dir=output) as scratch:
        sources = []
        filenames = ("CodexMigrate.swift", "UpdateEntitlement.swift", "SavedSetup.swift")
        if current_app is not None:
            filenames += ("InstallLocation.swift", "DuplicateLaunch.swift")
        for filename in filenames:
            source = subprocess.check_output(
                ["git", "show", f"{CURRENT_SOURCE if current_app else OLD_SOURCE}:desktop/{filename}"],
                cwd=ROOT, text=True)
            if filename == "CodexMigrate.swift":
                source = add_background_check(source if local_archive else add_canary_header(source))
            elif filename == "UpdateEntitlement.swift":
                source = add_piped_test_token(source)
            path = Path(scratch) / filename
            path.write_text(source)
            sources.append(path)
        run("xcrun", "swiftc", "-parse-as-library", "-O", "-target", "arm64-apple-macos13.0",
            "-F", frameworks, "-framework", "Sparkle", "-Xlinker", "-rpath",
            "-Xlinker", "@executable_path/../Frameworks", *sources, "-o", executable)
    run("codesign", "--force", "--sign", identity, "--options", "runtime", "--timestamp", app,
        timeout=60)
    run("codesign", "--verify", "--deep", "--strict", app)
    with info_path.open("rb") as stream:
        signed_info = plistlib.load(stream)
    if (signed_info["CFBundleVersion"] != "16" or
            signed_info["SUPublicEDKey"] != OLD_PUBLIC_KEY or
            signed_info["SUFeedURL"] != f"http://127.0.0.1:{port}/appcast"):
        raise ValueError("test client build/feed verification failed")
    print("Prepared disposable signed canary client:", app)
    print("Candidate:", selected["id"], "(current-code local archive)" if current_app else
          "(local archive)" if local_archive else
          "(sandbox-only; public release unchanged)")


def serve(port, local_archive=False, fault="none"):
    selected = canary()
    if fault not in ("none", "archive-404", "corrupt-archive", "bad-signature"):
        raise ValueError("unknown local update fault")
    if fault != "none" and not local_archive:
        raise ValueError("fault injection is local-only")
    if local_archive and (CANDIDATE_DMG.stat().st_size != selected["size"] or
                          hashlib.sha256(CANDIDATE_DMG.read_bytes()).hexdigest() != selected["sha256"]):
        raise ValueError("local DMG does not match the exact sandbox candidate")
    xml = appcast_xml(selected, f"http://127.0.0.1:{port}/archive" if local_archive else
                      "https://migrate.segeren.com/api/update-archive",
                      base64.b64encode(bytes(64)).decode() if fault == "bad-signature" else None)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/archive" and local_archive:
                if fault == "archive-404":
                    print("local_fixture_archive_http=404", flush=True)
                    self.send_error(404)
                    return
                print("local_fixture_archive_http=200 fault=" + fault, flush=True)
                self.send_response(200)
                self.send_header("Content-Type", "application/x-apple-diskimage")
                self.send_header("Content-Length", str(selected["size"]))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                with CANDIDATE_DMG.open("rb") as archive:
                    if fault == "corrupt-archive":
                        first = archive.read(1)
                        self.wfile.write(bytes([first[0] ^ 1]))
                    shutil.copyfileobj(archive, self.wfile)
                return
            if self.path != "/appcast":
                self.send_error(404)
                return
            if local_archive:
                print("local_fixture_appcast_http=200 fault=" + fault, flush=True)
            self.send_response(200)
            self.send_header("Content-Type", "application/rss+xml; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(xml)))
            self.end_headers()
            self.wfile.write(xml)

        def log_message(self, _format, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Canary feed listening on http://127.0.0.1:{port}/appcast", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "serve"))
    parser.add_argument("--port", type=int, default=8898)
    parser.add_argument("--output", type=Path, default=ROOT / "build/paid-update-canary-client")
    parser.add_argument("--identity", default="Developer ID Application: Joshua Segeren (P9J3JK79KQ)")
    parser.add_argument("--local-archive", action="store_true",
                        help="serve exact local DMG without any Production canary or paid credential")
    parser.add_argument("--current-app", type=Path,
                        help="with --local-archive, use exact signed build-17 app code in a disposable build-16 wrapper")
    parser.add_argument("--fault", choices=("none", "archive-404", "corrupt-archive", "bad-signature"),
                        default="none", help="with local serve only, inject one updater failure")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.output, args.port, args.identity, args.local_archive, args.current_app)
    else:
        serve(args.port, args.local_archive, args.fault)


if __name__ == "__main__":
    main()
