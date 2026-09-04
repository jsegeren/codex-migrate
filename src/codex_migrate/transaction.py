"""Durable destination evidence around replacement; no source data is read."""

import json
import secrets
import shlex

from codex_migrate.tree_digest import PERL_IMPORTS, TREE_FUNCTIONS

TRANSACTION_NAME = ".codex-migrate-transaction.json"
PENDING_MESSAGE = ("An unfinished destination installation needs recovery. Keep Codex closed on the "
                   "destination and keep staging and backups. Do not delete the recovery record; contact support.")
PENDING_GUARD = ("my @pending = lstat($home . '/" + TRANSACTION_NAME + "');\n"
                 "if (@pending || $! != Errno::ENOENT()) {\n"
                 "  print STDERR \"" + PENDING_MESSAGE + "\\n\"; exit 78;\n}\n")


def pending_check_script(home):
    """Read-only presence check, before ordinary preflight needs intact data."""
    return ("/usr/bin/perl -MErrno -e "
            + shlex.quote("my $home = $ARGV[0];\n" + PENDING_GUARD)
            + " -- " + shlex.quote(home) + "\n")


def recovery_preflight_script(home):
    return ("/usr/bin/perl -MJSON::PP -MIO::Handle -MDigest::SHA -MTime::HiRes -MEncode -e 'IO::Handle->can(\"sync\") or exit 78' "
            "2>/dev/null || { echo 'Required destination recovery tools are unavailable. "
            "Transfer was not started; contact support.' >&2; exit 78; }\n"
            + pending_check_script(home))

