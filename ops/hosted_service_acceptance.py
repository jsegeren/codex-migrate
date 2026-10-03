"""Operator-only synthetic acceptance against the real HTTPS service.

No fake entitlement, self-issued capability, production origin, or bearer-token
argument is supported. Enroll separate synthetic devices through the sandbox
purchase/email flow first. Device secrets stay in the native helper's Keychain.
This is not a customer command and is not a complete release certification.
"""

import argparse
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import uuid

from codex_migrate.vault_backup import _metadata, _fsync_directory, _atomic_json
from codex_migrate.vault_hosted_enrollment_client import HostedEnrollmentClient
from codex_migrate.vault_hosted_live_run import HostedLiveBackupRun
from codex_migrate.vault_recovery import restore_snapshot
from codex_migrate.vault_remote_recovery import (
    download_encrypted_snapshot, import_encrypted_recovery_key,
)

PREVIEW = re.compile(
    r"https://codex-migrate-[a-z0-9]+-joshuas-projects-d3a5c48d\.vercel\.app\Z")
LIMIT = 5_000_000
MARKER = ".synthetic-hosted-acceptance.json"
THREAD = "47210000-0000-4000-8000-000000004721"
RELATIVE = "sessions/2026/10/03/acceptance.jsonl"


def require(value):
    if not value:
        raise ValueError("acceptance_precondition_failed")


def outside_live_state(path):
    path = Path(path).resolve()
    lexical = (Path.home() / ".codex", Path.home() / "Library/Application Support/Codex Vault",
               Path.home() / "Library/Application Support/Codex Migrate")
    protected = lexical + tuple(p.resolve() for p in lexical)
    require(all(path != p and p not in path.parents and path not in p.parents
                for p in protected))


def private_file(path):
    """Refuse links, inherited-readable credentials, and a different owner."""
    path = Path(path)
    require(path.is_absolute())
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
            and info.st_mode & 0o077 == 0 and info.st_size <= 16_384)
    return path


def private_root(path):
    path = Path(path)
    outside_live_state(path)
    require(path.is_absolute() and str(path) == str(path.resolve())
            and path != Path.home() and len(path.parts) >= 4)
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and info.st_mode & 0o077 == 0)
    return path


