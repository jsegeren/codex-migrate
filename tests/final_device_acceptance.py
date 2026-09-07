"""Fixed-scope, one-shot build 5 device checks; never run as root/personal user.

Uses the existing disposable accounts and pinned pairing. Does not finalize a
full migration, replace prior fixtures, remove backups, or grant ongoing access.
"""
import fcntl
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
PUBLIC = Path('/Users/Shared/CodexMigrate-Authentic-Status-20260906')
SOURCE = Path('/Users/codexmigratesource')
TARGET = Path('/Users/codexmigratetarget')
NAME = 'Codex-Migrate-Final-20260907'
BUILD = SHARED / 'candidate-build5'
ENGINE = BUILD / 'Codex Migrate.app/Contents/Resources/engine/codex-migrate-engine'
ARCHIVE = BUILD / 'Codex-Migrate-0.1.0-build5-arm64.zip'
ARCHIVE_HASH = 'adc126c92952e0031138b199bc2003c18ee08a6a419f2cfe91ea404b84483be7'
SKILL = '.agents/skills/final-device-check/SKILL.md'
NEW_SKILL = '---\nname: final-device-check\ndescription: Disposable migration acceptance skill.\n---\nNew test skill.\n'
OLD_SKILL = 'Original disposable destination skill.\n'
SENTINEL = 'Unrelated disposable project file; preserve exactly.\n'


def require(ok, reason='review_required'):
    if not ok:
        raise RuntimeError(reason)


def safe_dir(path, owner):
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == owner and not info.st_mode & 0o022)


def account(home):
    user = pwd.getpwuid(os.getuid())
    require(os.getuid() == os.geteuid() != 0 and user.pw_dir == str(home)
            and user.pw_name == home.name, 'wrong_account')
    safe_dir(home, os.getuid())


def new_root(home):
    root = home / NAME
    require(not os.path.lexists(root), 'fixture_already_exists_preserve_it')
    root.mkdir(mode=0o700)
    return root


def closed():
    result = subprocess.run(['/bin/ps', '-U', str(os.getuid()), '-o', 'comm='],
                            capture_output=True, text=True, timeout=15)
    require(result.returncode == 0, 'process_check_failed')
    names = {Path(x.strip()).name for x in result.stdout.splitlines()}
    require(not names.intersection({'Codex', 'ChatGPT', 'codex', 'codex-cli',
                                    'codex_chronicle', 'codex-migrate-engine'}),
            'close_test_account_apps')


def retained_digest(home):
    """Private comparison only: never open authentication/installation identity."""
    root = home / '.codex'
    safe_dir(root, os.getuid())
    digest = hashlib.sha256()
    def failed(_error):
        raise RuntimeError('retained_state_unreadable')
    for folder, dirs, files in os.walk(root, followlinks=False, onerror=failed):
        dirs.sort()
        for name in sorted(dirs + files):
            path = Path(folder) / name
            relative = path.relative_to(root)
            if len(relative.parts) == 1 and name.casefold() in {'auth.json', 'installation_id'}:
                continue
            info = path.lstat()
            digest.update(str(relative).encode())
            digest.update(str(stat.S_IFMT(info.st_mode)).encode())
            if stat.S_ISREG(info.st_mode):
                with path.open('rb') as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(block)
            elif stat.S_ISLNK(info.st_mode):
                digest.update(os.readlink(path).encode())
    return digest.hexdigest()


