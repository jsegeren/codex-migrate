"""Destination-owned exclusion for staging writes and protected installation."""

from pathlib import Path
import secrets
import shlex

from codex_migrate.transaction import PENDING_GUARD


LOCK_NAME = ".codex-migrate-destination.lock"

# Keep the inode permanently: unlinking a flock file creates a second lock
# domain while another process can still hold the first. Kernel ownership,
# not a PID, timestamp or source connection, determines whether it is held.
LOCK_RUNNER = r"""
use strict;
use warnings;
use Fcntl qw(:DEFAULT :flock :mode F_SETFD);
use Errno qw(EAGAIN EWOULDBLOCK);
sub invalid {
    print STDERR "Cannot safely lock the destination. No migration data was changed; contact support.\n";
    exit 75;
}
(@ARGV == 1 || @ARGV == 2) or invalid();
my $home = shift @ARGV;
$home =~ m{^/} && $home ne '/' && $home !~ /[\r\n\0]/ or invalid();
$< != 0 && $< == $> or invalid();
my $path = '';
for my $part (split m{/}, $home) {
    next if $part eq '';
    $part ne '.' && $part ne '..' or invalid();
    $path .= '/' . $part;
    my @s = lstat($path);
    @s && S_ISDIR($s[2]) or invalid();
}
my @home_stat = lstat($home);
@home_stat && $home_stat[4] == $< or invalid();
umask 0077;
my $name = $home . '/.codex-migrate-destination.lock';
sysopen(my $lock, $name, O_RDWR | O_CREAT | O_NOFOLLOW | O_NONBLOCK, 0600) or invalid();
my @s = stat($lock);
my @p = lstat($name);
@s && @p && S_ISREG($s[2]) && $s[3] == 1 && $s[4] == $< &&
    ($s[2] & 07777) == 0600 && $s[7] == 0 &&
    $s[0] == $p[0] && $s[1] == $p[1] or invalid();
unless (flock($lock, LOCK_EX | LOCK_NB)) {
    if ($! == EAGAIN || $! == EWOULDBLOCK) {
        print STDERR "Another migration is using this destination. Resume or stop its transfer, or let finalization finish, then retry. Do not delete the destination lock file.\n";
        exit 75;
    }
    invalid();
}
# Recheck the path after acquiring. Never adopt a linked or replaced inode.
@p = lstat($name);
@p && $s[0] == $p[0] && $s[1] == $p[1] or invalid();
# Any pending or malformed record blocks migration writes until recovery.
PENDING_GUARD
# Retain the same open-file description across exec and child operations.
# A disconnected client cannot release a still-running receiver's lock.
defined fcntl($lock, F_SETFD, 0) or invalid();
my @command = @ARGV ? ('/bin/zsh', '-f', '-c', $ARGV[0]) : ('/bin/zsh', '-f', '-s');
exec(@command) or invalid();
""".replace("PENDING_GUARD", PENDING_GUARD)


def lock_command(home: str) -> str:
    if not Path(home).is_absolute() or home == "/" or any(c in home for c in "\r\n\0"):
        raise ValueError("Invalid destination home for installation lock")
    return "exec /usr/bin/perl -e " + shlex.quote(LOCK_RUNNER) + " -- " + shlex.quote(home)


def locked_destination_script(home: str, script: str) -> str:
    """Run a shell body unchanged under an inherited, destination-side flock."""
    delimiter = "CODEX_MIGRATE_INSTALL_" + secrets.token_hex(16)
    while delimiter in script.splitlines():
        delimiter = "CODEX_MIGRATE_INSTALL_" + secrets.token_hex(16)
    return (lock_command(home) + " <<'" + delimiter + "'\n"
            + script + "\n" + delimiter + "\n")


def locked_receiver_command(home: str, command: str) -> str:
    """Keep stdin untouched: it carries rsync's binary protocol, not a script."""
    return lock_command(home) + " " + shlex.quote(command)
