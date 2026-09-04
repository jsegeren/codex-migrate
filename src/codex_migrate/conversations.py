"""Frozen transcript-byte verification without parsing or logging chat contents."""

import hashlib
import os
from pathlib import Path
import shlex
import stat

from codex_migrate.errors import MigrationError


def conversation_verification_script(source_codex: str) -> str:
    """Return a zsh function body to check the same snapshot twice.

    Only active/archived .jsonl transcripts are hashed, never login files. File
    names and hashes stay inside the private SSH script, not progress output.
    This verifies bytes and relative transcript paths, not application behavior.
    """
    root = Path(source_codex)
    checks = ["local conversation_count"]

    def unreadable(error):
        raise MigrationError("Cannot read the complete conversation tree") from error

    for folder in ("sessions", "archived_sessions"):
        source = root / folder
        target = '"$1"/' + folder
        if source.is_symlink():
            raise MigrationError("Conversation directories must not be symbolic links")
        if not source.exists():
            if folder == "sessions":
                raise MigrationError("The source conversations directory is missing")
            checks.extend(("test ! -e " + target, "test ! -L " + target))
            continue
        if not source.is_dir():
            raise MigrationError("Conversation storage must be a directory")
        count = 0
        for current, directories, files in os.walk(source, followlinks=False, onerror=unreadable):
            relative = Path(current).relative_to(root)
            directory = '"$1"/' + shlex.quote(str(relative))
            checks.extend(("test -d " + directory, "test ! -L " + directory))
            for name in directories + files:
                if (Path(current) / name).is_symlink():
                    raise MigrationError("Conversation trees contain symbolic links; review them before migrating")
            for name in sorted(files):
                if not name.endswith(".jsonl"):
                    continue
                path = Path(current) / name
                digest = hashlib.sha256()
                try:
                    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                    with os.fdopen(descriptor, "rb") as stream:
                        before = os.fstat(stream.fileno())
                        if not stat.S_ISREG(before.st_mode):
                            raise MigrationError("Conversation transcript is not a regular file")
                        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                            digest.update(chunk)
                        after = os.fstat(stream.fileno())
                    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                            after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                        raise MigrationError("A conversation changed during verification; close writing apps and retry")
                except OSError as error:
                    raise MigrationError("Cannot read a conversation transcript for verification") from error
                destination = '"$1"/' + shlex.quote(str(relative / name))
                checks.extend(("test -f " + destination, "test ! -L " + destination))
                # Hash stdin so shasum never prints (or escapes) a filename.
                checks.append("test \"$(/usr/bin/shasum -a 256 < %s | /usr/bin/awk '{print $1}')\" = %s"
                              % (destination, digest.hexdigest()))
                count += 1
        # NUL counts, not newline counts: valid filenames can contain newlines.
        counter = "/usr/bin/tr -cd '\\000' | /usr/bin/wc -c | /usr/bin/tr -d ' '"
        checks.append("conversation_count=$(/usr/bin/find %s -type f -name '*.jsonl' -print0 | %s)"
                      % (target, counter))
        checks.append('test "$conversation_count" = %d' % count)
        checks.append("conversation_count=$(/usr/bin/find %s -type l -print0 | %s)" % (target, counter))
        checks.append('test "$conversation_count" = 0')
        checks.append("conversation_count=$(/usr/bin/find %s -name '*.jsonl' ! -type f ! -type d -print0 | %s)"
                      % (target, counter))
        checks.append('test "$conversation_count" = 0')
    # zsh ERR_EXIT in a function can bypass the outer EXIT rollback trap.
    # Return to a top-level explicit exit instead.
    return "\n".join(check + " || return 74" for check in checks)
