"""Internal post-crash restore engine. Not exposed by CLI/dashboard yet.

Only destination-local, explicitly confirmed recovery writes are performed.
Prepared copies are disposable; current destination entries are never deleted.
"""

import json
import shlex

from codex_migrate.errors import MigrationError
from codex_migrate.processes import require_codex_closed_script
from codex_migrate.recovery import RECOVERY_CONTEXT, _validate_report


RESTORE_RUNNER = RECOVERY_CONTEXT + r'''
@ARGV == 4 && $mode eq 'restore' or fail();
my $confirmation = eval { JSON::PP->new->utf8->decode($ARGV[2]) };
!$@ or fail();
exact_keys($confirmation, qw(transaction_id backup originals));
my $id = $record->{id};
$confirmation->{transaction_id} eq $id && $confirmation->{backup} eq $backup &&
    ref($confirmation->{originals}) eq 'ARRAY' or fail();
sub identical {
    return JSON::PP->new->canonical->encode($_[0]) eq JSON::PP->new->canonical->encode($_[1]);
}
my @expected = map { $_->{original} } @{$record->{scope}};
identical(\@expected, $confirmation->{originals}) or fail();
for my $item (@{$record->{scope}}) {
    # Full migration requires an existing signed-in destination. A record
    # without its previous Codex root cannot authorize removing a newer login.
    $item->{original} ne $home . '/.codex' || $item->{existed} or fail();
}
my $root = $backup . '/recovery-' . $id;
for my $item (@{$record->{scope}}) { !overlap($root, $item->{backup}) or fail(); }
my $device = $hs->[0];
umask 0077;
# Keep exclusion alive in copy/process-check children if the SSH parent dies.
fcntl($lock, F_SETFD, 0) or fail();
my $guard = $ARGV[3];
sub closed {
    system('/bin/zsh', '-f', '-c', $guard) == 0 or fail();
}
sub owned_directory {
    my ($path, $create) = @_;
    directory(parent($path));
    if (!present($path) && $create) {
        mkdir(filesystem_path($path), 0700) or fail();
        flush_parent($path);
    }
    directory($path);
    my $s = present($path);
    $s->[0] == $device && $s->[4] == $< && ($s->[2] & 07777) == 0700 or fail();
}
sub names {
    my ($path) = @_;
    opendir(my $dh, filesystem_path($path)) or fail();
    $! = 0;
    my @names = grep { $_ ne '.' && $_ ne '..' } readdir($dh);
    !$! or fail();
    closedir($dh) or fail();
    return @names;
}
sub snapshot {
    my ($path) = @_;
    directory(parent($path));
    my $s = present($path);
    if ($s) { $s->[0] == $device or fail(); }
    return {existed => $s ? JSON::PP::true : JSON::PP::false,
            backup_digest => $s ? digest($path) : undef};
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
sub barrier {
    my ($evidence) = @_;
    my $fh = handle($evidence);
    defined fcntl($fh, 51, 0) or fail();
    close($fh) or fail();
}
sub move_new {
    my ($from, $to, $evidence) = @_;
    directory(parent($from)); directory(parent($to));
    !present($to) && present($from) or fail();
    closed();
    exclusive_rename($from, $to);
    flush_parent($from); flush_parent($to); barrier($evidence);
}
sub quarantine {
    my ($path, $folder, $evidence) = @_;
    # Retain an interrupted generated copy/metadata write, never delete it or
    # adopt it as trusted data. Bounded slots avoid an unbounded retry fleet.
    owned_directory($folder, 1);
    for my $n (0..99) {
        my $to = $folder . '/' . $n;
        if (!present($to)) { move_new($path, $to, $evidence); return; }
    }
    fail();
}
sub save_recoverable {
    my ($path, $value, $evidence) = @_;
    if (present($path)) {
        identical(read_record($path), $value) or fail();
        # A previous attempt may have died after rename but before the device
        # barrier. Visibility alone is not durable publication.
        flush_tree($path, $device); flush_parent($path); barrier($path);
        return;
    }
    my $partial = $path . '.pending-' . $id;
    if (present($partial)) {
        my $s = present($partial);
        S_ISREG($s->[2]) && $s->[3] == 1 && $s->[4] == $< &&
            ($s->[2] & 07777) == 0600 or fail();
        quarantine($partial, $root . '/incomplete', $evidence);
    }
    save_new($path, $value, $id);
}
sub capture {
    my (@command) = @_;
    my $pid = open(my $fh, '-|');
    defined($pid) or fail();
    if ($pid == 0) {
        open(STDERR, '>', '/dev/null') or exit 78;
        exec @command;
        exit 78;
    }
    my $result = '';
    while (my $line = <$fh>) { $result .= $line; length($result) <= 1048576 or fail(); }
    close($fh) or fail();
    return $result;
}
sub space {
    my ($preparing) = @_;
    my $required = 2 * 1024 * 1024 * 1024;
    if ($preparing) {
        for my $item (@{$record->{scope}}) {
            next unless $item->{existed};
            my $size = capture('/usr/bin/du', '-sk', filesystem_path($item->{backup}));
            $size =~ /\A([0-9]+)\s/ or fail();
            $required += $1 * 1024;
        }
    }
    my $df = capture('/bin/df', '-Pk', filesystem_path($home));
    my @lines = split /\n/, $df;
    @lines == 2 or fail();
    my @fields = split /\s+/, $lines[1];
    @fields >= 6 && $fields[3] =~ /\A[0-9]+\z/ or fail();
    $fields[3] * 1024 >= $required or fail();
}
sub identity_files {
    my ($codex) = @_;
    return unless present($codex);
    directory($codex);
    # Never follow a credential link, or ambiguously overwrite a case alias.
    for my $name (names($codex)) {
        if (lc($name) eq 'auth.json' || lc($name) eq 'installation_id') {
            $name eq 'auth.json' || $name eq 'installation_id' or fail();
        }
    }
    for my $name ('auth.json', 'installation_id') {
        my $s = present($codex . '/' . $name);
        !$s || (S_ISREG($s->[2]) && $s->[3] == 1 && $s->[4] == $<) or fail();
    }
}
sub clone {
    my ($from, $to) = @_;
    !present($to) or fail();
    # APFS clone is required; never fall back to a cross-volume full copy.
    capture('/bin/cp', '-c', '-Rp', filesystem_path($from), filesystem_path($to)) eq '' or fail();
}
closed();
my $plan_path = $root . '/plan.json';
my $ready_path = $root . '/ready.json';
my $done_path = $root . '/complete.json';
my $plan;
if (present($root)) { owned_directory($root, 0); }
if (present($plan_path)) {
    $plan = read_record($plan_path);
    exact_keys($plan, qw(format transaction current));
    $plan->{format} eq '1' && identical($plan->{transaction}, $record) &&
        ref($plan->{current}) eq 'ARRAY' && @{$plan->{current}} == @expected or fail();
    for my $s (@{$plan->{current}}) { valid_snapshot($s); }
} else {
    # No original can move without a durable plan AND ready record. Unknown
    # files in an uninitialized recovery directory are not silently adopted.
    if (present($root)) {
        for my $name (names($root)) {
            $name eq 'plan.json.pending-' . $id || $name eq 'incomplete' or fail();
        }
    }
    space(1);
    my @current;
    for my $item (@{$record->{scope}}) {
        if ($item->{original} eq $home . '/.codex') {
            identity_files($item->{original}); identity_files($item->{backup});
        }
        push @current, snapshot($item->{original});
    }
    $plan = {format => 1, transaction => $record, current => \@current};
    owned_directory($root, 1);
    save_recoverable($plan_path, $plan, $journal);
}
owned_directory($root . '/prepared', 1);
owned_directory($root . '/current', 1);
my $ready;
if (present($ready_path)) {
    $ready = read_record($ready_path);
    exact_keys($ready, qw(format plan desired));
    $ready->{format} eq '1' && identical($ready->{plan}, $plan) &&
        ref($ready->{desired}) eq 'ARRAY' && @{$ready->{desired}} == @expected or fail();
    for my $i (0..$#expected) {
        valid_snapshot($ready->{desired}[$i]);
        $ready->{desired}[$i]{existed} == $record->{scope}[$i]{existed} or fail();
    }
} else {
    space(1);
    !(names($root . '/current')) or fail();
    my @desired;
    for my $i (0..$#expected) {
        my $item = $record->{scope}[$i];
        verify_frozen($plan->{current}[$i], $item->{original});
        my $candidate = $root . '/prepared/' . $i;
        # A partial copy or identity overlay has no trusted final digest yet.
        # Retain it rather than trying to infer whether it finished.
        quarantine($candidate, $root . '/incomplete', $plan_path) if present($candidate);
        if ($item->{existed}) {
            clone($item->{backup}, $candidate);
            verify_frozen($item, $candidate);
            if ($item->{original} eq $home . '/.codex') {
                identity_files($item->{original}); identity_files($candidate);
                for my $name ('auth.json', 'installation_id') {
                    # An existing Codex directory with a missing identity can
                    # represent logout/reset. Preserve that absence too. Only
                    # a wholly absent current directory uses backup identity.
                    next unless present($item->{original});
                    my $current_identity = $item->{original} . '/' . $name;
                    my $to = $candidate . '/' . $name;
                    # Only this generated copy is replaced; never either Mac's
                    # original identity or the frozen destination backup.
                    if (present($to)) { unlink(filesystem_path($to)) or fail(); }
                    if (present($current_identity)) {
                        clone($current_identity, $to);
                        digest($current_identity) eq digest($to) or fail();
                    }
                }
            }
            flush_tree($candidate, $device); flush_parent($candidate);
        }
        push @desired, snapshot($candidate);
        verify_frozen($plan->{current}[$i], $item->{original});
    }
    $ready = {format => 1, plan => $plan, desired => \@desired};
    save_recoverable($ready_path, $ready, $plan_path);
}
# This check runs again after potentially long clone/hash/fsync work.
closed();
space(0);
save_recoverable($plan_path, $plan, $journal);
save_recoverable($ready_path, $ready, $plan_path);
# Validate ALL entries before moving any entry in this attempt. Every legal
# state derives from a durable ready record and no-replacement renames.
for my $i (0..$#expected) {
    my $original = $expected[$i];
    my $saved = $root . '/current/' . $i;
    my $prepared = $root . '/prepared/' . $i;
    my $old = $plan->{current}[$i];
    my $desired = $ready->{desired}[$i];
    directory(parent($original));
    present(parent($original))->[0] == $device or fail();
    if (present($saved)) {
        $old->{existed} or fail();
        verify_frozen($old, $saved);
    } elsif ($old->{existed}) {
        verify_frozen($old, $original);
        # If both old and desired exist, a missing prepared copy is ambiguous.
        !$desired->{existed} || present($prepared) or fail();
    }
    if (present($prepared)) {
        verify_frozen($desired, $prepared);
        (!present($saved) && $old->{existed}) || !present($original) or fail();
    } else {
        verify_frozen($desired, $original) unless $old->{existed} && !present($saved);
    }
}
for my $i (0..$#expected) {
    my $original = $expected[$i];
    my $saved = $root . '/current/' . $i;
    my $prepared = $root . '/prepared/' . $i;
    my $old = $plan->{current}[$i];
    my $desired = $ready->{desired}[$i];
    if ($old->{existed} && !present($saved)) {
        verify_frozen($old, $original);
        flush_tree($original, $device);
        move_new($original, $saved, $ready_path);
    }
    if (present($prepared)) {
        verify_frozen($desired, $prepared);
        move_new($prepared, $original, $ready_path);
    }
    verify_frozen($desired, $original);
    verify_frozen($old, $saved);
}
for my $i (0..$#expected) {
    verify_frozen($ready->{desired}[$i], $expected[$i]);
    verify_frozen($plan->{current}[$i], $root . '/current/' . $i);
    flush_tree($expected[$i], $device) if $ready->{desired}[$i]{existed};
    flush_parent($expected[$i]);
}
save_recoverable($done_path, $ready, $ready_path);
unlink(filesystem_path($journal)) or fail();
flush_parent($journal); barrier($done_path);
emit({status => 'restored', transaction_id => $id, restored_items => scalar(@expected),
      preserved => $root . '/current'});
'''


