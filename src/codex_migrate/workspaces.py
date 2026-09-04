"""Frozen whole-tree checks using one streaming system-Perl process per root."""
import os
from pathlib import Path
import re
import shlex
import subprocess
import time

from codex_migrate.errors import MigrationError
from codex_migrate.exclusions import CODEX_EXCLUDES
from codex_migrate.filename_safety import MESSAGE as FILENAME_MESSAGE, PERL_NAME_CHECK
from codex_migrate.transport import _stop_process
from codex_migrate.tree_digest import PERL_IMPORTS, TREE_FUNCTIONS


PERL_COMMAND = ["/usr/bin/env", "-u", "PERL5OPT", "-u", "PERL5LIB", "-u", "PERLLIB",
                "-u", "PERLIO", "-u", "PERL_UNICODE", "LC_ALL=C", "/usr/bin/perl"]
PERL_PROBE = PERL_IMPORTS + PERL_NAME_CHECK + "validate_names('fixture'); my $flags = O_NOFOLLOW | O_NONBLOCK; die unless length(Digest::SHA::sha256_hex('')) == 64;"
WORKSPACE_TIMEOUT = 24 * 60 * 60


def _codex_filter():
    # Compile only the deliberately small wildcard grammar our transfer uses.
    # Directory-only exclusions must not hide files or symlinks of that name.
    # Managed worktrees have their own complete-tree check, including absence.
    lines = ["sub excluded { my ($relative, $path) = @_; return 0 unless $codex_mode;",
             "die if (lc($relative) eq 'auth.json' && $relative ne 'auth.json') || (lc($relative) eq 'installation_id' && $relative ne 'installation_id');"]
    for pattern in (*CODEX_EXCLUDES, "/worktrees/"):
        if not re.fullmatch(r"/[A-Za-z0-9._*/-]+", pattern) or "**" in pattern:
            raise MigrationError("Unsupported Codex verification exclusion")
        expression = re.escape(pattern.strip("/")).replace(r"\*", "[^/]*")
        condition = "$relative =~ m{\\A" + expression + "\\z}"
        if pattern.endswith("/"):
            condition += " && S_ISDIR(information($path)->[2])"
        lines.append("return 1 if " + condition + ";")
    return "\n".join(lines) + "\nreturn 0; }\n"

# Digest names/link text remain filesystem bytes; only the collision check
# decodes names. Nodes are domain-separated and length-framed, sorted as bytes.
# Hashes do not include absolute roots, owners, timestamps, ACLs or xattrs.
TREE_PROGRAM = PERL_IMPORTS + PERL_NAME_CHECK + r'''
my $codex_mode = @ARGV == 2 && $ARGV[1] eq 'codex';
''' + _codex_filter() + TREE_FUNCTIONS + r'''
my $digest;
my $ok = eval {
    local $SIG{__WARN__} = sub { die; };
    die unless @ARGV == 2 && ($ARGV[1] eq 'workspace' || $ARGV[1] eq 'codex') && S_ISDIR(information($ARGV[0])->[2]);
    $digest = unpack('H*', tree($ARGV[0], ''));
    1;
};
if (!$ok) {
    if ($@ eq "CM_FILENAME_SAFETY\n") { print STDERR "Source filenames need review before migration.\n"; exit 75; }
    print STDERR "Workspace tree could not be verified. Close writing apps and review unreadable or special files.\n"; exit 74;
}
print $digest, "\n" or exit 74;
'''


def check_local_tools():
    try:
        subprocess.run(PERL_COMMAND + ["-e", PERL_PROBE], check=True, capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as error:
        raise MigrationError("Workspace verification requires system Perl with Digest::SHA, Time::HiRes, Encode, Unicode::Normalize and no-follow file support") from error


def remote_tool_check():
    command = " ".join(shlex.quote(arg) for arg in PERL_COMMAND + ["-e", PERL_PROBE])
    return command + " >/dev/null 2>&1 || { echo 'Destination workspace-verification tools are unavailable.' >&2; exit 74; }\n"


def validate_codex_identity_names(root):
    try:
        with os.scandir(root) as entries:
            for entry in entries:
                if entry.name.casefold() in ("auth.json", "installation_id") and entry.name not in ("auth.json", "installation_id"):
                    raise MigrationError("Codex identity filenames use noncanonical capitalization; resolve this before transfer")
    except OSError as error:
        raise MigrationError("Codex identity filenames could not be inspected safely") from error


def freeze_tree(root: str, checkpoint=lambda: None, *, codex=False):
    checkpoint()
    if codex:
        validate_codex_identity_names(root)
    path = Path(root)
    if path.is_symlink() or not path.is_dir():
        raise MigrationError("Workspace verification requires a real source directory")
    process = subprocess.Popen(PERL_COMMAND + ["-e", TREE_PROGRAM, os.fspath(path), "codex" if codex else "workspace"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True)
    deadline = time.monotonic() + WORKSPACE_TIMEOUT
    try:
        while True:
            checkpoint()
            if time.monotonic() > deadline:
                raise MigrationError("Source workspace verification timed out; staging was kept")
            try:
                output, _ = process.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                continue
        checkpoint()
        if process.returncode == 75:
            raise MigrationError(FILENAME_MESSAGE)
        if process.returncode or not re.fullmatch(r"[0-9a-f]{64}\n", output):
            raise MigrationError("Source workspace verification failed. Close writing apps and review unreadable or special files; staging was kept.")
        return output.strip()
    except BaseException:
        _stop_process(process)
        raise


def remote_tree_function(*, codex=False):
    command = " ".join(shlex.quote(arg) for arg in PERL_COMMAND + ["-e", TREE_PROGRAM])
    function = "codex_state_digest" if codex else "workspace_tree_digest"
    return function + "() {\n" + command + ' "$1" ' + ("codex" if codex else "workspace") + "\n}\n"


def tree_check(root, digest, *, codex=False):
    quoted = shlex.quote(root)
    if digest is None:
        return "test ! -e %s && test ! -L %s" % (quoted, quoted)
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise MigrationError("Invalid frozen workspace verification snapshot")
    # Assignment failure must return explicitly, not be hidden by command
    # substitution or zsh's ERR_EXIT/outer rollback-trap interaction.
    return ('workspace_digest=$(%s %s) || return 74\n'
            'test "$workspace_digest" = %s') % ("codex_state_digest" if codex else "workspace_tree_digest", quoted, shlex.quote(digest))
