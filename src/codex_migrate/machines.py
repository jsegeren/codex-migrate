"""Reject self-migration independently of hostnames, addresses and usernames."""

import hashlib
import plistlib
import re
import secrets
import subprocess
from xml.parsers.expat import ExpatError

from codex_migrate.errors import MigrationError


UUID_PATTERN = r"[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}"
IOREG_COMMAND = ["/usr/sbin/ioreg", "-a", "-r", "-d", "1", "-c", "IOPlatformExpertDevice"]


def local_machine_uuid():
    try:
        result = subprocess.run(IOREG_COMMAND, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=10, check=True)
        records = plistlib.loads(result.stdout)
        if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
            raise ValueError("unexpected platform record")
        value = records[0].get("IOPlatformUUID")
        if not isinstance(value, str):
            raise ValueError("missing platform identity")
        value = value.upper()
        if not re.fullmatch(UUID_PATTERN, value) or value.replace("-", "") in ("0" * 32, "F" * 32):
            raise ValueError("invalid platform identity")
        return value
    except (OSError, ValueError, TypeError, ExpatError, subprocess.SubprocessError) as error:
        raise MigrationError("Cannot verify the source Mac's machine identity. "
                             "No destination command was started; contact support.") from error


def machine_comparison():
    # Use a fresh salt so command arguments do not contain a stable hardware ID.
    # Neither the UUID nor this ephemeral comparison is saved in migration state.
    source = local_machine_uuid()
    salt = secrets.token_hex(16)
    expected = hashlib.sha256((salt + ":" + source).encode("ascii")).hexdigest()
    return salt, expected


def destination_guard(comparison=None):
    salt, expected = comparison if comparison is not None else machine_comparison()
    if not isinstance(salt, str) or not re.fullmatch(r"[0-9a-f]{32}", salt) or not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise MigrationError("Invalid machine comparison; no connection was started")
    return """(
set -o pipefail
if ! cm_machine_uuid=$(/usr/sbin/ioreg -a -r -d 1 -c IOPlatformExpertDevice 2>/dev/null | /usr/bin/plutil -extract 0.IOPlatformUUID raw -o - - 2>/dev/null); then
  echo 'Cannot verify destination machine identity. No migration command was started; contact support.' >&2
  exit 76
fi
cm_machine_uuid=${(U)cm_machine_uuid}
if [[ ${#cm_machine_uuid} -ne 36 || ! $cm_machine_uuid =~ '^[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}$' || ${cm_machine_uuid//-/} == 00000000000000000000000000000000 || ${cm_machine_uuid//-/} == FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF ]]; then
  echo 'Cannot verify destination machine identity. No migration command was started; contact support.' >&2
  exit 76
fi
if ! cm_machine_digest=$(/usr/bin/printf '%s' 'SALT:'"$cm_machine_uuid" | /usr/bin/shasum -a 256 | /usr/bin/awk '{print $1}'); then
  echo 'Cannot compare machine identities. No migration command was started; contact support.' >&2
  exit 76
fi
if [[ $cm_machine_digest == 'EXPECTED' ]]; then
  echo 'The destination is this source Mac. Choose the other Mac; no migration command was started.' >&2
  exit 76
fi
if [[ ${#cm_machine_digest} -ne 64 || ! $cm_machine_digest =~ '^[0-9a-f]{64}$' ]]; then
  echo 'Cannot compare machine identities. No migration command was started; contact support.' >&2
  exit 76
fi
) || exit 76
""".replace("SALT", salt).replace("EXPECTED", expected)
