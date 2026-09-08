"""Narrow destination-backup exception for disposable Codex IPC endpoints.

Never applied to incoming source data or the saved recovery backup. macOS cp
does not clone sockets; an endpoint has no restorable process or file contents.
"""

from codex_migrate.tree_digest import PERL_IMPORTS, TREE_FUNCTIONS


# Only actual sockets in known Codex runtime locations qualify. A regular file,
# link, directory, pipe, or a socket inside a worktree is never filtered here.
# The containing directories and all their ordinary files are still checked.
SOCKET_EXCLUSION = r'''
our $cm_ignore_codex_runtime_sockets = 0;
sub excluded {
    my ($relative, $path) = @_;
    return 0 unless $cm_ignore_codex_runtime_sockets;
    return 0 unless $relative =~ m{\A(?:[^/]+\.(?:sock|socket)|fsmonitor--daemon\.ipc)\z}
        || $relative =~ m{\A(?:ipc|thread-writer-locks|process_manager|mcp-oauth-locks|node_repl|\.tmp|tmp)/};
    my @s = lstat($path);
    die unless @s;
    return S_ISSOCK($s[2]);
}
'''

CODEX_BACKUP_RUNNER = PERL_IMPORTS + SOCKET_EXCLUSION + r'''
my $codex_mode = 0;
sub validate_names { return; }
$SIG{__WARN__} = sub { exit 73; };
$SIG{__DIE__} = sub { exit 73; };
''' + TREE_FUNCTIONS + r'''
@ARGV == 2 or exit 73;
for my $root (@ARGV) {
    my @s = lstat($root);
    @s && S_ISDIR($s[2]) or exit 73;
}
my $original;
{
    local $cm_ignore_codex_runtime_sockets = 1;
    $original = tree($ARGV[0], '');
}
# The backup itself has no exclusions. Extra/mistyped entries still fail.
$original eq tree($ARGV[1], '') or exit 73;
'''