def write_new(path, data):
    fd, temporary = tempfile.mkstemp(prefix=".acceptance-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        # Atomic no-clobber publication: a failed write cannot leave a truncated
        # attempt marker that owns a remote publication it cannot reconcile.
        os.link(temporary, str(path))
        _fsync_directory(path.parent)
    finally:
        os.unlink(temporary)
        _fsync_directory(path.parent)


def fixture_bytes(case_id):
    require(str(uuid.UUID(case_id)) == case_id)
    return (json.dumps({"type": "session_meta", "payload": {"id": THREAD}})
            + "\n" + json.dumps({"type": "event_msg", "payload": {
                "type": "user_message", "message":
                "SYNTHETIC-CLOUD-RECOVERY-4721: preserve this business decision " + case_id}})
            + "\n").encode()


def prepare(root):
    """Create a fresh, bounded home; never accepts or edits a real Codex home."""
    outside_live_state(root)
    require(root.is_absolute() and str(root) == str(root.resolve())
            and not root.exists() and len(root.parts) >= 4)
    case_id = str(uuid.uuid4())
    root.mkdir(mode=0o700)
    _fsync_directory(root.parent)
    source = root / "source-home"
    source.mkdir(mode=0o700)
    transcript = source / ".codex" / RELATIVE
    transcript.parent.mkdir(mode=0o700, parents=True)
    write_new(transcript, fixture_bytes(case_id))
    # Deliberate exclusion sentinel: these bytes must never enter a backup.
    write_new(source / ".codex/auth.json", b'{"synthetic":"NEVER-BACK-UP-AUTH"}')
    marker = {"format": "synthetic-hosted-acceptance-v1", "caseId": case_id}
    write_new(root / MARKER, json.dumps(marker).encode())
    for directory in (transcript.parent, *transcript.parent.parents):
        _fsync_directory(directory)
        if directory == root:
            break
    return {"fixture_prepared": True}


def checked_fixture(root):
    root = private_root(root)
    marker = json.loads(private_file(root / MARKER).read_text())
    require(set(marker) == {"format", "caseId"}
            and marker["format"] == "synthetic-hosted-acceptance-v1")
    uuid.UUID(marker["caseId"])
    source = private_root(root / "source-home")
    codex = source / ".codex"
    require(not codex.is_symlink())
    found = set()
    for path in codex.rglob("*"):
        require(not path.is_symlink())
        if path.is_file():
            found.add(path.relative_to(codex).as_posix())
    require(found == {RELATIVE, "auth.json"}
            and (codex / RELATIVE).read_bytes() == fixture_bytes(marker["caseId"])
            and (codex / "auth.json").read_bytes() == b'{"synthetic":"NEVER-BACK-UP-AUTH"}')
    return root, source


def exact_catalog(catalog, expected):
    require(len(catalog) == 1)
    item = catalog[0]
    require(item.get("collection") == "active" and item.get("path") == RELATIVE.split("sessions/", 1)[1]
            and item.get("thread_id") == THREAD and item.get("size") == len(expected)
            and item.get("sha256") == hashlib.sha256(expected).hexdigest()
            and item.get("at_risk") is False)


def clients(args):
    require(PREVIEW.fullmatch(args.service_origin))
    for value in (args.device_id, args.account_id, args.vault_id):
        require(str(uuid.UUID(value)) == value)
    upload, recovery = HostedEnrollmentClient(args.service_origin).backup_clients(
        args.device_id, crypto_helper=args.crypto_helper)
    require(upload._account_id == args.account_id and upload._vault_id == args.vault_id)
    return upload, recovery


def publish(args):
    root, source = checked_fixture(Path(args.root))
    require(not (root / "published.json").exists())
    metadata_path = Path(args.metadata).resolve()
    require(root != metadata_path and root not in metadata_path.parents)
    metadata = json.loads(private_file(args.metadata).read_text())
    key_id = _metadata(metadata)
    case_id = json.loads(private_file(root / MARKER).read_text())["caseId"]
    expected = fixture_bytes(case_id)
    upload, recovery = clients(args)
    run = HostedLiveBackupRun(upload, recovery, str(source))
    latest = recovery.latest_snapshot(expected_account_id=args.account_id)
    attempt = {"format": "synthetic-hosted-attempt-v1", "caseId": case_id,
               "accountId": args.account_id, "vaultId": args.vault_id, "keyId": key_id,
               "fixtureSha256": hashlib.sha256(expected).hexdigest(), "initiallyEmpty": True}
    if (root / "attempt.json").exists():
        require(json.loads(private_file(root / "attempt.json").read_text()) == attempt)
    else:
        # Save ownership before the first write. Nonempty unowned Vaults cannot be adopted.
        require(latest is None and run.pending() is None)
        write_new(root / "attempt.json", json.dumps(attempt, sort_keys=True).encode())
    if latest is not None and run.pending() is None:
        # A committed publication may outlive the local ACK/receipt. The random case
        # nonce plus the authenticated exact catalog binds reconciliation to this attempt.
        snapshot = latest["snapshotId"]
        require(latest["sourceCoverage"] == "complete")
    else:
        result = run.back_up_live_history(metadata, crypto_helper=args.crypto_helper,
                                          max_prior_bytes=LIMIT, apply=True)
        require(result.get("sourceCoverage") == "complete" and result.get("atRiskThreads") == 0)
        snapshot = result["snapshotId"]
    observed, catalog = recovery.prior_catalog(
        key_id=key_id, crypto_helper=args.crypto_helper, max_bytes=LIMIT,
        expected_snapshot_id=snapshot, expected_account_id=args.account_id)
    require(observed == snapshot)
    exact_catalog(catalog, expected)
    checked_fixture(root)
    second = run.back_up_live_history(metadata, crypto_helper=args.crypto_helper,
                                      max_prior_bytes=LIMIT, apply=True)
    require(second.get("unchanged") is True and second.get("lastGoodSnapshotId") == snapshot)
    checked_fixture(root)
    receipt = {"format": "synthetic-hosted-service-publication-v1",
               "caseId": case_id,
               "accountId": args.account_id, "vaultId": args.vault_id,
               "snapshotId": snapshot, "fixtureSha256": hashlib.sha256(expected).hexdigest(),
               "authenticated_publication": True, "remote_manifest_authenticated": True,
               "unchanged_run_reused_snapshot": True,
               "service_requests": upload.service_request_counts(),
               "worker_requests": upload.worker_attempt_counts()}
    write_new(root / "published.json", json.dumps(receipt, sort_keys=True).encode())
    return receipt


def recover(args):
    # Execute in the independent VM with its own enrolled recovery device.
    root = private_root(args.root)
    require(not (root / "recovered.json").exists())
    for name in (args.publication_receipt, args.recovery_key_file):
        path = Path(name).resolve()
        require(root != path and root not in path.parents)
    published = json.loads(private_file(args.publication_receipt).read_text())
    expected = fixture_bytes(published["caseId"])
    require(published.get("format") == "synthetic-hosted-service-publication-v1"
            and published.get("accountId") == args.account_id
            and published.get("vaultId") == args.vault_id
            and published.get("fixtureSha256") == hashlib.sha256(expected).hexdigest())
    binding = {"format": "synthetic-hosted-receiver-v1", "caseId": published["caseId"],
               "accountId": args.account_id, "vaultId": args.vault_id,
               "snapshotId": published["snapshotId"], "fixtureSha256": published["fixtureSha256"]}
    attempt_path = root / "receiver-attempt.json"
    if attempt_path.exists():
        attempt = json.loads(private_file(attempt_path).read_text())
        require({k: v for k, v in attempt.items() if k != "restoreOutput"} == binding
                and re.fullmatch(r"restored(?:-[0-9a-f-]{36})?", attempt.get("restoreOutput", "")))
    else:
        require(not any((root / p).exists() for p in ("empty-home", "downloaded-vault", "restored")))
        attempt = {**binding, "restoreOutput": "restored"}
        write_new(attempt_path, json.dumps(attempt, sort_keys=True).encode())
    _, recovery = clients(args)
    receipt, store = recovery.prepare(max_bytes=LIMIT,
                                     selected_snapshot_id=published["snapshotId"])
    home = root / "empty-home"
    if not home.exists():
        home.mkdir(mode=0o700)
        _fsync_directory(root)
    private_root(home)
    require(not list(home.iterdir()))
    vault = root / "downloaded-vault"
    key = private_file(args.recovery_key_file).read_text().strip()
    import_encrypted_recovery_key(str(home), str(vault), store, receipt, key,
                                 max_bytes=LIMIT, crypto_helper=args.crypto_helper)
    download_encrypted_snapshot(str(home), str(vault), store, receipt,
                                max_bytes=LIMIT, crypto_helper=args.crypto_helper)
    restored = root / attempt["restoreOutput"]
    def matches():
        if not restored.exists():
            return False
        private_root(restored)
        entries = list(restored.rglob("*"))
        require(not any(p.is_symlink() for p in entries))
        return ({p.relative_to(restored).as_posix() for p in entries if p.is_file()} == {RELATIVE}
                and (restored / RELATIVE).read_bytes() == expected)
    if restored.exists() and not matches():
        # Preserve partial output; never clobber it on a retry.
        attempt = {**binding, "restoreOutput": "restored-" + str(uuid.uuid4())}
        _atomic_json(attempt_path, attempt, replace=True)
        restored = root / attempt["restoreOutput"]
    if not restored.exists():
        restore_snapshot(str(home), str(vault), str(restored), crypto_helper=args.crypto_helper)
    require(matches())
    result = {"authenticated_remote_recovery": True, "exact_restored_bytes": True,
              "authentication_material_excluded": True,
              "snapshotId": published["snapshotId"],
              # Host independence, scheduling and billing need separate receipts.
              "complete_release_acceptance": False}
    write_new(root / "recovered.json", json.dumps(result, sort_keys=True).encode())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "publish", "recover"))
    parser.add_argument("--root", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--vercel-preview-transport", action="store_true",
                        help="Operator-only: use the existing authorized Vercel CLI session")
    for name in ("service-origin", "device-id", "account-id", "vault-id", "crypto-helper",
                 "metadata", "publication-receipt", "recovery-key-file"):
        parser.add_argument("--" + name)
    args = parser.parse_args()
    try:
        require(args.apply)
        context = nullcontext()
        if args.vercel_preview_transport:
            require(args.action != "prepare")
            from vercel_preview_transport import protected_preview
            context = protected_preview(args.service_origin, Path(__file__).resolve().parents[1])
        with context:
            result = {"prepare": lambda: prepare(Path(args.root)),
                      "publish": lambda: publish(args), "recover": lambda: recover(args)}[args.action]()
    except Exception:
        # Provider/helper exceptions can contain signed URLs, keys or source text.
        print(json.dumps({"passed": False, "action": args.action,
                          "code": "hosted_acceptance_failed", "preserve_pending_state": True}))
        return 1
    print(json.dumps({"passed": True, "action": args.action, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
