"""Read-only Git probe primitive; a report alone is not an installation receipt.

One system-Perl runner can be used locally or through the strict SSH transport.
Raw Git output stays in bounded pipes and is never included in the report.
"""

import json
import re
import shlex
import subprocess
import time

from codex_migrate.errors import MigrationError
from codex_migrate.transport import _stop_process


PROBE_TIMEOUT = 3600
MESSAGE = "Git could not be checked safely. Existing files were not changed; keep your backup and contact support."

RUNNER = r'''
use strict;
use warnings;
use Cwd qw(abs_path);
use Digest::SHA qw(sha256_hex);
use Encode ();
use Errno qw(ENOENT);
use Fcntl qw(:mode);
use IO::Select;
use IPC::Open3;
use JSON::PP;
use POSIX qw(WNOHANG);
use Symbol qw(gensym);
use Time::HiRes qw(time);
use Unicode::Normalize ();
use feature 'fc';

sub fail { die "CM_GIT_PROBE\n"; }
sub inside { my ($p, $r) = @_; return $p eq $r || index($p, "$r/") == 0; }
sub path_key {
    my $text = Encode::decode('UTF-8', $_[0], Encode::FB_CROAK | Encode::LEAVE_SRC);
    return Unicode::Normalize::NFD(fc(Unicode::Normalize::NFD($text)));
}
sub overlaps {
    my ($a, $b) = map { path_key($_) } @_;
    return inside($a, $b) || inside($b, $a);
}
sub path {
    my ($p) = @_;
    fail() if ref($p) || !defined($p) || $p !~ m{\A/} || $p =~ /[\x00-\x1f\x7f]/;
    return Encode::encode('UTF-8', $p, Encode::FB_CROAK | Encode::LEAVE_SRC);
}
sub sb {
    my $text = Encode::decode('UTF-8', $_[0], Encode::FB_CROAK | Encode::LEAVE_SRC);
    return JSON::PP->new->utf8->encode($text);
}
sub execute {
    my (@command) = @_;
    my ($out, $err) = (gensym, gensym);
    my $pid = open3(undef, $out, $err, @command);
    my $reader = IO::Select->new($out, $err);
    my $stdout = '';
    my $stderr = 0;
    my $deadline = time() + 300;
    my $stdout_fd = fileno($out);
    my $exit;
    my $ok = eval {
        while ($reader->count) {
            fail() if time() > $deadline;
            for my $stream ($reader->can_read(0.2)) {
                my $n = sysread($stream, my $buffer, 65536);
                fail() unless defined $n;
                if (!$n) { $reader->remove($stream); close($stream) or fail(); next; }
                if (fileno($stream) == $stdout_fd) { $stdout .= $buffer; }
                else { $stderr += $n; }
                fail() if length($stdout) > 33554432 || $stderr > 1048576;
            }
        }
        while (1) {
            my $done = waitpid($pid, WNOHANG);
            if ($done == $pid) { $exit = $?; last; }
            fail() if $done == -1 || time() > $deadline;
            Time::HiRes::sleep(0.05);
        }
        1;
    };
    if (!$ok) { kill 'KILL', $pid; waitpid($pid, 0); fail(); }
    return ($exit >> 8, $stdout, $stderr, $exit & 127);
}
sub require_result {
    my ($code, $out, $errors, $signal) = @_;
    fail() if $code || $errors || $signal;
    return $out;
}

my $result;
my $ok = eval {
    local $SIG{__WARN__} = sub { fail(); };
    fail() unless @ARGV == 1 && length($ARGV[0]) < 1048576;
    my $input = JSON::PP->new->utf8->decode($ARGV[0]);
    fail() unless ref($input) eq 'HASH' && ref($input->{roots}) eq 'ARRAY'
        && ref($input->{repositories}) eq 'ARRAY' && @{$input->{roots}} <= 1000
        && @{$input->{repositories}} <= 10000;
    my $home = path($input->{home});
    my @home_info = lstat($home);
    fail() unless @home_info && S_ISDIR($home_info[2]) && $home_info[4] == $<
        && $< == $> && $< != 0 && abs_path($home) eq $home;
    my @roots;
    my %protected;
    my @protected_paths = ("$home/.ssh", "$home/.codex/auth.json", "$home/.codex/installation_id");
    for my $p ("$home/.ssh", "$home/.codex/auth.json", "$home/.codex/installation_id") {
        my $resolved = abs_path($p);
        push @protected_paths, $resolved if defined($resolved) && $resolved ne $p;
    }
    for my $name ('auth.json', 'installation_id') {
        my @s = stat("$home/.codex/$name");
        fail() unless @s || $! == ENOENT;
        $protected{"$s[0]:$s[1]"} = 1 if @s;
    }
    for my $value (@{$input->{roots}}) {
        my $root = path($value);
        my @s = lstat($root);
        fail() unless @s && S_ISDIR($s[2]) && abs_path($root) eq $root
            && inside($root, $home) && $root ne $home;
        fail() if grep { overlaps($root, $_) } @protected_paths;
        push @roots, $root;
        # Metadata only. A tracked hard link must not disguise Codex identity
        # material as an ordinary file that status would then open.
        my @pending = ($root);
        while (@pending) {
            my $p = pop @pending;
            my @i = lstat($p);
            fail() unless @i;
            fail() if $protected{"$i[0]:$i[1]"};
            next unless S_ISDIR($i[2]);
            opendir(my $dir, $p) or fail();
            while (1) {
                $! = 0;
                my $name = readdir($dir);
                if (!defined $name) { fail() if $!; last; }
                push @pending, "$p/$name" unless $name eq '.' || $name eq '..';
            }
            closedir($dir) or fail();
        }
    }
    %ENV = (PATH => '/usr/bin:/bin:/usr/sbin:/sbin', HOME => '/var/empty',
        LC_ALL => 'C', GIT_CONFIG_NOSYSTEM => '1', GIT_CONFIG_GLOBAL => '/dev/null',
        GIT_ATTR_NOSYSTEM => '1', GIT_OPTIONAL_LOCKS => '0', GIT_NO_LAZY_FETCH => '1',
        GIT_NO_REPLACE_OBJECTS => '1', GIT_TERMINAL_PROMPT => '0', GIT_PAGER => 'cat');
    my $git = require_result(execute('/usr/bin/xcrun', '--find', 'git'));
    $git =~ s/\n\z//;
    fail() unless $git =~ m{\A/(?:Applications/[^\n]+\.app/Contents/Developer|Library/Developer/CommandLineTools)/usr/bin/git\z};
    my @g = lstat($git);
    fail() unless @g && S_ISREG($g[2]) && $g[4] == 0 && !($g[2] & 0022)
        && abs_path($git) eq $git;
    my $toolchain = $git; $toolchain =~ s{/usr/bin/git\z}{};
    for my $runtime ('/System', '/usr/lib', '/usr/share', '/Library/Apple', $toolchain) {
        fail() if overlaps($home, $runtime) || grep { overlaps($_, $runtime) } @protected_paths;
    }
    my $profile = '(version 1)(deny default)(allow file-read-metadata)'
        . '(allow file-read-data (literal "/"))'
        . '(allow sysctl-read)(allow mach-lookup)'
        . '(allow file-write* (literal "/dev/null"))'
        . '(allow process-exec (literal ' . sb($git) . '))'
        . '(allow file-read-data (subpath "/System") (subpath "/usr/lib")'
        . ' (subpath "/usr/share") (subpath "/Library/Apple")'
        . ' (literal "/dev/null") (literal "/dev/urandom")'
        . ' (literal "/private/etc/localtime") (subpath ' . sb($toolchain) . '))';
    for my $root (@roots) { $profile .= '(allow file-read-data (subpath ' . sb($root) . '))'; }
    my @base = ('/usr/bin/sandbox-exec', '-p', $profile, $git,
        '--no-pager', '--no-optional-locks', '--no-lazy-fetch', '--literal-pathspecs',
        '-c', 'core.fsmonitor=false', '-c', 'core.untrackedCache=false',
        '-c', 'core.hooksPath=/dev/null', '-c', 'core.attributesFile=/dev/null',
        '-c', 'core.excludesFile=/dev/null', '-c', 'core.commitGraph=false',
        '-c', 'core.multiPackIndex=false', '-c', 'maintenance.auto=false',
        '-c', 'gc.auto=0', '-c', 'color.ui=false', '-c', 'status.renames=false',
        '-c', 'diff.renames=false', '-c', 'submodule.recurse=false');
    my $version = require_result(execute(@base, '--version'));
    fail() unless $version =~ /\Agit version ([0-9]+\.[0-9]+\.[0-9]+)(?: \(Apple Git-[0-9]+\))?\n\z/;
    $result = {format => 1, git_version => $1, repositories => []};
    for my $repo (@{$input->{repositories}}) {
        fail() unless ref($repo) eq 'HASH' && defined($repo->{kind})
            && $repo->{kind} =~ /\A(?:checkout|linked|storage)\z/;
        my $root = path($repo->{path});
        my $expected_git = path($repo->{git_dir});
        fail() unless grep { inside($root, $_) } @roots;
        fail() unless grep { inside($expected_git, $_) } @roots;
        fail() unless abs_path($root) eq $root && abs_path($expected_git) eq $expected_git;
        my @cmd = (@base, '-C', $root);
        my $row = {status => 'needs_review', reason => 'check_failed', checks => {}};
        push @{$result->{repositories}}, $row;
        my $checked = eval {
            my $actual = require_result(execute(@cmd, 'rev-parse', '--absolute-git-dir'));
            $actual =~ s/\n\z//;
            fail() unless defined(abs_path($actual)) && abs_path($actual) eq $expected_git;
            my $common = require_result(execute(@cmd, 'rev-parse', '--path-format=absolute', '--git-common-dir'));
            $common =~ s/\n\z//;
            my $resolved_common = abs_path($common);
            fail() unless defined($resolved_common) && grep { inside($resolved_common, $_) } @roots;
            my $bare = require_result(execute(@cmd, 'rev-parse', '--is-bare-repository'));
            fail() unless $bare eq "true\n" || $bare eq "false\n";
            if ($bare eq "false\n") {
                my $top = require_result(execute(@cmd, 'rev-parse', '--show-toplevel'));
                $top =~ s/\n\z//;
                fail() unless defined(abs_path($top)) && abs_path($top) eq $root;
            }
            my ($partial_code, $partial, $partial_errors, $partial_signal) = execute(@cmd,
                'config', '--includes', '--get-regexp', '^(extensions\.partialclone|remote\..*\.promisor|fsck\.)');
            fail() if $partial_errors || $partial_signal || ($partial_code != 0 && $partial_code != 1);
            if (length($partial)) { $row->{reason} = 'custom_object_policy'; fail(); }
            my $shallow = require_result(execute(@cmd, 'rev-parse', '--is-shallow-repository'));
            fail() unless $shallow eq "false\n" || $shallow eq "true\n";
            $row->{history_scope} = $shallow eq "true\n" ? 'shallow' : 'local';
            my ($head_code, $head, $head_errors, $head_signal) = execute(@cmd, 'symbolic-ref', '-q', 'HEAD');
            fail() if $head_errors || $head_signal || ($head_code != 0 && $head_code != 1);
            my ($refs_code, $refs, $refs_errors, $refs_signal) = execute(@cmd, 'show-ref', '--head', '--dereference');
            fail() if $refs_errors || $refs_signal || ($refs_code != 0 && $refs_code != 1);
            $row->{checks}{head} = sha256_hex($head_code . ':' . $head);
            $row->{checks}{refs} = sha256_hex($refs);
            if ($bare eq "false\n") {
                $row->{checks}{index} = sha256_hex(require_result(execute(@cmd, 'ls-files', '--stage', '-z')));
                $row->{checks}{status} = sha256_hex(require_result(execute(@cmd, 'status',
                    '--porcelain=v1', '-z', '--untracked-files=all', '--ignore-submodules=all')));
            }
            require_result(execute(@cmd, 'fsck', '--full', '--strict', '--no-dangling',
                '--no-progress', '--no-references'));
            $row->{status} = 'checked'; $row->{reason} = 'none';
            $row->{bare} = $bare eq "true\n" ? JSON::PP::true : JSON::PP::false;
            1;
        };
        if (!$checked) { $row->{checks} = {}; }
    }
    1;
};
if (!$ok) { print STDERR "Git could not be checked safely. No Git output is included.\n"; exit 79; }
print JSON::PP->new->canonical->utf8->encode($result), "\n" or exit 79;
'''


