"""Owner-only local history lock shared by Vault backup and installation."""

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import stat
from typing import Iterator

from codex_migrate.errors import MigrationError


LOCK_NAME = ".codex-vault-history.lock"


@contextmanager
def local_history_lock(source_home: str) -> Iterator[None]:
    home = Path(source_home).expanduser()
    if not home.is_absolute():
        raise ValueError("source home must be absolute")
    try:
        info = home.lstat()
    except OSError as error:
        raise MigrationError("The local account home could not be inspected safely.") from error
    if (stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid() or os.getuid() == 0):
        raise MigrationError("Vault history work requires the signed-in non-root Mac account.")
    path = home / LOCK_NAME
    try:
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except OSError as error:
        raise MigrationError("The local Vault history lock could not be opened safely.") from error
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077):
            raise MigrationError("The local Vault history lock has unsafe permissions.")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise MigrationError("Another local Vault history operation is already running.") from error
        yield
    finally:
        os.close(descriptor)
