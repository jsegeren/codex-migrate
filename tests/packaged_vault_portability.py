"""Disposable packaged-app recovery drill; no source package needed by receiver.

Transfer only the bundle and this stdlib-only script to a clean macOS guest.
The bundle contains synthetic ciphertext and a disposable recovery key. Never
print command output, keys, or restored content. A same-host run checks the
harness, not independent-Mac or real hosted-service recovery.
"""

import argparse
import json
import os
from pathlib import Path
import platform
import re
import signal
import subprocess
import tempfile


THREAD = "66666666-6666-4666-8666-666666666666"
ATTACHMENT = "77777777-7777-4777-8777-777777777777"
MARKER = "SYNTHETIC-PACKAGED-PORTABLE-ATTACHMENT"
FILES = {
    "sessions/active.jsonl": (
        json.dumps({"type": "session_meta", "payload": {"id": THREAD}}) + "\n" +
        json.dumps({"type": "response_item", "payload": {
            "role": "user", "content": [{"type": "input_text", "text":
                "# Files mentioned by the user:\n\n## Pasted text.txt: "
                "/Users/disposable/.codex/attachments/" + ATTACHMENT +
                "/pasted-text.txt\n\n## My request:\n"}]}}) + "\n").encode(),
    "archived_sessions/archived.jsonl": (
        json.dumps({"type": "session_meta", "payload": {
            "id": "88888888-8888-4888-8888-888888888888"}}) + "\n" +
        json.dumps({"type": "response_item", "payload": {
            "role": "assistant", "content": "SYNTHETIC-ARCHIVED-WORK"}}) + "\n").encode(),
    "attachments/" + ATTACHMENT + "/pasted-text.txt": MARKER.encode(),
}
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")
KEY = re.compile(r"CV1-[A-Za-z0-9_-]{43}\n?\Z")


def command(arguments, *, input_bytes=b"", allow_failure=False):
    env = {key: value for key, value in os.environ.items() if key in
           ("HOME", "USER", "LOGNAME", "TMPDIR", "LANG", "__CF_USER_TEXT_ENCODING")}
    env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
    process = subprocess.Popen(arguments, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True, env=env)
    try:
        stdout, _ = process.communicate(input=input_bytes, timeout=120)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()
        raise AssertionError("Packaged recovery command timed out") from None
    if process.returncode and not allow_failure:
        raise AssertionError("Packaged recovery command failed; output withheld")
    return process.returncode, stdout


def package(app):
    app = app.resolve(strict=True)
    command(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)])
    engine = app / "Contents/Resources/engine/codex-migrate-engine"
    helper = app / "Contents/Helpers/CodexVaultCrypto.app/Contents/MacOS/CodexVaultCrypto"
    if not engine.is_file() or not helper.is_file():
        raise AssertionError("Current packaged engine and helper required")
    metadata = json.loads((app / "Contents/Resources/build-info.json").read_text())
    revision = metadata.get("source_revision")
    if (metadata.get("source_dirty") is not False or not isinstance(revision, str) or
            not re.fullmatch(r"[0-9a-f]{40}", revision)):
        raise AssertionError("Clean committed package source required")
    return engine, helper, revision


