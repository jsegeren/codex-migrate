"""One-shot real-SSH recovery fixture. Never selects Codex data for replacement.

The fixture writer is intentionally killed after a production transaction is
durable. The unmodified signed build then inspects/restores through its HTTP API.
This is not a physical-cable-loss or native-browser-interaction test.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import shlex
import signal
import stat
import subprocess
import sys
import time

SHARED = Path('/Users/Shared/CodexMigrate-Authentic-20260906')
NAME = 'Codex-Migrate-Recovery-20260907'
ID = 'bfe9610a089a44b4ac9b192d0c8b3673'
OLD = 'Original disposable recovery fixture.\n'
NEW = 'Newer disposable data must survive restoration.\n'
SENTINEL = 'Outside the selected recovery scope.\n'


def require(value, reason='verification_failed'):
    if not value:
        raise RuntimeError(reason)


def plan_for(home):
    root = home / NAME
    backup = home / (NAME + '-Backup')
    return {'format': 2, 'id': ID, 'home': str(home), 'backup': str(backup),
            'scope': [{'original': str(root / 'workspace'),
                       'backup': str(backup / 'workspace')}]}


def fixture_writer():
    f.account(f.TARGET)
    f.closed()
    home = f.TARGET
    root = home / NAME
    backup = home / (NAME + '-Backup')
    require(not any(os.path.lexists(p) for p in
            (root, backup, home / '.codex-migrate-transaction.json')), 'existing_evidence')
    root.mkdir(mode=0o700)
    backup.mkdir(mode=0o700)
    original = root / 'workspace'
    original.mkdir(mode=0o700)
    (original / 'original.txt').write_text(OLD)
    (root / 'outside.txt').write_text(SENTINEL)
    result = subprocess.run(['/bin/cp', '-c', '-Rp', str(original), str(backup / 'workspace')],
                            capture_output=True)
    require(result.returncode == 0, 'backup_failed')
    result = subprocess.run(['/usr/bin/perl', '-e', TRANSACTION_RUNNER, '--',
                             'begin', json.dumps(plan_for(home))], capture_output=True)
    require(result.returncode == 0, 'transaction_failed')
    # Preserve the original separately as well as in the production-frozen backup.
    original.rename(root / 'prior-original')
    original.mkdir(mode=0o700)
    with (original / 'newer.txt').open('x') as stream:
        stream.write(NEW)
        stream.flush()
        os.fsync(stream.fileno())
    os.kill(os.getpid(), signal.SIGKILL)


def remote_action(action):
    f.account(f.TARGET)
    f.closed()
    home = f.TARGET
    root = home / NAME
    backup = home / (NAME + '-Backup')
    if action == 'interrupt':
        child = BOOTSTRAP + SELF + '\nfixture_writer()\n'
        command = 'exec /usr/bin/python3 -I -c ' + shlex.quote(child)
        # Production exclusion stays held by the exact writer until it dies.
        process = subprocess.Popen(['/usr/bin/perl', '-e', LOCK_RUNNER, '--', str(home), command],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output, _ = process.communicate(timeout=180)
        require(process.returncode == -signal.SIGKILL and not output, 'interruption_not_observed')
        record = json.loads((home / '.codex-migrate-transaction.json').read_text())
        require(record['id'] == ID and record['phase'] == 'replacing')
        require((root / 'workspace/newer.txt').read_text() == NEW)
        require((backup / 'workspace/original.txt').read_text() == OLD)
        return {'fixture_writer_killed': True, 'durable_pending_transaction': True}
    require(action == 'prove')
    f.safe_dir(root, os.getuid())
    f.safe_dir(backup, os.getuid())
    require(not os.path.lexists(home / '.codex-migrate-transaction.json'))
    require((root / 'workspace/original.txt').read_text() == OLD)
    require(not (root / 'workspace/newer.txt').exists())
    require((root / 'prior-original/original.txt').read_text() == OLD)
    require((backup / 'workspace/original.txt').read_text() == OLD)
    require((backup / ('recovery-' + ID) / 'current/0/newer.txt').read_text() == NEW)
    require((root / 'outside.txt').read_text() == SENTINEL)
    return {'original_restored': True, 'newer_files_preserved': True,
            'backup_contents_unchanged': True, 'out_of_scope_file_unchanged': True,
            'pending_journal_cleared': True}


def load_resources():
    owner = pwd.getpwnam('jsegeren').pw_uid
    for path in (SHARED, SHARED / 'final-recovery-resources.json'):
        info = path.lstat()
        require(info.st_uid == owner and not info.st_mode & 0o022
                and (stat.S_ISDIR(info.st_mode) if path == SHARED else stat.S_ISREG(info.st_mode)),
                'unsafe_resources')
    data = json.loads((SHARED / 'final-recovery-resources.json').read_text())
    import types
    module = types.ModuleType('final_device')
    exec(data['final_device'], module.__dict__)
    return data, module


def driver():
    resources, f = load_resources()
    f.account(f.SOURCE)
    f.closed()
    h = f.load_handoff()
    f.safe_dir(f.PUBLIC, os.getuid())
    state = f.SOURCE / '.local/state/codex-migrate-recovery-20260907'
    require(not os.path.lexists(state), 'existing_state_preserve_it')
    # Reserve the run before any remote mutation; this harness cannot be rerun.
    state.mkdir(mode=0o700)
    report = {'phase': 'preflight', 'runner_pid': os.getpid(), 'build': 5,
              'codex_replacement_selected': False, 'physical_disconnect_tested': False}
    def update(phase, **extra):
        report.update(phase=phase, updated_at=time.time(), **extra)
        h.save(f.PUBLIC / 'final-recovery-checks.json', report, public=True)
    engine = None
    try:
        update('preflight')
        require(hashlib.sha256(f.ARCHIVE.read_bytes()).hexdigest() == f.ARCHIVE_HASH, 'candidate_mismatch')
        h.ENGINE = f.ENGINE
        h.verify_shared_candidate()
        reply, options, identity, known = h.connection()
        bootstrap = ('import types\nf=types.ModuleType("fixture")\nexec(' + repr(resources['final_device'])
                     + ',f.__dict__)\nTRANSACTION_RUNNER=' + repr(resources['transaction'])
                     + '\nLOCK_RUNNER=' + repr(resources['lock']) + '\n')
        own = Path(__file__).read_text().split("\nif __name__ == '__main__':")[0]
        remote_code = bootstrap + 'BOOTSTRAP=' + repr(bootstrap) + '\nSELF=' + repr(own) + '\n' + own
        def remote(action):
            require(action in {'interrupt', 'prove'})
            code = remote_code + '\nprint(json.dumps(remote_action(' + repr(action) + ')))\n'
            process = subprocess.Popen(['/usr/bin/ssh', *options, reply['target'], '/usr/bin/python3 -I -'],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            output, _ = process.communicate(input=code.encode(), timeout=240)
            require(process.returncode == 0 and len(output) < 2048, 'remote_' + action + '_failed')
            return json.loads(output)
        # Bring up the verified recovery controller before creating a pending record.
        args = ['--apply', '--source-home', str(f.SOURCE), '--target', reply['target'],
                '--target-home', str(f.TARGET), '--identity-file', str(identity),
                '--known-hosts-file', str(known), '--host-key-alias', 'codex-migrate-' + reply['id']]
        engine = subprocess.Popen([str(f.ENGINE), 'serve', *args, '--state-dir', str(state),
            '--port', '0', '--no-open'], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True)
        for _ in range(100):
            require(engine.poll() is None, 'helper_exited')
            try:
                port = h.listener(engine.pid)
                token = h.checked(state / 'control-token').read_text().strip()
                break
            except (OSError, h.SafeError):
                time.sleep(0.2)
        else:
            raise RuntimeError('helper_start_timeout')
        def action(name, **extra):
            return h.api(port, token, '/api/action', dict(action=name, **extra))
        def wait_recovery(expected, pending):
            deadline = time.monotonic() + 240
            while time.monotonic() < deadline:
                value = h.api(port, token, '/api/status')
                status = value.get('recovery', {}).get('status')
                if status == expected:
                    return value
                require(status in pending, 'recovery_needs_review')
                time.sleep(0.2)
            raise RuntimeError('observation_timeout_preserve_helper')
        update('creating_disposable_interrupted_transaction', helper_pid=engine.pid)
        proof = remote('interrupt')
        update('checking_real_destination_backup', **proof)
        action('check_recovery')
        checked = wait_recovery('backup_verified', {'checking'})
        require(checked['recovery']['transaction_id'] == ID)
        require([x['original'] for x in checked['recovery']['items']] ==
                [plan_for(f.TARGET)['scope'][0]['original']])
        update('restoring_disposable_scope', production_backup_verified=True)
        action('restore_recovery', confirmed=True, transaction_id=ID)
        restored = wait_recovery('restore_verified', {'restoring'})
        require(restored.get('phase') == 'restored' and not restored.get('receipt'))
        update('verifying_preserved_files', **remote('prove'))
        action('check_recovery')
        wait_recovery('restore_verified', {'checking'})
        engine.send_signal(signal.SIGINT)
        engine.wait(timeout=30)
        update('passed', packaged_restore_verified=True, repeat_reconciliation_verified=True,
               migration_not_falsely_completed=True)
    except Exception as error:
        # No raw remote output, paths, tokens, or contents enter the Shared report.
        allowed = {'candidate_mismatch', 'remote_interrupt_failed', 'remote_prove_failed',
            'helper_exited', 'helper_start_timeout', 'recovery_needs_review',
            'observation_timeout_preserve_helper', 'verification_failed'}
        reason = str(error) if type(error) is RuntimeError else 'unexpected_error'
        update('needs_review', failed_phase=report['phase'], reason=reason if reason in allowed else 'unexpected_error')
        return 1
    return 0


if __name__ == '__main__':
    if sys.argv[1:] == ['--apply', '--background']:
        _, f = load_resources()
        f.account(f.SOURCE)
        subprocess.Popen(['/usr/bin/python3', '-I', str(Path(__file__).resolve()), '--apply'],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
    elif sys.argv[1:] == ['--apply']:
        sys.exit(driver())
    else:
        sys.exit(2)
