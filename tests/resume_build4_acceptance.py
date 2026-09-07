"""One authorized, fixed build-4 test continuation; no privileged service.

Runs as the existing disposable source user, never root. Revalidates the exact
failed backup with the candidate's read-only verifier before retiring its idle
helper. Retains sign-ins, conversations, migration state, staging and backups.
"""
import base64
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import shlex
import signal
import stat
import subprocess
import sys
import time

SHARED = Path('/Users/Shared/CodexMigrate-Authentic-20260906')
SOURCE = Path('/Users/codexmigratesource')
TARGET = Path('/Users/codexmigratetarget')
PUBLIC = Path('/Users/Shared/CodexMigrate-Authentic-Status-20260906')
BUNDLE_HASH = '4d7b5ad888875546e21a0ad7ae9988eec09463cc8661ef6da3dce76dcb2bb44c'
ARCHIVE_HASH = 'bba8b35f55b61389b0b36e65e50f45962975d7944d19293420e11a3f19a19d08'
BUILD = SHARED / 'accepted-build4'
ENGINE = BUILD / 'Codex Migrate.app/Contents/Resources/engine/codex-migrate-engine'
BACKUP = re.compile(r'Codex-Migrate-Backup-\d{8}T\d{6}Z-[a-f0-9]{16}')


def require(ok):
    if not ok:
        raise RuntimeError('review_required')


def directory(path):
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and not info.st_mode & 0o022)


def verifier(bytes_):
    require(hashlib.sha256(bytes_).hexdigest() == BUNDLE_HASH)
    return json.loads(bytes_)['program']


