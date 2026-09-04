"""Metadata-only screening for macOS dataless source files.

This never downloads files. Providers without SF_DATALESS and eviction races
still require real-provider acceptance; this is not a snapshot or pin operation.
"""

import os
from pathlib import Path

from codex_migrate.errors import MigrationError


# Darwin sys/stat.h: SF_DATALESS. Do not infer availability from allocated
# blocks: ordinary sparse files are valid and must remain migratable.
SF_DATALESS = 0x40000000
MESSAGE = ("Some selected files are not downloaded locally. Download and keep "
           "them on this Mac using their cloud provider, then inspect again. "
           "Original files and staging were kept.")


def check_info(info):
    if getattr(info, "st_flags", 0) & SF_DATALESS:
        raise MigrationError(MESSAGE)
    return info


def require_local(path):
    """Check the entry itself, not the target of an ordinary preserved link."""
    try:
        return check_info(Path(path).lstat())
    except OSError:
        raise MigrationError("Selected file availability could not be checked. "
                             "Keep the files intact and inspect again.") from None


def walk_local(root, *, followlinks=False, onerror=None):
    """Top-down os.walk with directory checks before each enumeration.

    Consumers may prune directories in place, just as with os.walk. Skipped
    directories and directory-link targets are not checked or traversed.
    """
    require_local(root)
    for current, directories, files in os.walk(root, followlinks=followlinks, onerror=onerror):
        yield current, directories, files
        for name in directories:
            candidate = Path(current) / name
            if followlinks or not candidate.is_symlink():
                require_local(candidate)
