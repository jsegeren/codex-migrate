"""Read-only destination recovery inspection; never authorizes replacement."""

import json
import shlex

from codex_migrate.errors import MigrationError
from codex_migrate.transaction import TRANSACTION_LIBRARY


# Uses the same persistent inode as writers, but opens it read-only and never
# creates it. No pending-record bypass is added to the normal write entrypoints.
INSPECT_RUNNER = TRANSACTION_LIBRARY + r'''
use Fcntl qw(:flock);
use Errno qw(EAGAIN EWOULDBLOCK);
use Unicode::Normalize ();
use feature 'fc';
sub emit {
    my ($value) = @_;
    print JSON::PP->new->canonical->utf8->encode($value), "\n" or fail();
    exit 0;
}
sub exact_keys {
    my ($value, @keys) = @_;
    ref($value) eq 'HASH' or fail();
    join('|', sort keys %$value) eq join('|', sort @keys) or fail();
}
sub clean_path {
    my ($path) = @_;
    defined($path) && !ref($path) && $path =~ m{\A/} &&
        $path !~ /[\r\n\0]/ && $path !~ m{//|/\.{1,2}(?:/|$)|/$} or fail();
}
sub inside {
    my ($path, $root) = @_;
    return $path =~ m{\A\Q$root\E/};
}
sub overlap {
    my ($a, $b) = @_;
    # Conservative case-folding avoids ambiguous scope on ordinary Mac volumes.
    ($a, $b) = (fc(Unicode::Normalize::NFD($a)), fc(Unicode::Normalize::NFD($b)));
    return $a eq $b || inside($a, $b) || inside($b, $a);
}
@ARGV == 1 or fail();
my $home = $ARGV[0];
$home = Encode::decode_utf8($home, Encode::FB_CROAK);
clean_path($home);
directory($home);
my $hs = present($home);
$home ne '/' && $hs->[4] == $< && $< != 0 && $< == $> or fail();
my $journal = $home . '/.codex-migrate-transaction.json';
my $lock_path = $home . '/.codex-migrate-destination.lock';
my $ls = present($lock_path);
if (!$ls) {
    !present($journal) or fail();
    emit({status => 'no_pending_record', inspected_items => 0});
}
$ls && S_ISREG($ls->[2]) && $ls->[3] == 1 && $ls->[4] == $< &&
    ($ls->[2] & 07777) == 0600 && $ls->[7] == 0 or fail();
my $lock = handle($lock_path);
unless (flock($lock, LOCK_SH | LOCK_NB)) {
    if ($! == EAGAIN || $! == EWOULDBLOCK) {
        emit({status => 'busy', inspected_items => 0});
    }
    fail();
}
my @opened = stat($lock);
my $locked = present($lock_path);
$locked && $opened[0] == $locked->[0] && $opened[1] == $locked->[1] or fail();
if (!present($journal)) { emit({status => 'no_pending_record', inspected_items => 0}); }
my $record = read_record($journal);
# Legacy records cannot acquire trusted fingerprints after the fact.
if (defined($record->{format}) && !ref($record->{format}) && $record->{format} eq '1') {
    emit({status => 'legacy_record', inspected_items => 0});
}
exact_keys($record, qw(format id home backup scope phase));
$record->{format} eq '2' && $record->{phase} eq 'replacing' &&
    $record->{home} eq $home && $record->{id} =~ /\A[0-9a-f]{32}\z/ &&
    ref($record->{scope}) eq 'ARRAY' && @{$record->{scope}} > 0 &&
    @{$record->{scope}} <= 10000 or fail();
my $backup = $record->{backup};
clean_path($backup);
$backup =~ m{\A\Q$home\E/[^/]+\z} or fail();
directory($backup);
my $bs = present($backup);
$bs->[0] == $hs->[0] && $bs->[4] == $< && ($bs->[2] & 0777) == 0700 or fail();
my @originals;
my @copies;
for my $item (@{$record->{scope}}) {
    exact_keys($item, qw(original backup existed backup_digest));
    my ($original, $copy) = @{$item}{qw(original backup)};
    clean_path($original); clean_path($copy);
    inside($original, $home) && inside($copy, $backup) &&
        !overlap($original, $backup) && !overlap($original, $journal) &&
        !overlap($original, $lock_path) && !overlap($original, $home . '/.ssh') or fail();
    # .codex is valid as one whole replacement, never an individual auth file.
    (!overlap($original, $home . '/.codex') || $original eq $home . '/.codex') or fail();
    for my $previous (@originals) { !overlap($previous, $original) or fail(); }
    for my $previous (@copies) { !overlap($previous, $copy) or fail(); }
    directory(parent($original), 1);
    directory(parent($copy), 1);
    JSON::PP::is_bool($item->{existed}) or fail();
    if ($item->{existed}) {
        defined($item->{backup_digest}) && !ref($item->{backup_digest}) &&
            $item->{backup_digest} =~ /\A[0-9a-f]{64}\z/ or fail();
    } else { !defined($item->{backup_digest}) or fail(); }
    push @originals, $original; push @copies, $copy;
}
# read_record/frozen-check failures are generic, not path/content dumps. A
# failed check does not mean the backup is absent or safe to replace.
for my $item (@{$record->{scope}}) { verify_frozen($item, $item->{backup}); }
my @items;
for my $item (@{$record->{scope}}) {
    my $current = present($item->{original});
    # Presence is intentionally not a claim about current bytes or usability.
    push @items, {original => $item->{original}, existed => $item->{existed},
                  current_present => $current ? JSON::PP::true : JSON::PP::false};
}
my $terminal_path = $backup . '/transaction-receipt.json';
my $terminal_phase;
if (present($terminal_path)) {
    my $terminal = read_record($terminal_path);
    $terminal_phase = $terminal->{phase};
    ($terminal_phase eq 'installed' || $terminal_phase eq 'restored') or fail();
    $terminal->{phase} = 'replacing';
    JSON::PP->new->canonical->encode($terminal) eq
        JSON::PP->new->canonical->encode($record) or fail();
}
emit({status => 'backup_verified', inspected_items => scalar(@items),
      backup => $backup, items => \@items, terminal_phase => $terminal_phase});
'''