def produce(app, bundle):
    engine, helper, revision = package(app)
    bundle.mkdir(mode=0o700)  # Existing paths, including links, are refused.
    vault = bundle / "vault"
    key_id = None
    try:
        with tempfile.TemporaryDirectory(prefix="packaged-vault-source-") as temporary:
            source = Path(temporary)
            for name, content in FILES.items():
                path = source / ".codex" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            _, output = command([str(engine), "vault", "--source-home", str(source),
                                 "backup", "--destination", str(vault), "--apply", "--json"])
            saved = json.loads(output)
            key_id = saved["key_id"]
            recovery = saved["recovery_key"]
            if (not UUID.fullmatch(key_id) or not isinstance(recovery, str) or
                    not KEY.fullmatch(recovery) or saved.get("needs_attention") is not False):
                raise AssertionError("Synthetic first snapshot was not complete")
            command([str(engine), "vault", "verify", "--vault", str(vault), "--json"])
            descriptor = os.open(bundle / "recovery-key.txt",
                                 os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(recovery + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            (bundle / "fixture.json").write_text(json.dumps({
                "format": "codex-backup-packaged-drill", "version": 1,
                "key_id": key_id, "source_revision": revision,
            }), encoding="utf-8")
    finally:
        if key_id is None and (vault / "vault.json").is_file():
            key_id = json.loads((vault / "vault.json").read_text())["key_id"]
        if key_id is not None and UUID.fullmatch(key_id):
            command([str(helper), "delete-key", "--key-id", key_id])
    print("Packaged synthetic snapshot prepared; producer test key removed")


def consume(app, bundle):
    engine, helper, revision = package(app)
    vault = bundle / "vault"
    key_id = json.loads((vault / "vault.json").read_text())["key_id"]
    marker = json.loads((bundle / "fixture.json").read_text())
    if marker != {"format": "codex-backup-packaged-drill", "version": 1,
                  "key_id": key_id, "source_revision": revision}:
        raise AssertionError("Only a generated disposable drill bundle is accepted")
    recovery = (bundle / "recovery-key.txt").read_bytes()
    if not UUID.fullmatch(key_id) or not KEY.fullmatch(recovery.decode("ascii")):
        raise AssertionError("Disposable recovery artifact is invalid")
    # Refuse a receiver that already has the producer key. Neither a failed
    # verify nor this script alone attests that the receiver is a clean Mac.
    status, _ = command([str(helper), "export-key", "--key-id", key_id], allow_failure=True)
    if status == 0:
        raise AssertionError("Receiver already has the test key; isolation not proven")
    status, _ = command([str(engine), "vault", "verify", "--vault", str(vault),
                         "--json"], allow_failure=True)
    if status == 0:
        raise AssertionError("Receiver already has the test key; isolation not proven")
    attempted = False
    try:
        attempted = True
        _, output = command([str(helper), "import-key", "--key-id", key_id],
                            input_bytes=recovery)
        imported = json.loads(output)
        if imported.get("key_id") != key_id or imported.get("imported") is not True:
            raise AssertionError("Packaged recovery key import did not confirm")
        command([str(engine), "vault", "verify", "--vault", str(vault), "--json"])
        with tempfile.TemporaryDirectory(prefix="packaged-vault-receiver-") as temporary:
            root = Path(temporary)
            lost_home, inspection = root / "lost-home", root / "inspection"
            lost_home.mkdir()
            inspection.mkdir()
            output = inspection / ".codex"
            command([str(engine), "vault", "--source-home", str(lost_home), "restore",
                     "--vault", str(vault), "--output", str(output), "--apply", "--json"])
            names = {path.relative_to(output).as_posix() for path in output.rglob("*")
                     if path.is_file()}
            if names != set(FILES) | {"restore-receipt.json"} or any(
                    (output / name).read_bytes() != content for name, content in FILES.items()):
                raise AssertionError("Packaged recovered files do not match the fixture")
            _, matches = command([str(engine), "vault", "--source-home", str(inspection),
                                  "search", MARKER, "--json"])
            if not any(row.get("collection") == "active" for row in json.loads(matches)):
                raise AssertionError("Recovered attachment text was not searchable")
    finally:
        # Import may persist a key before a timeout or failed reply.
        if attempted:
            command([str(helper), "delete-key", "--key-id", key_id])
    print("Packaged synthetic recovery and search passed; receiver test key removed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-disposable-test", action="store_true", required=True)
    parser.add_argument("mode", choices=("produce", "consume"))
    parser.add_argument("app", type=Path)
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args()
    if platform.system() != "Darwin" or not args.app.is_absolute() or not args.bundle.is_absolute():
        parser.error("macOS and explicit absolute app/bundle paths required")
    try:
        (produce if args.mode == "produce" else consume)(args.app, args.bundle)
    except Exception:
        raise SystemExit("Packaged recovery drill failed; private command output withheld") from None


if __name__ == "__main__":
    main()