def restore_script(home, inspection):
    """Bind mutation to a previously inspected transaction and exact scope."""
    report = {k: v for k, v in inspection.items() if k != "message"}
    _validate_report(report, home)
    if report["status"] != "backup_verified":
        raise MigrationError("A verified pending backup is required before restoration")
    confirmation = {"transaction_id": report["transaction_id"], "backup": report["backup"],
                    "originals": [item["original"] for item in report["items"]]}
    args = ["restore", home, json.dumps(confirmation), require_codex_closed_script(home)]
    return ("/usr/bin/env -u PERL5OPT -u PERL5LIB -u PERLLIB -u PERLIO -u PERL_UNICODE "
            "LC_ALL=C /usr/bin/perl -e " + shlex.quote(RESTORE_RUNNER) + " -- "
            + " ".join(shlex.quote(a) for a in args) + "\n")


def restore_recovery(config, transport, inspection):
    """Internal explicit-apply entry point; no default/automatic restoration."""
    if not config.apply:
        raise MigrationError("Restoration requires explicit --apply authority")
    try:
        script = restore_script(config.target_home, inspection)
        result = transport.run_remote(script, timeout=24 * 60 * 60)
        if len(result.stdout) > 1048576:
            raise ValueError("Oversized restoration result")
        report = json.loads(result.stdout)
        expected = {"status": "restored", "transaction_id": inspection["transaction_id"],
                    "restored_items": len(inspection["items"]),
                    "preserved": inspection["backup"] + "/recovery-" + inspection["transaction_id"] + "/current"}
        if report != expected or type(report.get("restored_items")) is not int:
            raise ValueError("Restoration was not confirmed")
    except Exception as error:
        raise MigrationError("Restoration is not confirmed. Keep destination Codex closed and all "
                             "current files, staging, backups and recovery records intact. "
                             "Do not start another migration; check recovery or contact support.") from error
    return report
