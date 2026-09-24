"""Prepare a disposable build-16 client for the private paid build-17 canary.

This never edits the shipped archive, live appcast, or release catalog. It
contains no purchase credential. Use only with the bounded Production canary
documented in docs/in-app-updates.md; this is not release acceptance.
"""

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import plistlib
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
OLD_SOURCE = "c6d2bdf81e7093a044886dd35e1b97ed8ce40ea3"
OLD_SHA256 = "60eff4dcb07088d01c966587e808f21d5fa74b8afb4eba45ed326543f07241f7"
CANARY_ID = "codex-migrate-0.1.0-build17-abort-guard-arm64"
ARCHIVE = ROOT / "build/desktop-wm6vw05x/Codex-Migrate-0.1.0-build16-arm64.zip"
CANDIDATE_DMG = ROOT / "build/desktop-rotation-fsfhlg3d/Codex-Migrate-0.1.0-build17-arm64.dmg"
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
    if selected.get("source") != "27ef9bf1d4c89ae9fb1853ed0e37a57458db39cf":
        raise ValueError("candidate source changed")
    if selected.get("sha256") != "bf33da502e15a012c287efc5cec6c9b3057bf544c9ebbf8d9aebb1d91d2c1dc6":
        raise ValueError("candidate artifact changed")
    if selected.get("size") != 10376201 or not selected.get("sparkleSignature"):
        raise ValueError("candidate signature or size changed")
    return selected


def appcast_xml(selected):
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            '<rss version="2.0" xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">'
            '<channel><title>Codex Migrate private canary</title>'
            '<item><title>Codex Migrate 0.1.0 (build 17)</title>'
            '<sparkle:version>17</sparkle:version>'
            '<sparkle:shortVersionString>0.1.0</sparkle:shortVersionString>'
            '<sparkle:minimumSystemVersion>13.0.0</sparkle:minimumSystemVersion>'
            '<sparkle:hardwareRequirements>arm64</sparkle:hardwareRequirements>'
            '<enclosure url="https://migrate.segeren.com/api/update-archive" '
            f'sparkle:edSignature="{selected["sparkleSignature"]}" '
            f'length="{selected["size"]}" type="application/x-apple-diskimage"/>'
            '</item></channel></rss>\n').encode()


def add_canary_header(source):
    if source.count(HEADER_HOOK) != 1 or "X-Codex-Migrate-Canary" in source:
        raise ValueError("archived updater request hook changed")
    source = source.replace(
        HEADER_HOOK,
        HEADER_HOOK + '\n        request.setValue("' + CANARY_ID
        + '", forHTTPHeaderField: "X-Codex-Migrate-Canary")')
    if source.count(HELPER_START) != 1:
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


def prepare(output, port, identity):
    selected = canary()
    if output.exists() or output.is_symlink() or output.parent.resolve() != (ROOT / "build").resolve():
        raise ValueError("output must be a new direct child of build/")
    if hashlib.sha256(ARCHIVE.read_bytes()).hexdigest() != OLD_SHA256:
        raise ValueError("live build-16 archive checksum mismatch")
    if (CANDIDATE_DMG.stat().st_size != selected["size"] or
            hashlib.sha256(CANDIDATE_DMG.read_bytes()).hexdigest() != selected["sha256"]):
        raise ValueError("local canary DMG does not match the sandbox catalog")
    if not 1024 <= port <= 65535:
        raise ValueError("choose a dedicated loopback port from 1024 to 65535")
    output.mkdir(mode=0o700)
    run("ditto", "-x", "-k", ARCHIVE, output)
    app = output / "Codex Migrate.app"
    receipt = json.loads((app / "Contents/Resources/build-info.json").read_text())
    if receipt.get("source_revision") != OLD_SOURCE or receipt.get("bundle_version") != "16":
        raise ValueError("archived build source receipt does not match live build 16")
    info_path = app / "Contents/Info.plist"
    with info_path.open("rb") as stream:
        info = plistlib.load(stream)
    if (info.get("CFBundleVersion") != "16" or
            info.get("SUPublicEDKey") != "xm7MLPjJBQcWcm2t8rXSoOoPk5ENifmVZPI52GwUoHs=" or
            info.get("SUFeedURL") != "https://migrate.segeren.com/api/appcast"):
        raise ValueError("archived app identity/feed does not match live build 16")
    info["SUFeedURL"] = f"http://127.0.0.1:{port}/appcast"
    with info_path.open("wb") as stream:
        plistlib.dump(info, stream)

    frameworks = app / "Contents/Frameworks"
    executable = app / "Contents/MacOS/CodexMigrate"
    with tempfile.TemporaryDirectory(prefix="paid-canary-source-", dir=output) as scratch:
        sources = []
        for filename in ("CodexMigrate.swift", "UpdateEntitlement.swift", "SavedSetup.swift"):
            source = subprocess.check_output(
                ["git", "show", f"{OLD_SOURCE}:desktop/{filename}"], cwd=ROOT, text=True)
            if filename == "CodexMigrate.swift":
                source = add_canary_header(source)
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
    if signed_info["CFBundleVersion"] != "16" or signed_info["SUFeedURL"] != f"http://127.0.0.1:{port}/appcast":
        raise ValueError("test client build/feed verification failed")
    print("Prepared disposable signed canary client:", app)
    print("Candidate:", selected["id"], "(sandbox-only; public release unchanged)")


def serve(port):
    xml = appcast_xml(canary())

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/appcast":
                self.send_error(404)
                return
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
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.output, args.port, args.identity)
    else:
        serve(args.port)


if __name__ == "__main__":
    main()
