"""Read-only reconciliation of one explicitly referenced restoration attempt."""

import json
import shlex

from codex_migrate.errors import MigrationError
from codex_migrate.recovery import RECOVERY_LOCK, validate_recovery_reference


RECONCILE_RUNNER = RECOVERY_LOCK + r'''
@ARGV == 3 && $mode eq 'reconcile' or fail();
my $reference = eval { JSON::PP->new->utf8->decode($ARGV[2]) };
!$@ or fail();
exact_keys($reference, qw(transaction_id backup originals));
my ($id, $backup) = @{$reference}{qw(transaction_id backup)};
!ref($id) && $id =~ /\A[0-9a-f]{32}\z/ or fail();
clean_path($backup);
$backup =~ m{\A\Q$home\E/[^/]+\z} or fail();
ref($reference->{originals}) eq 'ARRAY' && @{$reference->{originals}} > 0 &&
    @{$reference->{originals}} <= 10000 or fail();
sub summary {
    my ($status) = @_;
    emit({status => $status, inspected_items => 0});
}
my $pending;
if (present($journal)) {
    $pending = read_record($journal);
    # Do not inspect some other installation's backup because an old local
    # attempt was replayed. Malformed evidence never becomes a new identity.
    !ref($pending->{id}) && $pending->{id} =~ /\A[0-9a-f]{32}\z/ or fail();
    summary('different_transaction') if $pending->{id} ne $id;
    validate_transaction($pending, $home, $hs->[0]);
    my @originals = map { $_->{original} } @{$pending->{scope}};
    $pending->{backup} eq $backup && identical(\@originals, $reference->{originals}) or fail();
}
if (!present($backup)) { summary('restore_unconfirmed'); }
checked_recovery_directory($backup, $hs->[0]);
my $root = $backup . '/recovery-' . $id;
if (!present($root)) { summary($pending ? 'restore_incomplete' : 'restore_unconfirmed'); }
checked_recovery_directory($root, $hs->[0]);
my $plan_path = $root . '/plan.json';
my $ready_path = $root . '/ready.json';
my $complete_path = $root . '/complete.json';
if (!present($plan_path)) {
    !present($ready_path) && !present($complete_path) or fail();
    summary($pending ? 'restore_incomplete' : 'restore_unconfirmed');
}
my $plan = read_record($plan_path);
my $record = $plan->{transaction};
validate_transaction($record, $home, $hs->[0]);
validate_restore_plan($plan, $record);
my @originals = map { $_->{original} } @{$record->{scope}};
$record->{id} eq $id && $record->{backup} eq $backup &&
    identical(\@originals, $reference->{originals}) or fail();
!$pending || identical($pending, $record) or fail();
for my $item (@{$record->{scope}}) {
    !overlap($root, $item->{backup}) or fail();
    verify_frozen($item, $item->{backup});
}
if (!present($ready_path)) {
    !present($complete_path) or fail();
    summary($pending ? 'restore_incomplete' : 'restore_unconfirmed');
}
my $ready = read_record($ready_path);
validate_restore_ready($ready, $plan);
if (!present($complete_path)) {
    summary($pending ? 'restore_incomplete' : 'restore_unconfirmed');
}
identical(read_record($complete_path), $ready) or fail();
checked_recovery_directory($root . '/current', $hs->[0]);
checked_recovery_directory($root . '/prepared', $hs->[0]);
!(directory_entries($root . '/prepared')) or fail();
for my $name (directory_entries($root . '/current')) {
    $name =~ /\A(?:0|[1-9][0-9]*)\z/ && length($name) <= 5 && $name < @originals or fail();
}
sub matches {
    my ($expected, $path) = @_;
    directory(parent($path));
    my $s = present($path);
    if (!$expected->{existed}) { return !$s; }
    return 0 unless $s;
    $s->[0] == $hs->[0] or fail();
    return digest($path) eq $expected->{backup_digest};
}
my @items;
my $all_match = 1;
for my $i (0..$#originals) {
    my $original = $originals[$i];
    my $saved = $root . '/current/' . $i;
    my $restored_match = matches($ready->{desired}[$i], $original);
    my $preserved_match = matches($plan->{current}[$i], $saved);
    $all_match &&= $restored_match && $preserved_match;
    push @items, {original => $original, preserved => $saved,
        restored_expected => $ready->{desired}[$i]{existed},
        preserved_expected => $plan->{current}[$i]{existed},
        restored_present => present($original) ? JSON::PP::true : JSON::PP::false,
        preserved_present => present($saved) ? JSON::PP::true : JSON::PP::false,
        restored_matches => $restored_match ? JSON::PP::true : JSON::PP::false,
        preserved_matches => $preserved_match ? JSON::PP::true : JSON::PP::false};
}
# The kernel lock excludes other migration writers; also reject an unexpected
# manually changed journal instead of reporting a result for the wrong attempt.
if ($pending) { identical(read_record($journal), $pending) or fail(); }
else { !present($journal) or fail(); }
my $status = !$all_match ? 'restore_changed' : $pending ? 'restore_pending_cleanup' : 'restore_verified';
emit({status => $status, transaction_id => $id, backup => $backup,
      preserved => $root . '/current', inspected_items => scalar(@items),
      items => \@items, pending_cleanup => $pending ? JSON::PP::true : JSON::PP::false});
'''