# macOS fcntl.h defines F_FULLFSYNC as 51. fsync each file/directory, then use
# the device barrier before progressing past a durable transaction boundary.
# See the local macOS fsync(2)/fcntl(2) manuals; failures never fall back to sync.
TRANSACTION_LIBRARY = PERL_IMPORTS + r'''
use IO::Handle;
use JSON::PP;
use Errno qw(ENOENT);
use Encode ();
my $codex_mode = 0;
sub excluded { return 0; }
''' + TREE_FUNCTIONS + r'''
sub fail {
    print STDERR "Destination recovery evidence could not be safely saved or verified. Keep Codex closed, staging and backups intact, and contact support.\n";
    exit 78;
}
$SIG{__WARN__} = sub { fail(); };
$SIG{__DIE__} = sub { fail(); };
sub filesystem_path {
    my ($path) = @_;
    # JSON paths are Unicode; readdir and symlink text are filesystem bytes.
    # Convert only at the filesystem boundary, never the JSON record itself.
    return utf8::is_utf8($path) ? Encode::encode_utf8($path) : $path;
}
sub present {
    my ($path) = @_;
    $path = filesystem_path($path);
    my @s = lstat($path);
    return \@s if @s;
    $! == ENOENT or fail();
    return undef;
}
sub directory {
    my ($path, $missing_ok) = @_;
    $path =~ m{^/} && $path !~ /[\r\n\0]/ or fail();
    my $current = '';
    for my $part (split m{/}, $path) {
        next if $part eq '';
        $part ne '.' && $part ne '..' or fail();
        $current .= '/' . $part;
        my $s = present($current);
        return if !$s && $missing_ok;
        $s && S_ISDIR($s->[2]) or fail();
    }
}
sub parent { my ($p) = @_; $p =~ s{/[^/]+$}{}; return $p || '/'; }
sub handle {
    my ($path) = @_;
    $path = filesystem_path($path);
    my $s = present($path);
    $s && (S_ISREG($s->[2]) || S_ISDIR($s->[2])) or fail();
    sysopen(my $fh, $path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK) or fail();
    my @f = stat($fh);
    @f && $f[0] == $s->[0] && $f[1] == $s->[1] or fail();
    return $fh;
}
sub flush_tree {
    my ($path, $device) = @_;
    $path = filesystem_path($path);
    my $s = present($path);
    $s && $s->[0] == $device or fail();
    return if S_ISLNK($s->[2]); # the containing directory is synced by caller
    my $fh = handle($path);
    if (S_ISDIR($s->[2])) {
        opendir(my $dir, $path) or fail();
        my @names = grep { $_ ne '.' && $_ ne '..' } readdir($dir);
        closedir($dir) or fail();
        for my $name (@names) { flush_tree($path . '/' . $name, $device); }
    }
    $fh->sync or fail();
    close($fh) or fail();
}
sub flush_parent {
    my ($path) = @_;
    my $fh = handle(parent($path));
    $fh->sync or fail();
    close($fh) or fail();
}
sub exclusive_rename {
    my ($from, $to) = @_;
    $^O eq 'darwin' or fail();
    my $source = filesystem_path($from);
    my $destination = filesystem_path($to);
    # Darwin SDK sys/syscall.h: SYS_renameatx_np=488; sys/fcntl.h:
    # AT_FDCWD=-2; sys/stdio.h: RENAME_EXCL=4 (macOS 10.12+).
    # Atomic failure if the destination appears, including files/symlinks.
    # System Perl has syscall but ships no generated sys/syscall.ph. Never
    # fall back to check-then-rename or a replacing rename on unsupported OSes.
    syscall(488, -2, $source, -2, $destination, 4) == 0 or fail();
}
sub save_new {
    my ($path, $value, $id) = @_;
    $path = filesystem_path($path);
    !present($path) or fail();
    my $bytes = JSON::PP->new->canonical->utf8->encode($value);
    length($bytes) > 0 && length($bytes) <= 1048576 or fail();
    my $temp = $path . '.pending-' . $id;
    sysopen(my $fh, $temp, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600) or fail();
    my $offset = 0;
    while ($offset < length($bytes)) {
        my $n = syswrite($fh, $bytes, length($bytes) - $offset, $offset);
        defined($n) && $n > 0 or fail();
        $offset += $n;
    }
    $fh->sync or fail();
    exclusive_rename($temp, $path);
    flush_parent($path);
    defined fcntl($fh, 51, 0) or fail();
    close($fh) or fail();
}
sub read_record {
    my ($path) = @_;
    $path = filesystem_path($path);
    my $s = present($path);
    $s && S_ISREG($s->[2]) && $s->[3] == 1 && $s->[4] == $< &&
        ($s->[2] & 07777) == 0600 && $s->[7] > 0 && $s->[7] <= 1048576 or fail();
    my $fh = handle($path);
    my $bytes = '';
    while (length($bytes) <= 1048576) {
        my $chunk;
        my $n = sysread($fh, $chunk, 65536);
        defined($n) or fail();
        last if $n == 0;
        $bytes .= $chunk;
    }
    length($bytes) == $s->[7] or fail();
    close($fh) or fail();
    my $record = eval { JSON::PP->new->utf8->decode($bytes) };
    !$@ && ref($record) eq 'HASH' or fail();
    return $record;
}
sub digest {
    my ($path) = @_;
    directory(parent($path));
    return unpack('H*', tree(filesystem_path($path), ''));
}
sub verify_frozen {
    my ($item, $path) = @_;
    JSON::PP::is_bool($item->{existed}) or fail();
    if ($item->{existed}) {
        defined($item->{backup_digest}) && !ref($item->{backup_digest}) &&
            $item->{backup_digest} =~ /\A[0-9a-f]{64}\z/ or fail();
        digest($path) eq $item->{backup_digest} or fail();
    } else {
        !defined($item->{backup_digest}) && !present($path) or fail();
    }
}
'''