def remote_action(action):
    account(TARGET)
    closed()
    require(not os.path.lexists(TARGET / '.codex-migrate-transaction.json'), 'pending_recovery')
    if action == 'prepare':
        root = new_root(TARGET)
        skill = root / SKILL
        skill.parent.mkdir(parents=True, mode=0o700)
        skill.write_text(OLD_SKILL)
        (root / 'unrelated.txt').write_text(SENTINEL)
        (root / 'before.json').write_text(json.dumps({'retained': retained_digest(TARGET)}))
        (root / 'before.json').chmod(0o600)
        return {'prepared': True}
    if action == 'staged':
        staging = TARGET / (NAME + '-Staging')
        safe_dir(staging, os.getuid())
        # Count staged regular-file bytes; do not read their contents or identity.
        size = 0
        for folder, _, files in os.walk(staging, followlinks=False):
            for name in files:
                info = (Path(folder) / name).lstat()
                if stat.S_ISREG(info.st_mode):
                    size += info.st_size
        require(size > 0, 'no_partial_data')
        require((TARGET / NAME / SKILL).read_text() == OLD_SKILL, 'unexpected_full_replacement')
        return {'partial_staged_bytes': size, 'full_replacement_not_performed': True}
    require(action == 'prove', 'unsupported_action')
    root = TARGET / NAME
    safe_dir(root, os.getuid())
    before_path = root / 'before.json'
    info = before_path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and not info.st_mode & 0o077)
    before = json.loads(before_path.read_text())
    require((root / SKILL).read_text() == NEW_SKILL, 'selected_skill_mismatch')
    require((root / 'unrelated.txt').read_text() == SENTINEL, 'unrelated_file_changed')
    require(retained_digest(TARGET) == before['retained'], 'retained_codex_state_changed')
    return {'selected_skill_verified': True, 'unrelated_project_file_preserved': True,
            'retained_codex_state_preserved': True}


