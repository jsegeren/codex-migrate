"""Bounded, read-only screening for unsupported Codex storage overrides.

This is not a TOML evaluator or discovery of every running process's settings.
It checks visible CODEX_HOME and user config/profile keys without emitting
configuration values. The same system-Perl guard runs on either Mac.
"""

import os
from pathlib import Path
import pwd
import shlex
import subprocess
import time

from codex_migrate.errors import MigrationError
from codex_migrate.transport import _stop_process
from codex_migrate.source_availability import require_local


RUNNER = r'''
use strict; use warnings; use Fcntl qw(:DEFAULT :mode);
sub stop {
    my ($code) = @_;
    my %why = (65 => 'Custom CODEX_HOME detected.', 66 => 'A sqlite_home configuration setting needs review.');
    print STDERR ($why{$code} || 'Codex storage configuration could not be safely checked.'),
        " Keep existing files and settings intact; contact support before full migration. No migration data was changed.\n";
    exit $code;
}
my ($home, $check_env) = @ARGV;
@ARGV == 2 && defined($home) && $home =~ m{\A/[^\r\n\0]+\z} or stop(67);
my $root = "$home/.codex";
if ($check_env eq '1' && exists($ENV{CODEX_HOME}) && length($ENV{CODEX_HOME})) {
    my $configured = $ENV{CODEX_HOME};
    my @actual = stat($configured); my @expected = stat($root);
    @actual && @expected && S_ISDIR($actual[2]) && S_ISDIR($expected[2]) &&
        $actual[0] == $expected[0] && $actual[1] == $expected[1] or stop(65);
}
my @dir = lstat($root);
if (!@dir) { $!{ENOENT} ? exit(0) : stop(67); }
S_ISDIR($dir[2]) or stop(67);
my %identity;
for my $name ('auth.json', 'installation_id') {
    my @s = stat("$root/$name");
    if (@s) { $identity{"$s[0]:$s[1]"} = 1; }
    elsif (!$!{ENOENT}) { stop(67); }
}

# Screen keys lexically, including quoted/escaped keys and legacy profile
# tables. Values, comments and multiline strings are not interpreted as keys.
# Any sqlite_home key requires review, even if a value happens to be default.
sub screen {
    my ($text) = @_;
    my $n = length($text); my $i = 0;
    while ($i < $n) {
        my $c = substr($text, $i, 1);
        if ($c =~ /\s/) { $i++; next; }
        if ($c eq '#') { my $end = index($text, "\n", $i); $i = $end < 0 ? $n : $end + 1; next; }
        my $token = '';
        if ($c eq '"' || $c eq "'") {
            my $quote = $c; my $triple = substr($text, $i, 3) eq ($quote x 3);
            $i += $triple ? 3 : 1; my $closed = 0;
            while ($i < $n) {
                $c = substr($text, $i, 1);
                if ($c eq $quote) {
                    my $run = 0; $run++ while $i + $run < $n && substr($text, $i + $run, 1) eq $quote;
                    if (!$triple || $run >= 3) { $i += $triple ? $run : 1; $closed = 1; last; }
                }
                if ($quote eq '"' && $c eq '\\') {
                    $i++; $i < $n or stop(67); my $escape = substr($text, $i++, 1);
                    if ($escape eq 'u' || $escape eq 'U') {
                        my $width = $escape eq 'u' ? 4 : 8;
                        my $hex = substr($text, $i, $width);
                        length($hex) == $width && $hex =~ /\A[0-9a-fA-F]+\z/ or stop(67);
                        my $point = hex($hex);
                        $point <= 0x10ffff && !($point >= 0xd800 && $point <= 0xdfff) or stop(67);
                        $token .= chr($point); $i += $width;
                    } else { $token .= "\0"; }
                } else { $token .= $c; $i++; }
            }
            $closed or stop(67);
            next if $triple;
        } elsif ($c =~ /[A-Za-z0-9_-]/) {
            while ($i < $n && substr($text, $i, 1) =~ /[A-Za-z0-9_-]/) { $token .= substr($text, $i++, 1); }
        } else { $i++; next; }
        my $next = $i; $next++ while $next < $n && substr($text, $next, 1) =~ /[ \t]/;
        stop(66) if $token eq 'sqlite_home' && $next < $n && substr($text, $next, 1) =~ /[=.]/;
    }
}
opendir(my $dh, $root) or stop(67);
my ($entries, $files, $total) = (0, 0, 0);
while (1) {
    $! = 0;
    my $name = readdir($dh);
    if (!defined($name)) { $! ? stop(67) : last; }
    ++$entries <= 10000 or stop(67);
    next unless lc($name) eq 'config.toml' || $name =~ /\.config\.toml\z/i;
    ++$files <= 64 or stop(67);
    my $path = "$root/$name";
    my @before = lstat($path);
    @before && S_ISREG($before[2]) && $before[7] <= 1048576 && !$identity{"$before[0]:$before[1]"} or stop(67);
    sysopen(my $fh, $path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK) or stop(67);
    my @opened = stat($fh);
    @opened && S_ISREG($opened[2]) && $opened[0] == $before[0] && $opened[1] == $before[1] or stop(67);
    my $text = '';
    while (1) {
        my $count = sysread($fh, my $chunk, 8192);
        defined($count) or stop(67); last unless $count;
        $text .= $chunk; $total += $count;
        length($text) <= 1048576 && $total <= 4194304 or stop(67);
    }
    my @after = stat($fh); close($fh) or stop(67);
    @after && $after[7] == length($text) && $after[9] == $before[9] && $after[10] == $before[10] or stop(67);
    screen($text);
}
closedir($dh) or stop(67);
'''