def probe_command(home, roots, repositories):
    try:
        payload = json.dumps({"home": home, "roots": roots, "repositories": repositories}, ensure_ascii=False)
        if len(payload.encode("utf-8")) > 128 * 1024:
            raise ValueError()
    except (ValueError, TypeError, UnicodeError) as error:
        raise MigrationError(MESSAGE) from error
    return ["/usr/bin/env", "-i", "PATH=/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL=C",
            "/usr/bin/perl", "-e", RUNNER, "--", payload]


def probe_script(home, roots, repositories):
    return " ".join(shlex.quote(value) for value in probe_command(home, roots, repositories)) + "\n"


def probe_local(home, roots, repositories, checkpoint=lambda: None):
    checkpoint()
    command = probe_command(home, roots, repositories)
    try:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, start_new_session=True,
                                   env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C"})
    except OSError as error:
        raise MigrationError(MESSAGE) from error
    deadline = time.monotonic() + PROBE_TIMEOUT
    try:
        while True:
            checkpoint()
            if time.monotonic() > deadline:
                raise MigrationError(MESSAGE)
            try:
                output, _ = process.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                continue
        checkpoint()
        if process.returncode:
            raise MigrationError(MESSAGE)
        return parse_report(output, len(repositories))
    except BaseException:
        _stop_process(process)
        raise