def load_handoff():
    owner = pwd.getpwnam('jsegeren').pw_uid
    safe_dir(SHARED, owner)
    path = SHARED / 'authentic_mac_handoff.py'
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == owner and not info.st_mode & 0o022)
    spec = importlib.util.spec_from_file_location('handoff', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def driver():
    account(SOURCE)
    h = load_handoff()
    safe_dir(PUBLIC, os.getuid())
    lock_root = h.checked(SOURCE / h.STATE_NAME, directory=True)
    lock = os.fdopen(os.open(lock_root / 'final-device.lock',
                     os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600), 'w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    report = {'phase': 'preflight', 'runner_pid': os.getpid(), 'build': 5,
              'full_finalization_attempted': False, 'physical_disconnect_tested': False,
              'protected_recovery_tested': False, 'native_accessibility_tested': False}
    def update(phase, **extra):
        report.update(phase=phase, updated_at=time.time(), **extra)
        h.save(PUBLIC / 'final-device-checks.json', report, public=True)
    engine = None
    try:
        update('preflight')
        closed()
        require(hashlib.sha256(ARCHIVE.read_bytes()).hexdigest() == ARCHIVE_HASH, 'candidate_mismatch')
        h.ENGINE = ENGINE
        h.verify_shared_candidate()
        reply, options, identity, known = h.connection()
        def remote(action):
            require(action in {'prepare', 'staged', 'prove'})
            result = subprocess.run(['/usr/bin/ssh', *options, reply['target'],
                '/usr/bin/python3 -I - --remote ' + shlex.quote(action) + ' --apply'],
                input=Path(__file__).read_bytes(), capture_output=True, timeout=180)
            require(result.returncode == 0 and len(result.stdout) < 2048, 'target_' + action + '_failed')
            return json.loads(result.stdout)
        root = new_root(SOURCE)
        skill = root / SKILL
        skill.parent.mkdir(parents=True, mode=0o700)
        skill.write_text(NEW_SKILL)
        # Bounded incompressible fixture gives Stop a real transfer to interrupt.
        with (root / 'transfer-fixture.bin').open('xb') as stream:
            for _ in range(256):
                stream.write(os.urandom(1024 * 1024))
        update('preparing_new_destination_fixture')
        remote('prepare')
        state = SOURCE / '.local/state/codex-migrate-final-20260907'
        require(not os.path.lexists(state), 'state_already_exists_preserve_it')
        args = ['--apply', '--source-home', str(SOURCE), '--target', reply['target'],
                '--target-home', str(TARGET), '--workspace', str(root),
                '--identity-file', str(identity), '--known-hosts-file', str(known),
                '--host-key-alias', 'codex-migrate-' + reply['id']]
        engine = subprocess.Popen([str(ENGINE), 'serve', *args, '--state-dir', str(state),
            '--staging-name', NAME + '-Staging', '--port', '0', '--no-open'],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
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
        def status():
            return h.api(port, token, '/api/status')
        def action(name):
            return h.api(port, token, '/api/action', {'action': name})
        def wait(predicate, timeout=900):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                value = status()
                if predicate(value):
                    return value
                require(value.get('status') not in {'failed', 'interrupted'}, 'helper_needs_review')
                time.sleep(0.1)
            raise RuntimeError('observation_timeout_preserve_helper')
        update('inspecting')
        action('inspect')
        wait(lambda s: s.get('status') == 'ready')
        update('staging_until_workspace_copy')
        action('start')
        first = wait(lambda s: str(s.get('current_item', '')).startswith('Workspace')
                     or s.get('status') == 'ready_to_finalize')
        require(first.get('status') != 'ready_to_finalize', 'transfer_finished_before_stop_probe')
        migration_id = first['migration_id']
        action('pause')
        wait(lambda s: s.get('status') == 'paused')
        partial = remote('staged')
        action('cancel')
        stopped = wait(lambda s: s.get('status') in {'stopped', 'cancelled', 'ready_to_finalize'})
        require(stopped.get('status') != 'ready_to_finalize', 'stop_not_observed')
        update('resuming_retained_staging', stop_observed=True,
               pause_observed=True, partial_bytes_observed=partial['partial_staged_bytes'])
        action('resume')
        staged = wait(lambda s: s.get('status') == 'ready_to_finalize')
        require(staged['migration_id'] == migration_id and not staged.get('receipt'), 'scope_changed')
        update('staging_resume_passed', stage_resume_verified=True)
        engine.send_signal(signal.SIGINT)
        engine.wait(timeout=30)
        update('skills_only_repair')
        exporter = subprocess.Popen([str(ENGINE), 'export', *args, '--component', 'workspace-skills',
            '--state-dir', str(SOURCE / '.local/state/codex-migrate-final-skills-20260907'),
            '--staging-name', NAME + '-Skills-Staging', '--json'],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True)
        update('skills_only_repair', exporter_pid=exporter.pid)
        output, _ = exporter.communicate(timeout=900)  # Timeout never kills protected replacement.
        require(exporter.returncode == 0, 'skills_export_failed')
        result_data = json.loads(output)
        require(result_data.get('applied') is True and result_data.get('item_count') == 1
                and result_data.get('backup_verified') is True,
                'skills_export_failed')
        proof = remote('prove')
        update('automated_device_checks_passed_remaining_manual_gates', skills_backup_verified=True, **proof)
    except Exception as error:
        # Fixed categories only. Do not export raw SSH/errors, paths or credentials.
        reason = str(error) if type(error) is RuntimeError else type(error).__name__
        allowed = {'candidate_mismatch', 'fixture_already_exists_preserve_it', 'close_test_account_apps',
            'state_already_exists_preserve_it', 'target_prepare_failed', 'target_prove_failed',
            'helper_exited', 'helper_start_timeout', 'helper_needs_review', 'scope_changed',
            'transfer_finished_before_stop_probe', 'stop_not_observed', 'skills_export_failed',
            'observation_timeout_preserve_helper', 'review_required', 'wrong_account'}
        extra = {}
        if engine is not None and engine.poll() is None:
            try:
                extra['diagnostic'] = h.shared_diagnostic(status())
            except Exception:
                extra['diagnostic_unavailable'] = True
        update('needs_review', failed_phase=report['phase'], reason=reason if reason in allowed else 'unexpected_error', **extra)
        return 1
    return 0


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == '--remote' and sys.argv[3] == '--apply':
        try:
            print(json.dumps(remote_action(sys.argv[2])))
        except Exception:
            print('{"needs_review": true}')
            sys.exit(1)
    elif sys.argv[1:] == ['--apply', '--background']:
        account(SOURCE)
        subprocess.Popen(['/usr/bin/python3', '-I', str(Path(__file__).resolve()), '--apply'],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
    elif sys.argv[1:] == ['--apply']:
        sys.exit(driver())
    else:
        sys.exit(2)