MESSAGES = {
    65: "A custom CODEX_HOME is active. This migration supports the selected home's .codex folder only. Keep the custom storage intact and contact support to review the scope; do not unset the override just to bypass this check.",
    66: "A sqlite_home setting was found in a user configuration or profile. Its database storage needs review before full migration; do not remove the setting just to bypass this check.",
    67: "Codex storage configuration could not be safely checked. Keep the files intact and contact support before full migration.",
}


def storage_scope_script(home, check_environment=True):
    return ("/usr/bin/env -u PERL5OPT -u PERL5LIB -u PERLLIB -u PERLIO -u PERL_UNICODE "
            "LC_ALL=C /usr/bin/perl -e " + shlex.quote(RUNNER) + " -- "
            + shlex.quote(home) + (" 1\n" if check_environment else " 0\n"))


def require_source_storage(home, checkpoint=lambda: None):
    checkpoint()
    root = Path(home) / ".codex"
    if root.exists():
        require_local(root)
        if not root.is_symlink() and root.is_dir():
            try:
                with os.scandir(root) as entries:
                    for entry in entries:
                        checkpoint()
                        name = entry.name.lower()
                        if name == "config.toml" or name.endswith(".config.toml"):
                            require_local(entry.path)
            except OSError:
                raise MigrationError(MESSAGES[67]) from None
    # An explicit inspection of another home cannot describe that account's
    # environment using the caller's inherited variables.
    try:
        own = Path(pwd.getpwuid(os.getuid()).pw_dir).stat()
        selected = Path(home).stat()
        own_home = (own.st_dev, own.st_ino) == (selected.st_dev, selected.st_ino)
        if own_home and selected.st_uid != os.getuid():
            raise ValueError("Home ownership mismatch")
    except (OSError, KeyError, ValueError):
        raise MigrationError(MESSAGES[67]) from None
    script = storage_scope_script(home, own_home)
    checkpoint()
    process = subprocess.Popen(["/bin/zsh", "-f", "-s"], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True)
    started = time.monotonic()
    try:
        first = True
        while True:
            checkpoint()
            try:
                process.communicate(input=script if first else None, timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                first = False
                if time.monotonic() - started > 30:
                    raise MigrationError(MESSAGES[67])
    except BaseException:
        _stop_process(process)
        raise
    if process.returncode:
        raise MigrationError(MESSAGES.get(process.returncode, MESSAGES[67]))
