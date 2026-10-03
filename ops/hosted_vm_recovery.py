"""Host-only recovery runner for the one owned disposable acceptance Mac.

Stopping a Tart client does not prove its guest command stopped. Always stop
the owned test VM and verify its live state before accepting or returning.
This is not a customer path and never accepts a different VM or host credential.
"""
import json
from pathlib import PurePosixPath
import subprocess
import uuid

from preview_stdio_transport import relay_process, require

TART = "/Users/jsegeren/.local/share/codex-backup-acceptance/tools/tart.app/Contents/MacOS/tart"
VM = "codex-backup-clean-acceptance"
ROOT = "/Users/admin/codex-backup-relay-test-20261003"
PYTHON = "/Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14"
ENV = {"HOME": "/Users/jsegeren", "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
       "TART_HOME": "/Users/jsegeren/.local/share/codex-backup-acceptance/vms"}


def tart(arguments):
    return subprocess.run([TART, *arguments], env=ENV, capture_output=True, timeout=30)


def running():
    result = tart(["list", "--source", "local", "--format", "json"])
    require(result.returncode == 0 and len(result.stdout) <= 64 * 1024)
    entries = json.loads(result.stdout)
    require(isinstance(entries, list))
    entries = [item for item in entries if isinstance(item, dict) and item.get("Name") == VM]
    require(len(entries) == 1 and entries[0].get("Source") == "local"
            and type(entries[0].get("Running")) is bool
            and entries[0].get("State") == ("running" if entries[0]["Running"] else "stopped"))
    return entries[0]["Running"]


def stop_and_verify():
    # A failed metadata query must not prevent the containment attempt. The
    # fixed target is owned; final live stopped state is the authority, even
    # when stop timed out or raced with an already-completed shutdown.
    try:
        tart(["stop", VM])
    except (OSError, subprocess.SubprocessError):
        pass
    require(not running())


def private_guest_path(value):
    require(isinstance(value, str) and len(value) <= 4096
            and not any(c in value for c in "\r\n\x00"))
    path = PurePosixPath(value)
    require(path.is_absolute() and str(path) == value and ".." not in path.parts
            and PurePosixPath(ROOT) in path.parents)
    return value


def recover_in_vm(origin, working_directory, inputs):
    """Require caller's already-booted dedicated VM; no automatic startup.

    Inputs are opaque IDs and guest-private file paths, never key/token values.
    The existing guest harness checks file ownership and source/receipt binding.
    """
    fields = {"root", "device_id", "account_id", "vault_id", "crypto_helper",
              "publication_receipt", "recovery_key_file"}
    require(isinstance(inputs, dict) and set(inputs) == fields)
    for field in ("device_id", "account_id", "vault_id"):
        value = inputs[field]
        require(isinstance(value, str) and str(uuid.UUID(value)) == value
                and uuid.UUID(value).version == 4)
    for field in fields - {"device_id", "account_id", "vault_id"}:
        private_guest_path(inputs[field])
    require(running())
    try:
        command = [TART, "exec", "-i", VM, "/usr/bin/env",
            "PYTHONPATH=" + ROOT + "/src:" + ROOT + "/ops", "SSL_CERT_FILE=/etc/ssl/cert.pem",
            PYTHON, ROOT + "/ops/hosted_service_acceptance.py", "recover",
            "--stdio-preview-recovery", "--apply", "--service-origin", origin]
        for field in sorted(fields):
            command.extend(["--" + field.replace("_", "-"), inputs[field]])
        result = relay_process(command, origin, working_directory, environment=ENV)
    except Exception:
        raise ValueError("owned_vm_recovery_failed") from None
    finally:
        try:
            stop_and_verify()
        except Exception:
            raise ValueError("owned_vm_shutdown_not_verified") from None
    return {**result, "owned_vm_stopped_verified": True}
