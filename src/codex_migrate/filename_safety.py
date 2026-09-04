"""Conservative sibling-name screening; never rename or open file contents."""

import fnmatch
import os
from pathlib import Path
import unicodedata

from codex_migrate.errors import MigrationError
from codex_migrate.exclusions import CODEX_EXCLUDES


MESSAGE = ("Source filenames may collide on the new Mac or cannot be checked safely. "
           "Keep the original files and staging; contact support before renaming anything.")


def check_name(name, seen):
    try:
        name.encode("utf-8", "strict")
    except UnicodeError as error:
        raise MigrationError(MESSAGE) from error
    key = unicodedata.normalize("NFD", unicodedata.normalize("NFD", name).casefold())
    if key in seen:
        raise MigrationError(MESSAGE)
    seen.add(key)


def check_names(names):
    seen = set()
    for name in names:
        check_name(name, seen)


def check_tree_names(root, checkpoint=lambda: None, *, codex=False):
    """Inspect names only, without following directory links or excluded trees.

    All siblings are screened even when one is excluded from the transfer.
    This deliberately errs on the side of review for ambiguous source layouts.
    """
    root = Path(root)
    stack = [root]
    try:
        while stack:
            checkpoint()
            current = stack.pop()
            if current.is_symlink():
                raise MigrationError(MESSAGE)
            seen = set()
            with os.scandir(current) as entries:
                for entry in entries:
                    checkpoint()
                    check_name(entry.name, seen)
                    directory = entry.is_dir(follow_symlinks=False)
                    if not directory:
                        continue
                    relative = Path(entry.path).relative_to(root).as_posix()
                    if codex and any(
                        fnmatch.fnmatchcase(relative, pattern.strip("/"))
                        for pattern in CODEX_EXCLUDES
                        if relative.count("/") == pattern.strip("/").count("/")
                    ):
                        continue
                    stack.append(Path(entry.path))
    except InterruptedError:
        raise
    except OSError as error:
        raise MigrationError(MESSAGE) from error


# Keep digest bytes unchanged: Unicode is used only for the collision key.
# This is conservative screening, not an emulation of any APFS Unicode table.
PERL_NAME_CHECK = r'''
use Encode ();
use Unicode::Normalize ();
use feature 'fc';
sub validate_names {
    my %seen;
    for my $raw (@_) {
        my $name = eval { Encode::decode('UTF-8', $raw, Encode::FB_CROAK | Encode::LEAVE_SRC) };
        if ($@) { die "CM_FILENAME_SAFETY\n"; }
        my $key = Unicode::Normalize::NFD(fc(Unicode::Normalize::NFD($name)));
        die "CM_FILENAME_SAFETY\n" if $seen{$key}++;
    }
}
'''
