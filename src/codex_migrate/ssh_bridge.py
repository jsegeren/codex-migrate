"""Internal rsync remote-shell adapter. Preserve stdin and the process group."""

import base64
import json
import os
import shlex

from codex_migrate.config import MigrationConfig, SSHOptions, TARGET_PATTERN
from codex_migrate.errors import MigrationError
from codex_migrate.machines import destination_guard
from codex_migrate.destination_lock import locked_receiver_command
from codex_migrate.transport import SSHTransport


def run(arguments):
    try:
        if not arguments or len(arguments[0]) > 16384:
            raise ValueError("invalid adapter configuration")
        payload = json.loads(base64.b64decode(arguments[0], altchars=b"-_", validate=True))
        if not isinstance(payload, dict) or set(payload) != {"target", "target_home", "ssh", "comparison"}:
            raise ValueError("invalid adapter fields")
        target = payload["target"]
        if not isinstance(target, str) or not TARGET_PATTERN.fullmatch(target):
            raise ValueError("invalid destination")
        options = SSHOptions(**payload["ssh"]).validate()
        guard = destination_guard(payload["comparison"])
        args = list(arguments[1:])
        user, host = target.split("@", 1)
        # Both Apple openrsync and classic rsync remote-shell conventions.
        if args[:1] == ["-l"]:
            if len(args) < 3 or args[1] != user:
                raise ValueError("remote user mismatch")
            args = args[2:]
            expected = {host, host.strip("[]")}
        else:
            expected = {target, user + "@" + host.strip("[]")}
        if not args or args.pop(0) not in expected:
            raise ValueError("remote host mismatch")
        if len(args) < 3 or args[0] not in ("rsync", "/usr/bin/rsync") or args[1] != "--server":
            raise ValueError("unexpected rsync command")
        if "--sender" in args:
            raise ValueError("reverse transfer is unsupported")
        # Inputs are argument values, never executable shell fragments. In
        # particular a destination containing spaces/quotes remains one path.
        receiver = "exec /usr/bin/rsync " + " ".join(shlex.quote(arg) for arg in args[1:])
        script = guard + locked_receiver_command(payload["target_home"], receiver)
        config = MigrationConfig(target=target, target_home=payload["target_home"], ssh=options)
        command = SSHTransport(config).ssh_base() + [target, "/bin/zsh -f -c " + shlex.quote(script)]
    except (ValueError, TypeError, KeyError, MigrationError) as error:
        raise MigrationError("Rsync destination validation failed. No SSH connection was started.") from error
    # Replacing this adapter with SSH retains rsync's cancellation process group.
    # Do not print anything: stdout/stdin carry the binary rsync protocol.
    os.execv(command[0], command)
