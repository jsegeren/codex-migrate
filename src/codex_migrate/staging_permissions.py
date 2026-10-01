"""Bounded, destination-owned preparation for the macOS rsync metadata pass.

This is an internal staging primitive, not a source or live-data repair. The
caller must restore source modes and verify staging before installing it.
"""

from pathlib import Path
import re
import shlex

from codex_migrate.destination_lock import locked_destination_script
from codex_migrate.errors import MigrationError
from codex_migrate.workspaces import PERL_COMMAND


STAGING_TIMEOUT = 30 * 60

# Walk relative to open directory descriptors. No absolute child path is opened
# or chmodded. A validation pass precedes the optional filehandle-fchmod pass;
# the latter repeats all checks because a tree can change between passes.
# Private staging and the destination flock exclude cooperating migrations,
# not hostile writers running under the same macOS account.
STAGING_PROGRAM = r'''
use strict;
use warnings;
use Fcntl qw(:DEFAULT :mode F_GETFD F_SETFD);
use Errno qw(ENOENT);
sub invalid { die "CM_STAGING_UNSAFE\n"; }
sub matching {
    my ($a, $b) = @_;
    @$a && @$b or invalid();
    for my $i (0, 1, 2, 3, 4) { $a->[$i] == $b->[$i] or invalid(); }
}
sub directory {
    my ($name, $owned) = @_;
    my @before = lstat($name);
    @before && S_ISDIR($before[2]) or invalid();
    !$owned || $before[4] == $< or invalid();
    sysopen(my $dir, $name, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_NONBLOCK) or invalid();
    my @opened = stat($dir);
    matching(\@before, \@opened);
    chdir($dir) or invalid();
    return $dir;
}
sub enter_path {
    my ($absolute, $owned_below) = @_;
    $absolute =~ m{\A/} && $absolute ne '/' && $absolute !~ /[\r\n\0]/ or invalid();
    my @parts = split m{/}, $absolute;
    shift @parts;
    !grep { $_ eq '' || $_ eq '.' || $_ eq '..' } @parts or invalid();
    my $dir = directory('/', 0);
    my $current = '';
    for my $part (@parts) {
        $current .= '/' . $part;
        my $owned = $current eq $owned_below || index($current, $owned_below . '/') == 0;
        $dir = directory($part, $owned);
    }
    return $dir;
}
sub marker {
    my ($expected) = @_;
    my $name = '.codex-migrate-owner';
    my @before = lstat($name);
    @before && S_ISREG($before[2]) && $before[3] == 1 &&
        $before[4] == $< && ($before[2] & 07777) == 0600 && $before[7] == 33 or invalid();
    sysopen(my $file, $name, O_RDONLY | O_NOFOLLOW | O_NONBLOCK) or invalid();
    my @opened = stat($file);
    matching(\@before, \@opened);
    my $read = sysread($file, my $value, 34);
    defined($read) && $read == 33 && $value eq $expected . "\n" or invalid();
    my @after = stat($file);
    matching(\@before, \@after);
    close($file) or invalid();
}
my $nodes;
sub make_writable {
    my ($held, $pending) = @_;
    return unless @$pending;
    chdir($held) or invalid();
    my @arguments;
    for my $entry (@$pending) {
        my ($file, $before, $name) = @$entry;
        my @opened = stat($file);
        my @named = lstat($name);
        matching($before, \@opened);
        matching($before, \@named);
        my $flags = fcntl($file, F_GETFD, 0);
        defined($flags) && defined(fcntl($file, F_SETFD, 0)) or invalid();
        push @$entry, $flags;
        push @arguments, '/dev/fd/' . fileno($file);
    }
    # Existing deny-write ACLs otherwise make a successful first copy fail on
    # Finalize/Resume. Clear only ACLs of these pinned staging inodes; rsync -E
    # reapplies the source ACLs. The macOS descriptor filesystem keeps renamed
    # files pinned. Batch at most 32 descriptors, never an unbounded argv/fleet.
    my $status;
    {
        local *STDOUT; local *STDERR;
        open(STDOUT, '>', '/dev/null') && open(STDERR, '>', '/dev/null') or invalid();
        $status = system('/bin/chmod', '-N', @arguments);
    }
    $status == 0 or invalid();
    for my $entry (@$pending) {
        my ($file, $before, $name, $flags) = @$entry;
        defined(fcntl($file, F_SETFD, $flags)) or invalid();
        my @opened = stat($file);
        my @named = lstat($name);
        matching($before, \@opened);
        matching($before, \@named);
        my $mode = ($opened[2] & 07777) | S_IWUSR;
        chmod($mode, $file) == 1 or invalid();
        my @after = stat($file);
        @after && S_ISREG($after[2]) && $after[0] == $opened[0] &&
            $after[1] == $opened[1] && $after[3] == 1 && $after[4] == $< &&
            ($after[2] & 07777) == $mode or invalid();
        @named = lstat($name);
        matching(\@after, \@named);
        close($file) or invalid();
    }
    @$pending = ();
}
sub walk {
    my ($held, $depth, $bytes, $writable) = @_;
    $depth <= 128 && $bytes <= 4096 or invalid();
    chdir($held) or invalid();
    opendir(my $entries, '.') or invalid();
    my @pending;
    while (1) {
        $! = 0;
        my $name = readdir($entries);
        if (!defined($name)) { !$! or invalid(); last; }
        next if $name eq '.' || $name eq '..';
        ++$nodes <= 2000000 or invalid();
        length($name) && $name !~ m{/|\0} && $bytes + 1 + length($name) <= 4096 or invalid();
        my @before = lstat($name);
        @before or invalid();
        if (S_ISLNK($before[2])) {
            next; # Never resolve, enter, open, or change a link.
        }
        $before[4] == $< or invalid();
        if (S_ISDIR($before[2])) {
            make_writable($held, \@pending) if $writable;
            my $child = directory($name, 1);
            walk($child, $depth + 1, $bytes + 1 + length($name), $writable);
            chdir($held) or invalid();
            my @after = lstat($name);
            matching(\@before, \@after);
            close($child) or invalid();
        } elsif (S_ISREG($before[2])) {
            $before[3] == 1 or invalid();
            sysopen(my $file, $name, O_RDONLY | O_NOFOLLOW | O_NONBLOCK) or invalid();
            my @opened = stat($file);
            matching(\@before, \@opened);
            if ($writable) {
                push @pending, [$file, \@opened, $name];
                make_writable($held, \@pending) if @pending >= 32;
            } else {
                my @after = lstat($name);
                matching(\@before, \@after);
                close($file) or invalid();
            }
        } else { invalid(); }
    }
    make_writable($held, \@pending) if $writable;
    closedir($entries) or invalid();
}
sub selected_root {
    my ($root, $parts, $allow_absent) = @_;
    chdir($root) or invalid();
    my $held = $root;
    for my $part (@$parts) {
        my @s = lstat($part);
        return undef if !@s && $! == ENOENT && $allow_absent;
        @s or invalid();
        $held = directory($part, 1);
    }
    return $held;
}
my $ok = eval {
    local $SIG{__WARN__} = sub { invalid(); };
    local $SIG{ALRM} = sub { invalid(); };
    alarm(1800);
    @ARGV == 5 && $< != 0 && $< == $> or invalid();
    my ($home, $staging, $selected, $id, $action) = @ARGV;
    $id =~ /\A[0-9a-f]{32}\z/ &&
        ($action eq 'validate' || $action eq 'present' || $action eq 'writable') or invalid();
    index($staging, $home . '/') == 0 && index($selected, $staging . '/') == 0 or invalid();
    my $root = enter_path($staging, $home);
    my @root_info = stat($root);
    ($root_info[2] & 07777) == 0700 or invalid();
    marker($id);
    my $relative = substr($selected, length($staging) + 1);
    my @parts = split m{/}, $relative;
    @parts && !grep { $_ eq '' || $_ eq '.' || $_ eq '..' || /[\r\n\0]/ } @parts or invalid();
    my $held = selected_root($root, \@parts, $action eq 'validate');
    my @selected_info = defined($held) ? stat($held) : ();
    my $recheck = sub {
        my $named_root = enter_path($staging, $home);
        my @named_root_info = stat($named_root);
        matching(\@root_info, \@named_root_info);
        marker($id);
        my $named = selected_root($named_root, \@parts, $action eq 'validate');
        if (@selected_info) {
            defined($named) or invalid();
            my @named_info = stat($named);
            matching(\@selected_info, \@named_info);
        } else { !defined($named) or invalid(); }
    };
    if (defined($held)) {
        $nodes = 0;
        walk($held, 0, length($selected), 0);
        $recheck->();
        if ($action eq 'writable') {
            $nodes = 0;
            walk($held, 0, length($selected), 1);
            $recheck->();
        }
    }
    $recheck->();
    alarm(0);
    1;
};
unless ($ok) {
    print STDERR "Staging could not be prepared safely. Keep staging and backups intact; contact support before retrying.\n";
    exit 74;
}
'''


