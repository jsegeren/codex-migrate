"""Explicit, local-only connection cards. No passwords or private-key export.

Cards must be carried directly between the user's two trusted Macs. They are
not a network discovery protocol and are never accepted from an SSH key scan.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import stat
import subprocess
import tempfile
import time

from codex_migrate.config import SSHOptions, TARGET_PATTERN
from codex_migrate.errors import MigrationError


PREFIX = "CM-CONNECT-1:"
MAX_BYTES = 8192
LIFETIME = 7 * 24 * 60 * 60


def _account(home):
    account = pwd.getpwuid(os.getuid())
    if (os.getuid() == 0 or os.getuid() != os.geteuid()
            or Path(account.pw_dir).resolve() != home.resolve()
            or home.stat().st_uid != os.getuid()):
        raise MigrationError("Open the app normally in the Mac account you are moving. Do not use sudo or another user's home.")
    return account.pw_name


def _directory(path):
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077):
        raise MigrationError("Connection storage must be a private folder owned by this account. Contact support; no permissions were changed.")


def _read(path, public=False, limit=MAX_BYTES):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != os.getuid() or info.st_mode & (0o022 if public else 0o077)
                or info.st_size > limit):
            raise MigrationError("Unsafe connection file. Keep it intact and contact support.")
        data = handle.read(limit + 1)
        if len(data) > limit:
            raise MigrationError("Connection file is too large.")
        return data


def _write(path, data, expected=None):
    """Private atomic replacement; never blindly replace pre-existing state."""
    if path.exists() or path.is_symlink():
        before = _read(path, limit=1024 * 1024)
        if expected is None or before != expected:
            raise MigrationError("Connection file changed. Review it before retrying.")
    elif expected is not None:
        raise MigrationError("Connection file disappeared. Review it before retrying.")
    fd, temporary = tempfile.mkstemp(prefix=".connection-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if expected is not None and _read(path, limit=1024 * 1024) != expected:
            raise MigrationError("Connection file changed. Retry after other SSH setup tools have stopped.")
        if expected is None:
            # Hard-link publication fails if another writer created the name.
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def public_key(value):
    if not isinstance(value, str) or len(value) > 120:
        raise MigrationError("Invalid connection card key.")
    try:
        kind, encoded = value.split(" ")
        raw = base64.b64decode(encoded, validate=True)
        if (kind != "ssh-ed25519" or len(raw) != 51
                or raw[:19] != b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20"):
            raise ValueError()
    except (ValueError, TypeError):
        raise MigrationError("Invalid connection card key.") from None
    return value


def encode_card(payload):
    return PREFIX + base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True).encode()).decode()


def decode_card(card, kind, allow_expired=False):
    if not isinstance(card, str) or len(card) > MAX_BYTES or not card.strip().startswith(PREFIX):
        raise MigrationError("Paste the complete connection card from your other Mac.")
    try:
        value = json.loads(base64.b64decode(card.strip()[len(PREFIX):], altchars=b"-_", validate=True))
        keys = {"kind", "id", "expires", "key"}
        if kind == "accepted":
            keys |= {"target", "home", "host_key"}
        if (not isinstance(value, dict) or set(value) != keys or value["kind"] != kind
                or not isinstance(value["id"], str) or not re.fullmatch(r"[a-f0-9]{32}", value["id"])
                or type(value["expires"]) is not int
                or not (0 if allow_expired else time.time()) < value["expires"] <= time.time() + LIFETIME + 60):
            raise ValueError()
        public_key(value["key"])
        if kind == "accepted":
            public_key(value["host_key"])
            if (not isinstance(value["target"], str) or not TARGET_PATTERN.fullmatch(value["target"])
                    or not isinstance(value["home"], str) or not value["home"].startswith("/Users/")
                    or len(Path(value["home"]).parts) != 3 or any(x in value["home"] for x in ("\n", "\r", "\x00"))
                    or Path(value["home"]).name in (".", "..")):
                raise ValueError()
        return value
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise MigrationError("This connection card is invalid, expired, or for a different step. Copy a fresh card from the other Mac.") from None


class Pairing:
    def __init__(self, home, state_root):
        self.home = Path(home)
        self.root = Path(state_root) / "connection"

    def _prepare(self):
        user = _account(self.home)
        # The already-owned registry is the parent. Reject replacement by links.
        _directory(self.root.parent)
        self.root.mkdir(mode=0o700, exist_ok=True)
        _directory(self.root)
        return user

    def request(self):
        self._prepare()
        record = self.root / "request.json"
        if record.exists():
            request = decode_card(_read(record).decode(), "request")
            public = self._generated_public()
            if request["key"] != public:
                raise MigrationError("The connection key changed. Keep connection files intact and contact support.")
        else:
            key = self.root / "identity"
            if any(path.exists() or path.is_symlink() for path in (key, key.with_name("identity.pub"))):
                raise MigrationError("An unfinished connection key exists. Use Start a fresh connection to preserve it before trying again.")
            subprocess.run(["/usr/bin/ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "codex-migrate", "-f", str(key)],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15, check=True)
            request = {"kind": "request", "id": secrets.token_hex(16), "expires": int(time.time()) + LIFETIME,
                       "key": self._generated_public()}
            _write(record, encode_card(request).encode())
        return {"card": encode_card(request), "expires": request["expires"]}

    def _generated_public(self):
        # Validate the private file's metadata without opening or exporting it.
        info = (self.root / "identity").lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid()
                or info.st_mode & 0o077):
            raise MigrationError("Unsafe connection key. Contact support.")
        result = subprocess.run(["/usr/bin/ssh-keygen", "-y", "-P", "", "-f", str(self.root / "identity")],
                                env={"PATH": "/usr/bin:/bin", "SSH_ASKPASS_REQUIRE": "never"},
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10, check=True)
        return public_key(" ".join(result.stdout.decode().strip().split()[:2]))

    def _receiver_details(self):
        user = self._prepare()
        if self.home.parent != Path("/Users") or self.home.name != user:
            raise MigrationError("Guided pairing requires a standard /Users/username home. Use advanced setup for a custom home.")
        host = subprocess.run(["/usr/sbin/scutil", "--get", "LocalHostName"], capture_output=True, text=True, timeout=5, check=True).stdout.strip()
        target = user + "@" + host + ".local"
        if not TARGET_PATTERN.fullmatch(target):
            raise MigrationError("Check this Mac's Sharing name before pairing.")
        path = Path("/etc/ssh/ssh_host_ed25519_key.pub")
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 or info.st_size > 1024:
            raise MigrationError("Cannot verify this Mac's SSH identity. Contact support.")
        # This fixed, root-owned public file is not the private host key.
        host_key = public_key(" ".join(path.read_text().strip().split()[:2]))
        return {"target": target, "home": str(self.home), "host_key": host_key}

    def approve(self, card, apply=False):
        if apply is not True:
            raise MigrationError("Confirm connection access before approving this Mac.")
        request = decode_card(card, "request")
        details = self._receiver_details()
        accepted = dict(request, kind="accepted", **details)
        record = self.root / "approved.json"
        encoded = encode_card(accepted).encode()
        if record.exists():
            if _read(record) != encoded:
                raise MigrationError("Another connection is already approved. Remove its access before approving a different request.")
        else:
            # Record exact ownership before authorization, for crash-safe removal.
            _write(record, encoded)
        ssh = self.home / ".ssh"
        ssh.mkdir(mode=0o700, exist_ok=True)
        _directory(ssh)
        path = ssh / "authorized_keys"
        before = _read(path, limit=1024 * 1024) if path.exists() or path.is_symlink() else None
        expires = datetime.fromtimestamp(request["expires"], timezone.utc).strftime("%Y%m%d%H%M%SZ")
        line = ('restrict,expiry-time="%s" %s codex-migrate-%s\n' % (expires, request["key"], request["id"])).encode()
        # Never alter existing entries, including their options or comments.
        if line not in (before or b"").splitlines(keepends=True):
            contents = before or b""
            if contents and not contents.endswith(b"\n"):
                contents += b"\n"
            _write(path, contents + line, expected=before)
        return {"card": encode_card(accepted), "expires": request["expires"], "target": details["target"]}

    def revoke(self, apply=False):
        if apply is not True:
            raise MigrationError("Confirm removal of this connection's access.")
        self._prepare()
        record = self.root / "approved.json"
        approved = decode_card(_read(record).decode(), "accepted", allow_expired=True)
        _directory(self.home / ".ssh")
        path = self.home / ".ssh/authorized_keys"
        before = _read(path, limit=1024 * 1024)
        expires = datetime.fromtimestamp(approved["expires"], timezone.utc).strftime("%Y%m%d%H%M%SZ")
        owned = ('restrict,expiry-time="%s" %s codex-migrate-%s\n' % (expires, approved["key"], approved["id"])).encode()
        after = b"".join(line for line in before.splitlines(keepends=True) if line != owned)
        if after != before:
            _write(path, after, expected=before)
        os.replace(record, self.root / ("revoked-" + approved["id"] + ".json"))
        return {"message": "This connection's access was removed. Existing SSH entries were kept."}

    def restart(self, apply=False):
        if apply is not True:
            raise MigrationError("Confirm starting a new connection.")
        self._prepare()
        if (self.root / "approved.json").exists():
            raise MigrationError("Remove the approved connection's access on this Mac before starting over.")
        archived = self.root.with_name("connection-retired-" + secrets.token_hex(16))
        os.rename(self.root, archived)
        return {"message": "Previous connection files were preserved locally. Create a new card and approve it on the new Mac. Previous access there lasts until removed or expired."}

    def accept(self, card, apply=False):
        if apply is not True:
            raise MigrationError("Confirm the card came directly from your new Mac before trusting it.")
        self._prepare()
        accepted = decode_card(card, "accepted")
        request = decode_card(_read(self.root / "request.json").decode(), "request")
        if any(accepted[k] != request[k] for k in ("id", "key", "expires")) or request["key"] != self._generated_public():
            raise MigrationError("This reply does not match the connection request on this Mac.")
        alias = "codex-migrate-" + request["id"]
        known = (alias + " " + accepted["host_key"] + "\n").encode()
        path = self.root / "known_hosts"
        if path.exists():
            if _read(path) != known:
                raise MigrationError("The paired Mac's identity changed. No trust entry was replaced.")
        else:
            _write(path, known)
        record = self.root / "accepted.json"
        encoded = encode_card(accepted).encode()
        if record.exists():
            if _read(record) != encoded:
                raise MigrationError("A different Mac is already paired. No pairing was replaced.")
        else:
            _write(record, encoded)
        return {"target": accepted["target"], "target_home": accepted["home"]}

    def options(self, target, target_home):
        self._prepare()
        accepted = decode_card(_read(self.root / "accepted.json").decode(), "accepted")
        if accepted["target"] != target or accepted["home"] != target_home:
            raise MigrationError("The destination differs from your paired Mac. Recheck the connection card.")
        alias = "codex-migrate-" + accepted["id"]
        if (_read(self.root / "known_hosts") != (alias + " " + accepted["host_key"] + "\n").encode()
                or accepted["key"] != self._generated_public()):
            raise MigrationError("Connection files changed. No connection was started.")
        return SSHOptions(identity_file=str(self.root / "identity"), known_hosts_file=str(self.root / "known_hosts"), host_key_alias=alias, isolated=True)
