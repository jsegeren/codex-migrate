"""Read-only destination recovery inspection; never authorizes replacement."""

import json
import re
import shlex

from codex_migrate.errors import MigrationError
from codex_migrate.transaction import TRANSACTION_LIBRARY


# Uses the same persistent inode as writers, but opens it read-only and never
# creates it. No pending-record bypass is added to the normal write entrypoints.
RECOVERY_LIBRARY = TRANSACTION_LIBRARY + r'''
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
sub identical {
    return JSON::PP->new->canonical->encode($_[0]) eq JSON::PP->new->canonical->encode($_[1]);
}
sub valid_snapshot {
    my ($s) = @_;
    exact_keys($s, qw(existed backup_digest));
    JSON::PP::is_bool($s->{existed}) or fail();
    if ($s->{existed}) {
        defined($s->{backup_digest}) && !ref($s->{backup_digest}) &&
            $s->{backup_digest} =~ /\A[0-9a-f]{64}\z/ or fail();
    } else { !defined($s->{backup_digest}) or fail(); }
}
sub validate_transaction {
    my ($record, $home, $device) = @_;
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
    $bs->[0] == $device && $bs->[4] == $< && ($bs->[2] & 07777) == 0700 or fail();
    my (@originals, @copies);
    for my $item (@{$record->{scope}}) {
        exact_keys($item, qw(original backup existed backup_digest));
        my ($original, $copy) = @{$item}{qw(original backup)};
        clean_path($original); clean_path($copy);
        inside($original, $home) && inside($copy, $backup) &&
            !overlap($original, $backup) &&
            !overlap($original, $home . '/.codex-migrate-transaction.json') &&
            !overlap($original, $home . '/.codex-migrate-destination.lock') &&
            !overlap($original, $home . '/.ssh') or fail();
        (!overlap($original, $home . '/.codex') || $original eq $home . '/.codex') or fail();
        for my $previous (@originals) { !overlap($previous, $original) or fail(); }
        for my $previous (@copies) { !overlap($previous, $copy) or fail(); }
        directory(parent($original), 1); directory(parent($copy), 1);
        valid_snapshot({existed => $item->{existed}, backup_digest => $item->{backup_digest}});
        push @originals, $original; push @copies, $copy;
    }
}
sub validate_restore_plan {
    my ($plan, $record) = @_;
    exact_keys($plan, qw(format transaction current));
    $plan->{format} eq '1' && identical($plan->{transaction}, $record) &&
        ref($plan->{current}) eq 'ARRAY' &&
        @{$plan->{current}} == @{$record->{scope}} or fail();
    for my $s (@{$plan->{current}}) { valid_snapshot($s); }
}
sub validate_restore_ready {
    my ($ready, $plan) = @_;
    exact_keys($ready, qw(format plan desired));
    $ready->{format} eq '1' && identical($ready->{plan}, $plan) &&
        ref($ready->{desired}) eq 'ARRAY' &&
        @{$ready->{desired}} == @{$plan->{current}} or fail();
    for my $i (0..$#{$plan->{current}}) {
        valid_snapshot($ready->{desired}[$i]);
        $ready->{desired}[$i]{existed} == $plan->{transaction}{scope}[$i]{existed} or fail();
    }
}
sub checked_recovery_directory {
    my ($path, $device) = @_;
    directory($path);
    my $s = present($path);
    $s->[0] == $device && $s->[4] == $< && ($s->[2] & 07777) == 0700 or fail();
}
sub directory_entries {
    my ($path) = @_;
    opendir(my $dh, filesystem_path($path)) or fail();
    $! = 0;
    my @names = grep { $_ ne '.' && $_ ne '..' } readdir($dh);
    !$! or fail();
    closedir($dh) or fail();
    return @names;
}
'''

# Reconciliation shares the same read-only existing-inode lock as inspection.
# No writer is allowed while either operation verifies saved/current contents.
RECOVERY_LOCK = RECOVERY_LIBRARY + r'''
@ARGV >= 2 or fail();
my $mode = $ARGV[0];
$mode eq 'inspect' || $mode eq 'restore' || $mode eq 'reconcile' or fail();
my $home = $ARGV[1];
$home = Encode::decode_utf8($home, Encode::FB_CROAK);
clean_path($home);
directory($home);
my $hs = present($home);
$home ne '/' && $hs->[4] == $< && $< != 0 && $< == $> or fail();
my $journal = $home . '/.codex-migrate-transaction.json';
my $lock_path = $home . '/.codex-migrate-destination.lock';
my $ls = present($lock_path);
if (!$ls) {
    $mode ne 'reconcile' or fail();
    !present($journal) or fail();
    emit({status => 'no_pending_record', inspected_items => 0});
}
$ls && S_ISREG($ls->[2]) && $ls->[3] == 1 && $ls->[4] == $< &&
    ($ls->[2] & 07777) == 0600 && $ls->[7] == 0 or fail();
my $lock = handle($lock_path);
unless (flock($lock, ($mode eq 'restore' ? LOCK_EX : LOCK_SH) | LOCK_NB)) {
    if ($! == EAGAIN || $! == EWOULDBLOCK) {
        emit({status => 'busy', inspected_items => 0});
    }
    fail();
}
my @opened = stat($lock);
my $locked = present($lock_path);
$locked && $opened[0] == $locked->[0] && $opened[1] == $locked->[1] or fail();
'''