def staging_permissions_script(home, staging, selected, migration_id, *, writable=False,
                               allow_absent=True):
    """Validate, or temporarily add owner-write only to owned staging files.

    A failed or interrupted writable pass may leave staging partly writable.
    Callers must not mark it complete and must rerun every transfer phase.
    """
    paths = (home, staging, selected)
    for value in paths:
        if (not isinstance(value, str) or not value.startswith('/') or value == '/'
                or len(value.encode()) > 4096 or any(c in value for c in '\r\n\0')
                or any(part in ('', '.', '..') for part in value.split('/')[1:])):
            raise ValueError('Invalid owned staging path')
    if (Path(home) not in Path(staging).parents
            or Path(staging) not in Path(selected).parents
            or not isinstance(migration_id, str)
            or not re.fullmatch(r'[0-9a-f]{32}', migration_id)
            or type(writable) is not bool or type(allow_absent) is not bool):
        raise ValueError('Invalid owned staging scope')
    action = 'writable' if writable else 'validate' if allow_absent else 'present'
    args = [*PERL_COMMAND, '-e', STAGING_PROGRAM, '--', *paths, migration_id, action]
    command = ' '.join(shlex.quote(arg) for arg in args) + '\n'
    return locked_destination_script(home, command)


def transfer_staged(transport, home, staging, selected, migration_id, source,
                    excludes=(), *, copy_links=False, on_output=None,
                    checkpoint=lambda: None, on_process=lambda process: None,
                    cancelled=lambda: False):
    """Run every staging phase on every retry; never fall back after failure.

    Each remote operation retains the normal destination lock and SSH guards.
    The caller owns final source/staged verification and completion publication.
    """
    def guard(writable=False, allow_absent=False):
        checkpoint()
        script = staging_permissions_script(home, staging, selected, migration_id,
                                            writable=writable, allow_absent=allow_absent)
        transport.run_remote_cancellable(script, STAGING_TIMEOUT, cancelled)
        checkpoint()

    guard(allow_absent=True)
    for phase in ('data', 'metadata', 'modes'):
        if phase == 'metadata':
            guard(writable=True)
        checkpoint()
        process = transport.rsync_process(source, selected, excludes=excludes,
                                           copy_links=copy_links, phase=phase)
        on_process(process)
        try:
            checkpoint()
            if cancelled():
                raise MigrationError('Staging stopped')
            if on_output is None:
                process.start()
            else:
                process.start(on_output)
            checkpoint()
        finally:
            on_process(None)
    guard()
