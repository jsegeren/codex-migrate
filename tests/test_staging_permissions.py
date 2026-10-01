"""Actual Perl/rsync on disposable trees only; no SSH or customer data."""

import os
from pathlib import Path
import platform
import select
import signal
import subprocess
import sys
import tempfile
import unittest

from codex_migrate.destination_lock import locked_destination_script
from codex_migrate.staging_permissions import staging_permissions_script, transfer_staged
from codex_migrate.transport import TransferProcess, TransportError, rsync_phase_options
from codex_migrate.workspaces import freeze_tree


@unittest.skipUnless(platform.system() == 'Darwin', 'macOS system Perl and rsync')
class StagingPermissionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.home = self.base / "new person's home"
        self.staging = self.home / 'Codex-Migrate-Staging'
        self.selected = self.staging / 'home-relative' / 'Git repo'
        self.selected.mkdir(parents=True)
        self.staging.chmod(0o700)
        self.migration_id = 'a' * 32
        self.marker = self.staging / '.codex-migrate-owner'
        self.marker.write_text(self.migration_id + '\n')
        self.marker.chmod(0o600)
        self.file = self.selected / 'read only'
        self.file.write_bytes(b'disposable fixture')
        self.file.chmod(0o444)
        self.outside = self.base / 'not staging'
        self.outside.mkdir()
        self.victim = self.outside / 'keep mode and content'
        self.victim.write_bytes(b'outside fixture')
        self.victim.chmod(0o444)

    def script(self, writable=False, selected=None):
        return staging_permissions_script(str(self.home), str(self.staging),
                                          str(selected or self.selected), self.migration_id,
                                          writable=writable)

    def run_script(self, writable=False, script=None, selected=None):
        return subprocess.run(['/bin/zsh', '-f', '-s'],
                              input=script or self.script(writable, selected),
                              text=True, capture_output=True, timeout=10)

    def mode(self, file=None):
        return (file or self.file).stat().st_mode & 0o7777

    def refused(self, result):
        self.assertEqual(result.returncode, 74, result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertIn('Keep staging and backups intact', result.stderr)
        self.assertNotIn('disposable fixture', result.stderr)
        self.assertEqual(self.mode(), 0o444)
        self.assertEqual(self.mode(self.victim), 0o444)
        self.assertEqual(self.victim.read_bytes(), b'outside fixture')

    def test_validation_is_read_only_and_writable_uses_filehandle(self):
        self.file.chmod(0o450)
        self.assertEqual(self.run_script().returncode, 0)
        self.assertEqual(self.mode(), 0o450)
        result = self.run_script(writable=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.mode(), 0o650)
        self.assertEqual(self.file.read_bytes(), b'disposable fixture')
        self.assertEqual(self.marker.stat().st_mode & 0o7777, 0o600)
        self.assertEqual(self.mode(self.victim), 0o444)
        # The final archive pass has not run; this is resumable, not complete.
        self.assertEqual(self.run_script().returncode, 0)

    def test_symlink_files_and_directories_are_inert(self):
        (self.selected / 'file alias').symlink_to(self.victim)
        (self.selected / 'directory alias').symlink_to(self.outside)
        (self.selected / 'broken alias').symlink_to(self.outside / 'absent')
        before = [os.readlink(self.selected / name)
                  for name in ('file alias', 'directory alias', 'broken alias')]
        result = self.run_script(writable=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.mode(self.victim), 0o444)
        self.assertEqual(before, [os.readlink(self.selected / name)
                                 for name in ('file alias', 'directory alias', 'broken alias')])

    def test_hardlink_to_outside_refuses_before_any_permission_changes(self):
        os.link(self.victim, self.selected / 'hard link')
        self.refused(self.run_script(writable=True))

    def test_internal_hardlink_also_refuses(self):
        os.link(self.file, self.selected / 'other name')
        self.refused(self.run_script(writable=True))

    def test_fifo_refuses_without_hanging_or_mutating_any_file(self):
        os.mkfifo(self.selected / 'pipe')
        self.refused(self.run_script(writable=True))

    def test_socket_refuses_without_permission_changes(self):
        # A relative bind avoids macOS's short sockaddr_un path limit.
        subprocess.run([sys.executable, '-c',
                        'import socket; s = socket.socket(socket.AF_UNIX); s.bind("socket"); s.close()'],
                       cwd=self.selected, check=True, timeout=5)
        self.refused(self.run_script(writable=True))

    def test_linked_selected_root_refuses(self):
        alias = self.staging / 'outside alias'
        alias.symlink_to(self.outside)
        self.refused(self.run_script(writable=True, selected=alias))

    def test_linked_intermediate_ancestor_refuses(self):
        alias = self.staging / 'intermediate alias'
        alias.symlink_to(self.outside)
        self.refused(self.run_script(writable=True, selected=alias / 'child'))

    def test_missing_subtree_is_valid_only_for_pre_copy_validation(self):
        missing = self.staging / 'not yet copied' / 'child'
        self.assertEqual(self.run_script(selected=missing).returncode, 0)
        self.assertFalse(missing.parent.exists())
        self.refused(self.run_script(writable=True, selected=missing))
        strict = staging_permissions_script(str(self.home), str(self.staging),
                                             str(missing), self.migration_id, allow_absent=False)
        self.refused(self.run_script(script=strict))

    def test_bad_markers_refuse_before_mutation(self):
        for content in ('b' * 32 + '\n', 'a' * 32, 'a' * 32 + '\nextra', 'private-fixture'):
            with self.subTest(content_length=len(content)):
                self.marker.write_text(content)
                self.refused(self.run_script(writable=True))
        self.marker.write_text(self.migration_id + '\n')
        self.marker.chmod(0o644)
        self.refused(self.run_script(writable=True))

    def test_marker_link_and_hardlink_are_rejected(self):
        self.marker.unlink()
        self.marker.symlink_to(self.victim)
        self.refused(self.run_script(writable=True))
        self.marker.unlink()
        marker_copy = self.outside / 'marker copy'
        marker_copy.write_text(self.migration_id + '\n')
        marker_copy.chmod(0o600)
        os.link(marker_copy, self.marker)
        self.refused(self.run_script(writable=True))

    def test_private_staging_root_is_required(self):
        self.staging.chmod(0o755)
        self.refused(self.run_script(writable=True))

    def test_limits_refuse_static_tree_before_any_mutation(self):
        (self.selected / 'second file').write_bytes(b'fixture')
        self.refused(self.run_script(script=self.script(True).replace('2000000', '1')))
        child = self.selected / 'nested'
        child.mkdir()
        (child / 'file').write_bytes(b'fixture')
        self.refused(self.run_script(script=self.script(True).replace('$depth <= 128', '$depth <= 0')))

    def test_detached_selected_tree_is_rejected_before_mutation(self):
        script = self.script(True).replace(
            'walk($held, 0, length($selected), 0);',
            'walk($held, 0, length($selected), 0); '
            'rename($selected, $selected . ".detached") or die; '
            'mkdir($selected, 0700) or die;')
        result = self.run_script(script=script)
        self.assertEqual(result.returncode, 74, result.stderr)
        self.assertEqual((Path(str(self.selected) + '.detached') / self.file.name).stat().st_mode & 0o7777,
                         0o444)
        self.assertEqual(self.mode(self.victim), 0o444)
        self.assertEqual(list(self.selected.iterdir()), [])

    def test_appearance_of_previously_missing_subtree_is_not_reported_valid(self):
        missing = self.staging / 'not copied'
        script = self.script(selected=missing).replace(
            'my @selected_info = defined($held) ? stat($held) : ();',
            'my @selected_info = defined($held) ? stat($held) : (); '
            'mkdir($selected, 0700) or die;')
        self.refused(self.run_script(script=script))

    def test_nested_shell_and_newline_names_are_not_executed(self):
        directory = self.selected / "quotes ' $() ;\nfolder"
        directory.mkdir()
        nested = directory / '`whoami` ;\nfile'
        nested.write_bytes(b'fixture')
        nested.chmod(0o440)
        result = self.run_script(writable=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.mode(nested), 0o640)
        self.assertEqual(nested.read_bytes(), b'fixture')
        self.assertEqual(sorted(path.name for path in self.selected.iterdir()),
                         sorted([self.file.name, directory.name]))

    def test_scope_and_arguments_rejected_before_shell(self):
        for selected in (self.home, self.staging, self.victim,
                         self.staging / '..' / 'live', self.staging / 'bad\nroot'):
            with self.subTest(selected=selected):
                with self.assertRaises(ValueError):
                    self.script(selected=selected)
        for migration_id in ('', 'a' * 31, 'A' * 32, 'a' * 32 + '\n', '; touch fixture'):
            with self.assertRaises(ValueError):
                staging_permissions_script(str(self.home), str(self.staging),
                                           str(self.selected), migration_id)
        with self.assertRaises(ValueError):
            staging_permissions_script(str(self.home), str(self.staging),
                                       str(self.selected), self.migration_id, writable=1)

    def test_competing_destination_lock_prevents_permission_changes(self):
        holder = subprocess.Popen(['/bin/zsh', '-f', '-s'], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, start_new_session=True)
        try:
            holder.stdin.write(locked_destination_script(str(self.home),
                                                        'echo READY; /bin/sleep 30'))
            holder.stdin.close()
            holder.stdin = None
            self.assertTrue(select.select([holder.stdout], [], [], 5)[0])
            self.assertEqual(holder.stdout.readline().strip(), 'READY')
            result = self.run_script(writable=True)
            self.assertEqual(result.returncode, 75, result.stderr)
            self.assertEqual(self.mode(), 0o444)
        finally:
            os.killpg(holder.pid, signal.SIGTERM)
            holder.communicate(timeout=5)

    def test_immutable_file_refuses_without_clearing_flag(self):
        subprocess.run(['/usr/bin/chflags', 'uchg', str(self.file)], check=True)
        try:
            result = self.run_script(writable=True)
            self.refused(result)
            self.assertTrue(self.file.stat().st_flags & 2)
        finally:
            subprocess.run(['/usr/bin/chflags', 'nouchg', str(self.file)], check=True)

    def test_descriptor_acl_reset_does_not_follow_replaced_path(self):
        import getpass
        subprocess.run(['/bin/chmod', '+a', 'user:%s deny write' % getpass.getuser(),
                        str(self.file)], check=True)
        script = r'''use strict; use warnings; use Fcntl qw(:DEFAULT F_SETFD);
sysopen(my $file, $ARGV[0], O_RDONLY | O_NOFOLLOW | O_NONBLOCK) or die;
rename($ARGV[0], $ARGV[0] . '.held') or die;
open(my $replacement, '>', $ARGV[0]) or die;
print $replacement 'replacement fixture'; close($replacement) or die;
chmod(0440, $ARGV[0]) == 1 or die;
defined fcntl($file, F_SETFD, 0) or die;
system('/bin/chmod', '-N', '/dev/fd/' . fileno($file)) == 0 or die;
'''
        result = subprocess.run(['/usr/bin/perl', '-e', script, str(self.file)],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        held = Path(str(self.file) + '.held')
        result = subprocess.run(['/bin/ls', '-le', str(held)],
                                capture_output=True, text=True, check=True)
        self.assertEqual(len(result.stdout.splitlines()), 1)
        self.assertEqual(self.mode(held), 0o444)
        self.assertEqual(held.read_bytes(), b'disposable fixture')
        self.assertEqual(self.mode(), 0o440)
        self.assertEqual(self.file.read_bytes(), b'replacement fixture')

    def test_real_multipass_preserves_readonly_bytes_modes_links_and_metadata(self):
        source = self.base / 'disposable source'
        source.mkdir()
        readonly = source / 'object'
        readonly.write_bytes(b'Git-like read-only object')
        (source / 'empty directory').mkdir()
        (source / 'object alias').symlink_to('object')
        (source / 'external file alias').symlink_to(self.victim)
        (source / 'external directory alias').symlink_to(self.outside)
        subprocess.run(['/usr/bin/xattr', '-w', 'com.segeren.fixture',
                        'metadata fixture', str(readonly)], check=True)
        subprocess.run(['/usr/bin/xattr', '-wx', 'com.apple.ResourceFork',
                        '00010203', str(readonly)], check=True)
        subprocess.run(['/bin/chmod', '+a', 'everyone allow read', str(readonly)], check=True)
        import getpass
        subprocess.run(['/bin/chmod', '+a', 'user:%s deny write' % getpass.getuser(),
                        str(readonly)], check=True)
        readonly.chmod(0o444)
        expected = freeze_tree(str(source))
        # Empty the disposable preexisting leaf; do not delete any real data.
        self.file.unlink()
        fixture = self
        phases = []
        class LocalTransport:
            def run_remote_cancellable(self, script, timeout, cancelled):
                if cancelled():
                    raise RuntimeError('Fixture stopped')
                result = fixture.run_script(script=script)
                fixture.assertEqual(result.returncode, 0, result.stderr)
                return result

            def rsync_process(self, source, destination, excludes=(), copy_links=False, phase='data'):
                fixture.assertEqual(excludes, ())
                fixture.assertFalse(copy_links)
                phases.append(phase)
                return TransferProcess(['/usr/bin/rsync', *rsync_phase_options(phase),
                                        '--delete-after', source + '/', destination + '/'])

        transfer_staged(LocalTransport(), str(self.home), str(self.staging),
                        str(self.selected), self.migration_id, str(source))
        self.assertEqual(phases, ['data', 'metadata', 'modes'])
        self.assertEqual(freeze_tree(str(self.selected)), expected)
        self.assertEqual(freeze_tree(str(source)), expected)
        for name in ('com.segeren.fixture', 'com.apple.ResourceFork'):
            def attribute(path):
                return subprocess.run(['/usr/bin/xattr', '-px', name, str(path)],
                                      capture_output=True, check=True).stdout
            self.assertEqual(attribute(readonly), attribute(self.selected / 'object'))
        def acl(path):
            return subprocess.run(['/bin/ls', '-le', str(path)], capture_output=True,
                                  check=True, text=True).stdout.splitlines()[1:]
        self.assertEqual(acl(readonly), acl(self.selected / 'object'))
        self.assertEqual(self.run_script().returncode, 0)
        # Finalize and Resume must both work after the source deny-write ACL
        # has already been installed on the staging file by an earlier pass.
        phases.clear()
        transfer_staged(LocalTransport(), str(self.home), str(self.staging),
                        str(self.selected), self.migration_id, str(source))
        self.assertEqual(phases, ['data', 'metadata', 'modes'])
        self.assertEqual(freeze_tree(str(self.selected)), expected)
        self.assertEqual(acl(readonly), acl(self.selected / 'object'))
        for name in ('com.segeren.fixture', 'com.apple.ResourceFork'):
            self.assertEqual(attribute(readonly), attribute(self.selected / 'object'))
        self.assertEqual(self.mode(self.victim), 0o444)
        self.assertEqual(self.victim.read_bytes(), b'outside fixture')

    def test_writable_batches_preserve_every_other_mode_bit_and_metadata(self):
        import getpass
        paths = []
        for index in range(65):
            path = self.selected / ('file %d' % index)
            path.write_bytes(b'disposable batch fixture')
            subprocess.run(['/bin/chmod', '+a', 'user:%s deny write' % getpass.getuser(),
                            str(path)], check=True, capture_output=True)
            path.chmod(0o450)
            paths.append(path)
        result = self.run_script(writable=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for path in paths:
            self.assertEqual(self.mode(path), 0o650)
            self.assertEqual(path.read_bytes(), b'disposable batch fixture')
            acl = subprocess.run(['/bin/ls', '-le', str(path)], capture_output=True,
                                 text=True, check=True).stdout.splitlines()[1:]
            self.assertEqual(acl, [])

    def test_restrictive_directory_acl_remains_fail_closed_not_silently_dropped(self):
        import getpass
        source = self.base / 'directory ACL source'
        restricted = source / 'restricted'
        restricted.mkdir(parents=True)
        file = restricted / 'file'
        file.write_bytes(b'disposable restricted fixture')
        subprocess.run(['/usr/bin/xattr', '-wx', 'com.apple.ResourceFork',
                        '00010203', str(file)], check=True)
        permission = 'user:%s deny add_file,add_subdirectory,delete_child' % getpass.getuser()
        subprocess.run(['/bin/chmod', '+a', permission, str(restricted)], check=True)
        # Remove only the disposable fixture ACLs before tempfile cleanup.
        def cleanup_acl():
            for path in (restricted, self.selected / 'restricted'):
                if path.is_dir():
                    subprocess.run(['/bin/chmod', '-N', str(path)], check=True, capture_output=True)
        self.addCleanup(cleanup_acl)
        fixture = self
        phases = []
        class LocalTransport:
            def run_remote_cancellable(self, script, timeout, cancelled):
                result = fixture.run_script(script=script)
                fixture.assertEqual(result.returncode, 0, result.stderr)
            def rsync_process(self, source, destination, excludes=(), copy_links=False, phase='data'):
                phases.append(phase)
                return TransferProcess(['/usr/bin/rsync', *rsync_phase_options(phase),
                                        '--delete-after', source + '/', destination + '/'])
        with self.assertRaises(TransportError):
            transfer_staged(LocalTransport(), str(self.home), str(self.staging),
                            str(self.selected), self.migration_id, str(source))
        self.assertEqual(phases, ['data', 'metadata'])
        self.assertEqual(file.read_bytes(), b'disposable restricted fixture')
        self.assertEqual(self.mode(self.victim), 0o444)