def remote_check(payload):
    user = pwd.getpwuid(os.getuid())
    require(os.getuid() == os.geteuid() != 0 and user.pw_name == TARGET.name
            and user.pw_dir == str(TARGET))
    require(set(payload) == {'name', 'verifier'} and BACKUP.fullmatch(payload['name']))
    program = verifier(base64.b64decode(payload['verifier'], validate=True))
    directory(TARGET)
    backup = TARGET / payload['name']
    for item in (backup, TARGET / '.codex', backup / '.codex'):
        directory(item)
    require(not os.path.lexists(TARGET / '.codex-migrate-transaction.json')
            and not os.path.lexists(backup / 'verification.json'))
    processes = subprocess.check_output(['/bin/ps', '-U', str(os.getuid()), '-o', 'comm='],
                                        text=True, timeout=10)
    require(not any(Path(line.strip()).name in
        {'Codex', 'ChatGPT', 'codex', 'codex-cli', 'codex_chronicle', 'codex-migrate-engine'}
        for line in processes.splitlines()))
    result = subprocess.run(['/usr/bin/perl', '-e', program, '--',
        str(TARGET / '.codex'), str(backup / '.codex')],
        env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
    require(result.returncode == 0)
    require(not os.path.lexists(TARGET / '.codex-migrate-transaction.json'))
    return {'read_only': True, 'candidate_backup_comparison_passed': True}


def safe_failure(value, target):
    if not isinstance(value, dict):
        return False
    config = value.get('config', {})
    backup = value.get('pending_backup')
    return (isinstance(config, dict) and config.get('source_home') == str(SOURCE)
        and config.get('target_home') == str(TARGET) and config.get('target') == target
        and config.get('staging_name') == 'Codex-Migrate-Authentic-Staging-20260906'
        and config.get('workspace_roots') == [str(SOURCE / 'Authentic-Migration-Test')]
        and value.get('status') == 'failed' and value.get('phase') == 'installing'
        and not value.get('receipt') and isinstance(backup, str)
        and Path(backup).parent == TARGET and BACKUP.fullmatch(Path(backup).name) is not None
        and isinstance(value.get('migration_id'), str)
        and re.fullmatch(r'[a-f0-9]{32}', value['migration_id']) is not None
        and all(isinstance(value.get(key, {}), dict)
                and value.get(key, {}).get('status') not in ('checking', 'restoring')
                for key in ('recovery', 'git_verification', 'path_compatibility')))


def load_handoff():
    # These public operator files are owned by the administrator who prepared
    # them, not writable by the disposable account or other local users.
    for path in (SHARED, SHARED / 'authentic_mac_handoff.py',
                 SHARED / 'build4-backup-verifier.json'):
        info = path.lstat()
        require(not stat.S_ISLNK(info.st_mode) and info.st_uid == pwd.getpwnam('jsegeren').pw_uid
                and not info.st_mode & 0o022)
    spec = importlib.util.spec_from_file_location('authentic_handoff', SHARED / 'authentic_mac_handoff.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def continue_test():
    h = load_handoff()
    home = h.account('source')
    root = h.checked(home / h.STATE_NAME, directory=True)
    h.checked(PUBLIC, directory=True, private=False)
    lock_fd = os.open(root / 'build4-continuation.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    lock = os.fdopen(lock_fd, 'w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    # An earlier observer must have exited before this upgrade is attempted.
    runner_fd = os.open(root / 'runner.lock', os.O_RDWR | os.O_NOFOLLOW)
    runner_lock = os.fdopen(runner_fd, 'w')
    fcntl.flock(runner_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    phase = 'checking_candidate'
    def report(**extra):
        h.save(PUBLIC / 'build4-continuation.json',
               {'phase': phase, 'runner_pid': os.getpid(), 'updated_at': time.time(), **extra}, public=True)
    try:
        report()
        archive = BUILD / 'Codex-Migrate-0.1.0-build4-arm64.zip'
        require(hashlib.sha256(archive.read_bytes()).hexdigest() == ARCHIVE_HASH)
        candidate = h.ENGINE
        h.ENGINE = ENGINE
        h.verify_shared_candidate()
        h.ENGINE = candidate
        reply, options, _, _ = h.connection()
        runtime = h.read(root / h.RUNTIME_RECORD)
        pid = runtime.get('pid')
        require(type(pid) is int and (pid, str(candidate)) in h.processes())
        require(h.codex_closed())
        state_dir = h.checked(root / h.MIGRATION_STATE, directory=True)
        token = h.checked(state_dir / 'control-token').read_text().strip()
        port = h.listener(pid)
        before = h.api(port, token, '/api/status')
        require(safe_failure(before, reply['target']))
        phase = 'checking_actual_backup_with_build4'
        report()
        bundle = (SHARED / 'build4-backup-verifier.json').read_bytes()
        verifier(bundle)
        payload = base64.b64encode(json.dumps({'name': Path(before['pending_backup']).name,
            'verifier': base64.b64encode(bundle).decode()}).encode()).decode()
        response = subprocess.run(['/usr/bin/ssh', *options, reply['target'],
            '/usr/bin/python3 -I - --remote ' + shlex.quote(payload)],
            input=Path(__file__).read_bytes(), capture_output=True, timeout=330)
        require(response.returncode == 0 and len(response.stdout) < 1024
                and json.loads(response.stdout) == {'read_only': True, 'candidate_backup_comparison_passed': True})
        after = h.api(port, token, '/api/status')
        require(safe_failure(after, reply['target']) and (pid, str(candidate)) in h.processes()
                and all(before.get(key) == after.get(key)
                        for key in ('migration_id', 'pending_backup', 'config')))
        # Save a separate diagnostic before shutdown. Never overwrite state or
        # delete the failed attempt's backup. No SIGKILL or active-phase stop.
        h.export_test_diagnostic()
        phase = 'retiring_verified_idle_build2_helper'
        report(candidate_backup_comparison_passed=True)
        os.kill(pid, signal.SIGTERM)
        for _ in range(100):
            if (pid, str(candidate)) not in h.processes():
                break
            time.sleep(0.1)
        require((pid, str(candidate)) not in h.processes())
        phase = 'running_build4_acceptance'
        report(candidate_backup_comparison_passed=True)
        h.ENGINE = ENGINE
        runner_lock.close()  # driver takes the same normal runner lock itself.
        h.driver(reviewed_backup={key: before[key] for key in ('migration_id', 'pending_backup')})
        phase = 'runner_finished_check_result'
        report()
    except Exception:
        report(needs_review=True)
        raise
    finally:
        runner_lock.close()
        lock.close()


if __name__ == '__main__':
    try:
        if len(sys.argv) == 3 and sys.argv[1] == '--remote':
            print(json.dumps(remote_check(json.loads(base64.b64decode(sys.argv[2], validate=True)))))
        elif sys.argv[1:] == ['--background']:
            require(os.getuid() == os.geteuid() == pwd.getpwnam('codexmigratesource').pw_uid)
            h = load_handoff()
            h.account('source')
            h.checked(PUBLIC, directory=True, private=False)
            worker = subprocess.Popen(['/usr/bin/python3', '-I', str(Path(__file__).resolve())],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True)
            time.sleep(1)
            require(worker.poll() is None or worker.returncode == 0)
            print('Authorized test worker started. Results will be saved in Shared; this window may close.')
        else:
            require(len(sys.argv) == 1)
            continue_test()
    except Exception:
        print('Test stopped for review; no raw errors or credentials were exported.')
        sys.exit(1)
