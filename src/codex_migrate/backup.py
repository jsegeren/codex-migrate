"""Shared fail-closed backup checks. Remote output never includes file contents."""

import json
from datetime import datetime, timezone
from pathlib import Path
import secrets
import shlex
from typing import Sequence, Tuple

from codex_migrate.backup_sockets import CODEX_BACKUP_RUNNER


MIN_RESERVE_BYTES = 2 * 1024**3


def new_backup_path(home: str, prefix: str) -> str:
    """Name a fresh attempt without reusing backups after fast/clock-skew retries.

    The destination's existing-path check and lock still enforce non-overwrite.
    Timestamp is for people; the random suffix distinguishes attempts.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return str(Path(home) / (prefix + "-" + timestamp + "-" + secrets.token_hex(8)))


# A conservative full-copy budget is required even though APFS clones normally
# consume much less space. Pipe failures must not silently turn into zero bytes.
BACKUP_FUNCTIONS = r'''
set -o pipefail
backup_size() {
  local item size total=0 parent
  for item in "$@"; do
    parent=${item:h}
    while test "$parent" != /; do
      test ! -L "$parent" || { echo 'Backup path has a symbolic-link parent.' >&2; return 71; }
      parent=${parent:h}
    done
    if test -e "$item" || test -L "$item"; then
      size=$(/usr/bin/du -sk "$item" 2>/dev/null | /usr/bin/awk '{print $1}') || {
        echo 'Cannot measure destination backup; installation blocked.' >&2; return 71;
      }
      case "$size" in ''|*[!0-9]*) return 71;; esac
      total=$((total + size * 1024))
    fi
  done
  printf '%s\n' "$total"
}
backup_space() {
  local available required=$2
  available=$(/bin/df -Pk "$1" | /usr/bin/tail -1 | /usr/bin/awk '{print $4}') || return 71
  case "$available" in ''|*[!0-9]*) return 71;; esac
  available=$((available * 1024))
  if test "$available" -lt "$required"; then
    printf 'Not enough destination space for a safe backup: need %s bytes free, found %s. Installation blocked; free space and retry. No backup bypass is available.\n' "$required" "$available" >&2
    return 72
  fi
}
verify_backup() {
  local changes
  if test -L "$1"; then
    test -L "$2" && test "$(readlink "$1")" = "$(readlink "$2")" || return 73
  elif test -d "$1"; then
    test -d "$2" && test ! -L "$2" || return 73
    # Dry-run only: --delete detects unexpected backup entries, never deletes.
    # Compare special-node types too. Without --specials rsync reports cloned
    # FIFOs as skipped even when cp preserved them, falsely rejecting a backup.
    # Socket nodes omitted by cp must still fail the missing-entry check.
    # No socket is connected and no FIFO content is read; this stays dry-run.
    # Checksums, tree structure and link targets; no filenames/hashes are logged.
    changes=$(/usr/bin/rsync -rlnc --specials --delete --out-format='%i' "$1/" "$2/" 2>/dev/null) || {
      echo 'Backup verification could not complete. Installation blocked.' >&2; return 73;
    }
    test -z "$changes" || {
      echo 'Backup verification found differences. Installation blocked.' >&2; return 73;
    }
  else
    echo 'Unsupported backup item. Installation blocked.' >&2
    return 73
  fi
}
'''

# Only the full migration's destination .codex backup uses this comparison.
# Workspaces and skills retain verify_backup without runtime exclusions.
BACKUP_FUNCTIONS += "\nverify_codex_backup() {\n  " + (
    "/usr/bin/env -u PERL5OPT -u PERL5LIB -u PERLLIB -u PERLIO -u PERL_UNICODE "
    "LC_ALL=C /usr/bin/perl -e " + shlex.quote(CODEX_BACKUP_RUNNER)
    + ' -- "$1" "$2" 2>/dev/null || {\n'
    + "    echo 'Backup verification found differences or could not complete. Installation blocked.' >&2; return 73;\n"
    + "  }\n}\n"
)


def size_command(paths: Sequence[str]) -> str:
    return "backup_size " + " ".join(shlex.quote(path) for path in paths)


def verification_receipt(backup: str, mappings: Sequence[Tuple[str, str]]) -> str:
    """Written only after every backup passes, before any destructive install."""
    payload = json.dumps({
        "backup_verified": True,
        "verification": "file checksums, tree structure and symbolic-link targets",
        "scope": [{"original": a, "backup": b} for a, b in mappings],
        "limitations": "Same-disk rollback copy; not protection against disk failure. "
        "Not a point-in-time snapshot: close all apps writing selected files. "
        "Recognized destination Codex runtime sockets are not restorable data and "
        "are omitted; ordinary files and the saved recovery backup remain checked. "
        "Extended attributes, ACLs and hard-link topology are not independently verified.",
        "recovery": "Keep writing apps closed. Preserve current destination files by moving "
        "them aside, then restore each existing backup to its original path. Missing "
        "backup items require review, not automatic deletion of current files. Never delete "
        "the old Mac source or this backup until recovery is confirmed.",
    }, indent=2)
    return "printf '%%s\\n' %s > %s\n" % (
        shlex.quote(payload), shlex.quote(backup + "/verification.json"),
    )