MESSAGES = {
    "no_pending_record": "No unfinished-installation record was found. This does not verify that a migration finished or that the workspace is usable.",
    "busy": "A migration is still using this destination. Let it finish or stop it safely before checking recovery again. Do not delete the lock file.",
    "legacy_record": "This interrupted installation has older recovery evidence without frozen backup checksums. Keep Codex closed, staging and backups intact, and contact support.",
    "backup_verified": "The saved backup still matches its pre-installation checksums. No files were restored or removed. Keep destination Codex closed; guided restore is not available yet.",
}


def inspection_script(home):
    return ("/usr/bin/env -u PERL5OPT -u PERL5LIB -u PERLLIB -u PERLIO -u PERL_UNICODE "
            "LC_ALL=C /usr/bin/perl -e " + shlex.quote(INSPECT_RUNNER) + " -- " + shlex.quote(home) + "\n")


def _validate_report(report, home):
    if not isinstance(report, dict) or report.get("status") not in MESSAGES:
        raise ValueError("Invalid recovery report")
    if report["status"] != "backup_verified":
        if set(report) != {"status", "inspected_items"} or type(report["inspected_items"]) is not int or report["inspected_items"] != 0:
            raise ValueError("Invalid recovery summary")
        return
    if set(report) != {"status", "inspected_items", "backup", "items", "terminal_phase"}:
        raise ValueError("Invalid recovery fields")
    if report["terminal_phase"] not in (None, "installed", "restored"):
        raise ValueError("Invalid recovery phase")
    items = report["items"]
    if (not isinstance(items, list) or not 0 < len(items) <= 10000
            or type(report["inspected_items"]) is not int or report["inspected_items"] != len(items)):
        raise ValueError("Invalid recovery count")
    paths = [report["backup"]]
    for item in items:
        if (not isinstance(item, dict) or set(item) != {"original", "existed", "current_present"}
                or type(item["existed"]) is not bool or type(item["current_present"]) is not bool):
            raise ValueError("Invalid recovery item")
        paths.append(item["original"])
    for path in paths:
        if (not isinstance(path, str) or not path.startswith(home + "/")
                or any(c in path for c in "\r\n\0")
                or any(part in ("", ".", "..") for part in path[1:].split("/"))):
            raise ValueError("Invalid recovery path")


def inspect_recovery(config, transport, cancelled=None):
    """No local StateStore or source scan is required to inspect the destination."""
    try:
        script = inspection_script(config.target_home)
        if cancelled is None:
            result = transport.run_remote(script, timeout=24 * 60 * 60)
        else:
            result = transport.run_remote_cancellable(script, 24 * 60 * 60, cancelled)
        if len(result.stdout) > 1048576:
            raise ValueError("Oversized recovery report")
        report = json.loads(result.stdout)
        _validate_report(report, config.target_home)
    except Exception as error:
        raise MigrationError("Recovery could not be verified. No recovery changes were made. "
                             "Keep destination Codex closed, staging and backups intact, and contact support.") from error
    report["message"] = MESSAGES[report["status"]]
    return report
