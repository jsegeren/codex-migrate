"""Checked home-path compatibility; privileged creation is manual and exclusive."""

import json
import re
import shlex
from datetime import datetime, timezone


# No file contents are inspected. The account query is bounded, stays on the
# destination, and returns no account records to the caller. The same checks
# run again inside the manually invoked command, immediately before symlink().
RUNNER = r'''
use strict; use warnings;
use JSON::PP; use Fcntl qw(:mode); use Cwd qw(realpath);
use Encode qw(encode decode FB_CROAK LEAVE_SRC);
use Unicode::Normalize qw(NFD); use feature 'fc';
sub fail { die "Home-path compatibility could not be safely checked. No existing path was replaced.\n"; }
sub emit { print JSON::PP->new->canonical->encode({status => $_[0]}), "\n" or fail(); exit 0; }
my ($mode, $old, $new, $user) = @ARGV;
($mode eq 'inspect' && @ARGV == 4 || $mode eq 'create' && @ARGV == 5 && $ARGV[4] eq '--apply') or fail();
($old, $new) = map { decode('UTF-8', $_, FB_CROAK) } ($old, $new);
sub fs { return encode('UTF-8', $_[0], FB_CROAK | LEAVE_SRC); }
sub text_path { return decode('UTF-8', $_[0], FB_CROAK | LEAVE_SRC); }
my $users_root = '/Users';
sub supported {
    my ($p) = @_;
    return defined($p) && $p =~ m{\A\Q$users_root\E/[^/\r\n\0]+\z} &&
        $p ne "$users_root/." && $p ne "$users_root/.." && fc(NFD($p)) ne fc(NFD("$users_root/Shared"));
}
supported($old) && supported($new) or emit('unsupported');
my @parent = lstat($users_root);
@parent && S_ISDIR($parent[2]) && $parent[4] == 0 && !($parent[2] & 0002) or fail();
my @home = lstat(fs($new));
@home && S_ISDIR($home[2]) && $home[4] != 0 && text_path(realpath(fs($new))) eq $new or fail();
if ($mode eq 'inspect') { $< == $> && $< == $home[4] or fail(); }
else { $< == 0 && $> == 0 or fail(); }
$user =~ /\A[A-Za-z_][A-Za-z0-9._-]*\z/ or fail();
my $account_json = '';
open(my $accounts, '-|', '/bin/zsh', '-f', '-c',
    'set -o pipefail; /usr/bin/dscl -plist . -readall /Users NFSHomeDirectory UniqueID 2>/dev/null | /usr/bin/plutil -convert json -o - -- - 2>/dev/null') or fail();
while (1) {
    my $count = read($accounts, my $chunk, 8192);
    defined($count) or fail(); last unless $count;
    $account_json .= $chunk; length($account_json) <= 1048576 or fail();
}
close($accounts) or fail();
my $records = eval { JSON::PP->new->utf8->decode($account_json) };
!$@ && ref($records) eq 'ARRAY' && @$records > 0 or fail();
my ($found, $claimed) = (0, 0);
for my $record (@$records) {
    ref($record) eq 'HASH' or fail();
    my $uids = $record->{'dsAttrTypeStandard:UniqueID'};
    my $names = $record->{'dsAttrTypeStandard:RecordName'};
    my $homes = $record->{'dsAttrTypeStandard:NFSHomeDirectory'} || [];
    ref($uids) eq 'ARRAY' && @$uids == 1 && !ref($uids->[0]) && $uids->[0] =~ /\A-?[0-9]+\z/ &&
        ref($names) eq 'ARRAY' && @$names > 0 && ref($homes) eq 'ARRAY' or fail();
    for my $name (@$names) { defined($name) && !ref($name) or fail(); }
    for my $path (@$homes) {
        defined($path) && !ref($path) or fail();
        $found = 1 if $uids->[0] == $home[4] && $path eq $new && grep { $_ eq $user } @$names;
        $claimed = 1 if fc(NFD($path)) eq fc(NFD($old)) && $uids->[0] != $home[4];
    }
}
$found or fail();
$claimed and emit('conflict');
$old eq $new and emit('not_needed');
my @entry = lstat(fs($old));
if (@entry) {
    # Accept only a direct, literal alias owned by root/the destination owner.
    # Wrong, chained, dangling and cyclic aliases are never followed or fixed.
    if (S_ISLNK($entry[2]) && ($entry[4] == 0 || $entry[4] == $home[4]) && text_path(readlink(fs($old))) eq $new) {
        my @resolved = stat(fs($old));
        @resolved && $resolved[0] == $home[0] && $resolved[1] == $home[1] or fail();
        emit('mapped');
    }
    emit('conflict');
}
$!{ENOENT} or fail();
$mode eq 'inspect' and emit('missing');
# Exact-path syscall: EEXIST fails even if a directory/link appears after the
# check. Never use ln's directory-destination behavior or replace an entry.
symlink(fs($new), fs($old)) or fail();
text_path(readlink(fs($old))) eq $new or fail();
my @resolved = stat(fs($old));
@resolved && $resolved[0] == $home[0] && $resolved[1] == $home[1] or fail();
emit('mapped');
'''

MESSAGES = {
    "not_needed": "Both Macs use the same home path. No compatibility link is needed.",
    "mapped": "The old home path points directly to the new home. This point-in-time check does not prove every chat or repository works.",
    "missing": "The old home path is missing on the new Mac. Review the compatibility command, run it there, then check paths again.",
    "conflict": "The old home path is occupied or claimed by another local account. Nothing was replaced. Contact support; do not delete or rename that path to force migration.",
    "unsupported": "Automatic compatibility guidance supports ordinary /Users/name homes only. This home layout needs review before migration.",
    "unverified": "Home-path compatibility could not be verified. Keep existing files and the installation receipt intact, then check again or contact support.",
}
READY = {"not_needed", "mapped"}


def _command(config, mode):
    return ("/usr/bin/env -u PERL5OPT -u PERL5LIB -u PERLLIB -u PERLIO -u PERL_UNICODE "
            "LC_ALL=C /usr/bin/perl -e " + shlex.quote(RUNNER) + " -- "
            + " ".join(shlex.quote(value) for value in
                       (mode, config.source_home, config.target_home, config.target.split("@", 1)[0]))
            + (" --apply" if mode == "create" else ""))


def check_compatibility(config, transport, cancelled=None):
    try:
        if cancelled is None:
            result = transport.run_remote(_command(config, "inspect"), timeout=30)
        else:
            result = transport.run_remote_cancellable(_command(config, "inspect"), 30, cancelled)
        if len(result.stdout) > 1024:
            raise ValueError("Oversized path report")
        report = json.loads(result.stdout)
        if not isinstance(report, dict) or set(report) != {"status"} or report["status"] not in MESSAGES:
            raise ValueError("Invalid path report")
        status = report["status"]
    except Exception:
        status = "unverified"
    return {"status": status, "message": MESSAGES[status],
            "source_home": config.source_home, "target_home": config.target_home,
            "checked_at": datetime.now(timezone.utc).isoformat()}


def compatibility_command(config, report):
    if not isinstance(report, dict) or report.get("status") != "missing":
        return None
    if report.get("source_home") != config.source_home or report.get("target_home") != config.target_home:
        return None
    for path in (config.source_home, config.target_home):
        if not re.fullmatch(r"/Users/[^/\r\n\0]+", path) or path.rsplit("/", 1)[-1].casefold() in (".", "..", "shared"):
            return None
    if config.source_home == config.target_home:
        return None
    return "sudo " + _command(config, "create")
