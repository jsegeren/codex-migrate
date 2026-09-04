"""Frozen whole-tree checks using one streaming system-Perl process per root."""
import os
from pathlib import Path
import re
import shlex
import subprocess
import time

from codex_migrate.errors import MigrationError
from codex_migrate.transport import _stop_process


PERL_COMMAND = ["/usr/bin/env", "-u", "PERL5OPT", "-u", "PERL5LIB", "-u", "PERLLIB",
                "-u", "PERLIO", "-u", "PERL_UNICODE", "LC_ALL=C", "/usr/bin/perl"]
PERL_IMPORTS = "use strict; use warnings; use bytes; use Digest::SHA; use Time::HiRes (); use Fcntl qw(:DEFAULT :mode);"
PERL_PROBE = PERL_IMPORTS + "my $flags = O_NOFOLLOW | O_NONBLOCK; die unless length(Digest::SHA::sha256_hex('')) == 64;"
WORKSPACE_TIMEOUT = 24 * 60 * 60

# Names/link text are filesystem bytes, never decoded as Unicode. Each tree
# node is domain-separated and length-framed; child names are sorted as bytes.
# Hashes do not include absolute roots, owners, timestamps, ACLs or xattrs.
TREE_PROGRAM = PERL_IMPORTS + r'''
sub information {
    my ($path) = @_;
    my @s = Time::HiRes::lstat($path);
    die unless @s;
    return \@s;
}
sub stable {
    my ($a, $b) = @_;
    die unless @$b;
    for my $index (0, 1, 2, 3, 7, 9, 10) { die unless $a->[$index] == $b->[$index]; }
}
sub field {
    my ($sha, $value) = @_;
    $sha->add(pack('N', length($value)), $value);
}
sub tree {
    my ($path) = @_;
    my $before = information($path);
    my $sha = Digest::SHA->new(256);
    field($sha, 'codex-migrate-tree-v1');
    if (S_ISLNK($before->[2])) {
        my $value = readlink($path);
        die unless defined $value;
        field($sha, 'link'); field($sha, $value);
        die unless readlink($path) eq $value;
    } elsif (S_ISDIR($before->[2])) {
        field($sha, 'directory'); field($sha, sprintf('%04o', $before->[2] & 07777));
        opendir(my $directory, $path) or die;
        $! = 0;
        my @names = sort grep { $_ ne '.' && $_ ne '..' } readdir($directory);
        die if $!;
        closedir($directory) or die;
        for my $name (@names) { field($sha, $name); field($sha, tree($path . '/' . $name)); }
    } elsif (S_ISREG($before->[2])) {
        sysopen(my $file, $path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK) or die;
        binmode($file) or die;
        my @opened = Time::HiRes::stat($file);
        stable($before, \@opened);
        die unless S_ISREG($opened[2]);
        my $content = Digest::SHA->new(256);
        my $total = 0;
        while (1) {
            my $read = sysread($file, my $buffer, 1048576);
            die unless defined $read;
            last unless $read;
            $content->add($buffer); $total += $read;
        }
        my @after = Time::HiRes::stat($file);
        stable($before, \@after);
        die unless $total == $before->[7];
        close($file) or die;
        field($sha, 'file'); field($sha, sprintf('%04o', $before->[2] & 07777));
        field($sha, $content->digest);
    } else { die; }
    stable($before, information($path));
    return $sha->digest;
}
my $digest;
my $ok = eval {
    local $SIG{__WARN__} = sub { die; };
    die unless @ARGV == 1 && S_ISDIR(information($ARGV[0])->[2]);
    $digest = unpack('H*', tree($ARGV[0]));
    1;
};
if (!$ok) { print STDERR "Workspace tree could not be verified. Close writing apps and review unreadable or special files.\n"; exit 74; }
print $digest, "\n" or exit 74;
'''


def check_local_tools():
    try:
        subprocess.run(PERL_COMMAND + ["-e", PERL_PROBE], check=True, capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as error:
        raise MigrationError("Workspace verification requires system Perl with Digest::SHA, Time::HiRes and no-follow file support") from error


def remote_tool_check():
    command = " ".join(shlex.quote(arg) for arg in PERL_COMMAND + ["-e", PERL_PROBE])
    return command + " >/dev/null 2>&1 || { echo 'Destination workspace-verification tools are unavailable.' >&2; exit 74; }\n"


def freeze_tree(root: str, checkpoint=lambda: None):
    checkpoint()
    path = Path(root)
    if path.is_symlink() or not path.is_dir():
        raise MigrationError("Workspace verification requires a real source directory")
    process = subprocess.Popen(PERL_COMMAND + ["-e", TREE_PROGRAM, os.fspath(path)],
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
        if process.returncode or not re.fullmatch(r"[0-9a-f]{64}\n", output):
            raise MigrationError("Source workspace verification failed. Close writing apps and review unreadable or special files; staging was kept.")
        return output.strip()
    except BaseException:
        _stop_process(process)
        raise


def remote_tree_function():
    command = " ".join(shlex.quote(arg) for arg in PERL_COMMAND + ["-e", TREE_PROGRAM])
    return "workspace_tree_digest() {\n" + command + ' "$1"\n}\n'


def tree_check(root, digest):
    quoted = shlex.quote(root)
    if digest is None:
        return "test ! -e %s && test ! -L %s" % (quoted, quoted)
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise MigrationError("Invalid frozen workspace verification snapshot")
    # Assignment failure must return explicitly, not be hidden by command
    # substitution or zsh's ERR_EXIT/outer rollback-trap interaction.
    return ('workspace_digest=$(workspace_tree_digest %s) || return 74\n'
            'test "$workspace_digest" = %s') % (quoted, shlex.quote(digest))
