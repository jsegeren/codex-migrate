"""Enumerate Codex-owned attachments without following source links.

Large pasted prompts can live only in this directory, with a JSONL rollout
containing a path rather than the prompt body. A transcript-only snapshot is
therefore not a complete conversation backup.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import stat
from typing import Iterator, List, Optional, Tuple

from codex_migrate.errors import MigrationError
from codex_migrate.source_availability import check_info, require_local


MAX_ATTACHMENT_FILES = 100_000
MAX_PASTED_TEXT_BYTES = 128 * 1024 * 1024
_PASTED_PATH = re.compile(
    r"\.codex/attachments/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12})/pasted-text\.txt\b", re.IGNORECASE)


def attachment_files(source_home: str) -> List[Tuple[str, Path, str]]:
    """Return regular files under ``.codex/attachments`` for encrypted capture.

    The registry is included: it may be needed to interpret an attachment on
    another Mac. No source file is changed and no file content is read here.
    """
    root = Path(source_home) / ".codex" / "attachments"
    try:
        info = check_info(root.lstat())
    except FileNotFoundError:
        return []
    except OSError as error:
        raise MigrationError("Codex attachments could not be inspected safely.") from error
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise MigrationError("The Codex attachments folder needs review before backup.")

    files: List[Tuple[str, Path, str]] = []

    def failed(error: OSError) -> None:
        raise MigrationError("Codex attachments could not be inspected safely.") from error

    try:
        for current, directories, names in os.walk(root, followlinks=False,
                                                    onerror=failed):
            folder = Path(current)
            folder_info = require_local(folder)
            if (not stat.S_ISDIR(folder_info.st_mode) or
                    folder_info.st_uid != os.getuid()):
                raise MigrationError("A Codex attachment folder needs review before backup.")
            directories.sort()
            names.sort()
            for name in directories:
                child = require_local(folder / name)
                if (not stat.S_ISDIR(child.st_mode) or
                        child.st_uid != os.getuid()):
                    raise MigrationError("A linked Codex attachment folder needs review.")
            for name in names:
                path = folder / name
                entry = require_local(path)
                if (not stat.S_ISREG(entry.st_mode) or entry.st_uid != os.getuid()
                        or entry.st_nlink != 1):
                    raise MigrationError("A Codex attachment file needs review before backup.")
                relative = path.relative_to(root).as_posix()
                if len(relative) > 4096 or "\\" in relative:
                    raise MigrationError("A Codex attachment path is too long or unsafe.")
                files.append(("attachments", path, relative))
                if len(files) > MAX_ATTACHMENT_FILES:
                    raise MigrationError("There are too many Codex attachments for one snapshot.")
    except OSError as error:
        raise MigrationError("Codex attachments could not be inspected safely.") from error
    return files


def pasted_references(text: str) -> Iterator[str]:
    """Resolve only Codex's fixed pasted-text attachment shape, never a path.

    The transcript may name an old Mac's absolute home. The UUID is the only
    value used to locate this snapshot's separately restored attachment.
    """
    if not isinstance(text, str):
        return
    for match in _PASTED_PATH.finditer(text.replace("\\/", "/")):
        yield match.group(1).lower()


def read_pasted_text(source_home: str, attachment_id: str) -> Optional[str]:
    """Read one local/restored pasted prompt without following source links."""
    if (not isinstance(attachment_id, str) or
            not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}",
                             attachment_id)):
        raise MigrationError("A pasted attachment identity is invalid.")
    root = Path(source_home) / ".codex" / "attachments"
    opened = []
    try:
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        for name in (str(root), attachment_id):
            try:
                descriptor = (os.open(name, flags | os.O_DIRECTORY) if not opened
                              else os.open(name, flags | os.O_DIRECTORY,
                                           dir_fd=opened[-1]))
            except FileNotFoundError:
                return None
            opened.append(descriptor)
            info = check_info(os.fstat(descriptor))
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                raise MigrationError("A pasted attachment folder is unsafe.")
        try:
            descriptor = os.open("pasted-text.txt", flags, dir_fd=opened[-1])
        except FileNotFoundError:
            return None
        opened.append(descriptor)
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            before = os.fstat(stream.fileno())
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or
                    before.st_nlink != 1 or before.st_size > MAX_PASTED_TEXT_BYTES):
                raise MigrationError("A pasted attachment is unsafe or too large to browse.")
            raw = stream.read(MAX_PASTED_TEXT_BYTES + 1)
            after = os.fstat(stream.fileno())
            if (len(raw) != before.st_size or
                    (before.st_dev, before.st_ino, before.st_size,
                     before.st_mtime_ns, before.st_ctime_ns) !=
                    (after.st_dev, after.st_ino, after.st_size,
                     after.st_mtime_ns, after.st_ctime_ns)):
                raise MigrationError("A pasted attachment changed while it was read.")
    except OSError as error:
        raise MigrationError("A pasted attachment could not be opened or read safely.") from error
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)
    try:
        return raw.decode("utf-8")
    except UnicodeError as error:
        raise MigrationError("A pasted attachment is not readable text.") from error
