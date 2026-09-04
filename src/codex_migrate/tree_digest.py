"""Shared, byte-framed Perl tree digest; callers supply filtering and errors."""

PERL_IMPORTS = "use strict; use warnings; use Digest::SHA; use Time::HiRes (); use Fcntl qw(:DEFAULT :mode);"

# Names and link text are filesystem bytes. Absolute roots, owners, timestamps,
# ACLs, xattrs and hard-link topology are deliberately not part of the digest.
# Callers define $codex_mode and excluded(). Recovery always disables filtering.
TREE_FUNCTIONS = r'''
{
use bytes;
sub information {
    my ($path) = @_;
    my @s = Time::HiRes::lstat($path);
    die unless @s;
    return \@s;
}
sub stable {
    my ($a, $b) = @_;
    die unless @$b;
    for my $index (0, 1, 2, 3, 7, 9, 10) { die unless $a->[$index] == $b->[$index]; }
}
sub field {
    my ($sha, $value) = @_;
    $sha->add(pack('N', length($value)), $value);
}
sub tree {
    my ($path, $relative) = @_;
    my $before = information($path);
    my $sha = Digest::SHA->new(256);
    field($sha, $codex_mode ? 'codex-migrate-retained-state-v1' : 'codex-migrate-tree-v1');
    if (S_ISLNK($before->[2])) {
        my $value = readlink($path);
        die unless defined $value;
        field($sha, 'link'); field($sha, $value);
        die unless readlink($path) eq $value;
    } elsif (S_ISDIR($before->[2])) {
        field($sha, 'directory');
        field($sha, sprintf('%04o', $before->[2] & 07777)) unless $codex_mode && $relative eq '';
        opendir(my $directory, $path) or die;
        $! = 0;
        my @names = sort grep { $_ ne '.' && $_ ne '..' } readdir($directory);
        die if $!;
        closedir($directory) or die;
        for my $name (@names) {
            my $child = $relative eq '' ? $name : $relative . '/' . $name;
            next if excluded($child, $path . '/' . $name);
            field($sha, $name); field($sha, tree($path . '/' . $name, $child));
        }
    } elsif (S_ISREG($before->[2])) {
        sysopen(my $file, $path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK) or die;
        binmode($file) or die;
        my @opened = Time::HiRes::stat($file);
        stable($before, \@opened);
        die unless S_ISREG($opened[2]);
        my $content = Digest::SHA->new(256);
        my $total = 0;
        while (1) {
            my $read = sysread($file, my $buffer, 1048576);
            die unless defined $read;
            last unless $read;
            $content->add($buffer); $total += $read;
        }
        my @after = Time::HiRes::stat($file);
        stable($before, \@after);
        die unless $total == $before->[7];
        close($file) or die;
        field($sha, 'file'); field($sha, sprintf('%04o', $before->[2] & 07777));
        field($sha, $content->digest);
    } else { die; }
    stable($before, information($path));
    return $sha->digest;
}
}
'''