RECOVERY_CONTEXT = RECOVERY_LOCK + r'''
if (!present($journal)) { emit({status => 'no_pending_record', inspected_items => 0}); }
my $record = read_record($journal);
# Legacy records cannot acquire trusted fingerprints after the fact.
if (defined($record->{format}) && !ref($record->{format}) && $record->{format} eq '1') {
    emit({status => 'legacy_record', inspected_items => 0});
}
validate_transaction($record, $home, $hs->[0]);
my $backup = $record->{backup};
# read_record/frozen-check failures are generic, not path/content dumps. A
# failed check does not mean the backup is absent or safe to replace.
for my $item (@{$record->{scope}}) { verify_frozen($item, $item->{backup}); }
'''

INSPECT_RUNNER = RECOVERY_CONTEXT + r'''
@ARGV == 2 && $mode eq 'inspect' or fail();
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
      transaction_id => $record->{id}, backup => $backup, items => \@items,
      terminal_phase => $terminal_phase});
'''


MESSAGES = {
    "no_pending_record": "No unfinished-installation record was found. This does not verify that a migration finished or that the workspace is usable.",
    "busy": "A migration is still using this destination. Let it finish or stop it safely before checking recovery again. Do not delete the lock file.",
    "legacy_record": "This interrupted installation has older recovery evidence without frozen backup checksums. Keep Codex closed, staging and backups intact, and contact support.",
    "backup_verified": "The saved backup still matches its pre-installation checksums. No files were restored or removed. Review the listed paths before restoring; keep destination Codex and all writing apps closed.",
}


def inspection_script(home):
    return ("/usr/bin/env -u PERL5OPT -u PERL5LIB -u PERLLIB -u PERLIO -u PERL_UNICODE "
            "LC_ALL=C /usr/bin/perl -e " + shlex.quote(INSPECT_RUNNER) + " -- inspect " + shlex.quote(home) + "\n")


def _validate_report(report, home):
    if not isinstance(report, dict) or report.get("status") not in MESSAGES:
        raise ValueError("Invalid recovery report")
    if report["status"] != "backup_verified":
        if set(report) != {"status", "inspected_items"} or type(report["inspected_items"]) is not int or report["inspected_items"] != 0:
            raise ValueError("Invalid recovery summary")
        return
    if set(report) != {"status", "inspected_items", "transaction_id", "backup", "items", "terminal_phase"}:
        raise ValueError("Invalid recovery fields")
    if not isinstance(report["transaction_id"], str) or not re.fullmatch(r"[0-9a-f]{32}", report["transaction_id"]):
        raise ValueError("Invalid recovery identity")
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


def recovery_reference(home, inspection):
    """Retain only the inspected identity/scope, never accept arbitrary fields."""
    report = {k: v for k, v in inspection.items() if k not in ("message", "checked_at")}
    _validate_report(report, home)
    if report["status"] != "backup_verified":
        raise MigrationError("A verified pending backup is required before restoration")
    reference = {"transaction_id": report["transaction_id"], "backup": report["backup"],
                 "originals": [item["original"] for item in report["items"]]}
    validate_recovery_reference(reference, home)
    return reference


def validate_recovery_reference(reference, home):
    if not isinstance(reference, dict) or set(reference) != {"transaction_id", "backup", "originals"}:
        raise ValueError("Invalid recovery reference")
    if not isinstance(reference["transaction_id"], str) or not re.fullmatch(r"[0-9a-f]{32}", reference["transaction_id"]):
        raise ValueError("Invalid recovery identity")
    originals = reference["originals"]
    if not isinstance(originals, list) or not 0 < len(originals) <= 10000:
        raise ValueError("Invalid recovery scope")
    for path in [reference["backup"], *originals]:
        if (not isinstance(path, str) or not path.startswith(home + "/")
                or any(c in path for c in "\r\n\0")
                or any(part in ("", ".", "..") for part in path[1:].split("/"))):
            raise ValueError("Invalid recovery path")
    if "/" in reference["backup"][len(home) + 1:] or len(set(originals)) != len(originals):
        raise ValueError("Invalid recovery scope")
    if len(json.dumps(reference).encode("utf-8")) > 1048576:
        raise ValueError("Oversized recovery reference")


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