TRANSACTION_RUNNER = TRANSACTION_LIBRARY + r'''
@ARGV == 2 or fail();
my ($mode, $payload) = @ARGV;
$mode =~ /\A(?:begin|check-backup|installed|restored|clear)\z/ or fail();
my $plan = eval { JSON::PP->new->utf8->decode($payload) };
!$@ && ref($plan) eq 'HASH' && $plan->{format} == 2 &&
    $plan->{id} =~ /\A[0-9a-f]{32}\z/ && ref($plan->{scope}) eq 'ARRAY' &&
    @{$plan->{scope}} > 0 or fail();
my ($home, $backup, $id) = @{$plan}{qw(home backup id)};
directory($home);
my $hs = present($home);
$home ne '/' && $hs->[4] == $< && $< != 0 && $< == $> or fail();
$backup =~ /\A\Q$home\E\/[^\/]+\z/ or fail();
directory($backup);
my $device = $hs->[0];
my $journal = $home . '/.codex-migrate-transaction.json';
umask 0077;
for my $item (@{$plan->{scope}}) {
    ref($item) eq 'HASH' or fail();
    my ($original, $copy) = @{$item}{qw(original backup)};
    $original =~ /\A\Q$home\E\/.+/ && $copy =~ /\A\Q$backup\E\/.+/ or fail();
    directory(parent($original));
    directory(parent($copy), 1);
    present(parent($original))->[0] == $device or fail();
}
if ($mode eq 'begin') {
    !present($journal) or fail();
    for my $item (@{$plan->{scope}}) {
        my $original = present($item->{original});
        my $copy = present($item->{backup});
        (!!$original) == (!!$copy) or fail();
        $item->{existed} = $original ? JSON::PP::true : JSON::PP::false;
        $item->{backup_digest} = $copy ? digest($item->{backup}) : undef;
        verify_frozen($item, $item->{original});
    }
    flush_tree($backup, $device);
    flush_parent($backup);
    $plan->{phase} = 'replacing';
    save_new($journal, $plan, $id);
} else {
    my $record = read_record($journal);
    $record->{format} == 2 && $record->{id} eq $id && $record->{home} eq $home && $record->{backup} eq $backup &&
        $record->{phase} eq 'replacing' or fail();
    my @expected = map { +{ original => $_->{original}, backup => $_->{backup} } } @{$record->{scope}};
    JSON::PP->new->canonical->encode(\@expected) eq JSON::PP->new->canonical->encode($plan->{scope}) or fail();
    # The backup must still match its pre-replacement snapshot, not merely
    # match another possibly corrupted copy. Never print these local digests.
    if ($mode ne 'clear') {
        for my $item (@{$record->{scope}}) { verify_frozen($item, $item->{backup}); }
        exit 0 if $mode eq 'check-backup';
    }
    if ($mode eq 'clear') {
        my $receipt = $backup . '/transaction-receipt.json';
        my $terminal = read_record($receipt);
        ($terminal->{phase} eq 'installed' || $terminal->{phase} eq 'restored') or fail();
        $terminal->{phase} = 'replacing';
        JSON::PP->new->canonical->encode($terminal) eq JSON::PP->new->canonical->encode($record) or fail();
        unlink($journal) or fail();
        flush_parent($journal);
        my $fh = handle($receipt);
        defined fcntl($fh, 51, 0) or fail();
        close($fh) or fail();
        exit 0;
    }
    for my $item (@{$record->{scope}}) {
        verify_frozen($item, $item->{original}) if $mode eq 'restored';
        my $s = present($item->{original});
        if ($mode eq 'installed' || $item->{existed}) {
            $s or fail();
            flush_tree($item->{original}, $device);
        } else {
            !$s or fail();
        }
        flush_parent($item->{original});
    }
    $record->{phase} = $mode;
    my $receipt = $backup . '/transaction-receipt.json';
    save_new($receipt, $record, $id);
}
'''


def transaction_commands(home, backup, mappings):
    """Begin defines the shared helper; subsequent commands run in that shell."""
    payload = json.dumps({"format": 2, "id": secrets.token_hex(16), "home": home,
                          "backup": backup,
                          "scope": [{"original": a, "backup": b} for a, b in mappings]})
    definition = ("cm_transaction() {\n/usr/bin/perl -e " + shlex.quote(TRANSACTION_RUNNER)
                  + " -- \"$1\" " + shlex.quote(payload) + "\n}\n")
    # zsh ERR_EXIT inside a function can bypass the caller's EXIT trap. An
    # explicit top-level exit preserves rollback for ordinary helper failures.
    return (definition + "cm_transaction begin || exit 78", "cm_transaction installed || exit 78",
            "cm_transaction restored", "cm_transaction clear")


def rollback_checks(mappings):
    """A restore is successful only when every original matches its backup."""
    checks = ["rollback_verified=1"]
    for original, backup in mappings:
        a, b = shlex.quote(original), shlex.quote(backup)
        checks.append("if test -e {b} || test -L {b}; then\n"
                      "  verify_backup {b} {a} || rollback_verified=0\n"
                      "elif test -e {a} || test -L {a}; then rollback_verified=0; fi".format(a=a, b=b))
    return "\n".join(checks)