def parse_report(output, count):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError()
            result[key] = value
        return result
    try:
        if len(output) > 8 * 1024 * 1024:
            raise ValueError()
        report = json.loads(output, object_pairs_hook=unique_object)
        if (not isinstance(report, dict) or set(report) != {"format", "git_version", "repositories"}
                or type(report["format"]) is not int or report["format"] != 1
                or not isinstance(report["git_version"], str)
                or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", report["git_version"])):
            raise ValueError()
        if not isinstance(report["repositories"], list) or len(report["repositories"]) != count:
            raise ValueError()
        for row in report["repositories"]:
            if not isinstance(row, dict) or set(row) - {"status", "reason", "checks", "bare", "history_scope"}:
                raise ValueError()
            if row["status"] not in ("checked", "needs_review") or row["reason"] not in ("none", "check_failed", "custom_object_policy"):
                raise ValueError()
            checks = row["checks"]
            if not isinstance(checks, dict) or set(checks) - {"head", "refs", "index", "status"}:
                raise ValueError()
            if any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in checks.values()):
                raise ValueError()
            if row["status"] == "checked":
                expected = {"head", "refs"} if row.get("bare") is True else {"head", "refs", "index", "status"}
                if row["reason"] != "none" or set(checks) != expected or type(row.get("bare")) is not bool or row.get("history_scope") not in ("local", "shallow"):
                    raise ValueError()
            elif checks or row["reason"] == "none" or "bare" in row:
                raise ValueError()
            if "history_scope" in row and row["history_scope"] not in ("local", "shallow"):
                raise ValueError()
        return report
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise MigrationError(MESSAGE) from error