MESSAGES = {
    "busy": "The destination is still in use. Wait, then check again; do not restart restoration or remove the lock.",
    "different_transaction": "Another unfinished installation is recorded on the destination. This saved restore attempt cannot resolve it. Keep all data and contact support.",
    "restore_incomplete": "Restoration is not confirmed complete. Its pending record remains. Keep destination Codex closed and preserve all current files, staging and backups.",
    "restore_unconfirmed": "No matching completed restoration could be verified. A missing pending record is not proof of success. Keep all data and contact support.",
    "restore_verified": "The saved completion record, restored entries and preserved current entries match. The previous destination has been restored; this does not complete the source migration or prove Codex usability.",
    "restore_pending_cleanup": "Restored and preserved entries match the completion record, but final recovery cleanup is still pending. Keep destination Codex closed; do not start another migration.",
    "restore_changed": "A restoration completion record exists, but some current or preserved entries have changed. No files were replaced. Keep the newer work and review it before proceeding.",
}
DETAILED_STATUSES = {"restore_verified", "restore_pending_cleanup", "restore_changed"}


def reconciliation_script(home, reference):
    validate_recovery_reference(reference, home)
    return ("/usr/bin/env -u PERL5OPT -u PERL5LIB -u PERLLIB -u PERLIO -u PERL_UNICODE "
            "LC_ALL=C /usr/bin/perl -e " + shlex.quote(RECONCILE_RUNNER) + " -- reconcile "
            + shlex.quote(home) + " " + shlex.quote(json.dumps(reference)) + "\n")


def _validate_result(report, reference):
    if not isinstance(report, dict) or report.get("status") not in MESSAGES:
        raise ValueError("Invalid reconciliation report")
    if report["status"] not in DETAILED_STATUSES:
        if set(report) != {"status", "inspected_items"} or type(report["inspected_items"]) is not int or report["inspected_items"] != 0:
            raise ValueError("Invalid reconciliation summary")
        return
    if set(report) != {"status", "transaction_id", "backup", "preserved", "inspected_items", "items", "pending_cleanup"}:
        raise ValueError("Invalid reconciliation fields")
    root = reference["backup"] + "/recovery-" + reference["transaction_id"]
    originals = reference["originals"]
    if (report["transaction_id"] != reference["transaction_id"] or report["backup"] != reference["backup"]
            or report["preserved"] != root + "/current" or type(report["pending_cleanup"]) is not bool
            or type(report["inspected_items"]) is not int or report["inspected_items"] != len(originals)
            or not isinstance(report["items"], list) or len(report["items"]) != len(originals)):
        raise ValueError("Mismatched reconciliation identity")
    all_match = True
    for index, item in enumerate(report["items"]):
        if (not isinstance(item, dict) or set(item) != {"original", "preserved", "restored_expected", "preserved_expected", "restored_present", "preserved_present", "restored_matches", "preserved_matches"}
                or item["original"] != originals[index] or item["preserved"] != root + "/current/" + str(index)
                or any(type(item[key]) is not bool for key in ("restored_expected", "preserved_expected", "restored_present", "preserved_present", "restored_matches", "preserved_matches"))):
            raise ValueError("Invalid reconciliation item")
        for prefix in ("restored", "preserved"):
            if item[prefix + "_matches"] and item[prefix + "_present"] != item[prefix + "_expected"]:
                raise ValueError("Inconsistent entry presence")
        all_match = all_match and item["restored_matches"] and item["preserved_matches"]
    expected = "restore_changed" if not all_match else "restore_pending_cleanup" if report["pending_cleanup"] else "restore_verified"
    if report["status"] != expected:
        raise ValueError("Inconsistent reconciliation outcome")


def reconcile_recovery(config, transport, reference, cancelled=None):
    """Read-only even with --apply; never retries restoration or clears evidence."""
    try:
        script = reconciliation_script(config.target_home, reference)
        if cancelled is None:
            result = transport.run_remote(script, timeout=24 * 60 * 60)
        else:
            result = transport.run_remote_cancellable(script, 24 * 60 * 60, cancelled)
        if len(result.stdout) > 1048576:
            raise ValueError("Oversized reconciliation report")
        report = json.loads(result.stdout)
        _validate_result(report, reference)
    except Exception as error:
        raise MigrationError("The restoration outcome could not be verified. No reconciliation "
                             "changes were made. Keep destination Codex closed and all current files, "
                             "staging, backups and records intact; contact support.") from error
    report["message"] = MESSAGES[report["status"]]
    return report
