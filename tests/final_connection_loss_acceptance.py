"""Drop only this run's rsync SSH child, restart helper, resume real staging.

Does not switch interfaces, stop SSH servers, replace destination data, or
represent a physical Wi-Fi/cable-removal test. Uses existing synthetic files.
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
NAME = 'Codex-Migrate-Linkloss-20260907'


def require(value, reason='verification_failed'):
    if not value:
        raise RuntimeError(reason)


def transfer_ssh(rows, engine, uid):
    """Select only ssh directly parented by this helper's own rsync process."""
    processes = {}
    for line in rows.splitlines():
        parts = line.strip().split(None, 3)
        if len(parts) == 4 and all(x.isdigit() for x in parts[:3]):
            pid, parent, owner = map(int, parts[:3])
            processes[pid] = (parent, owner, Path(parts[3]).name)
    if processes.get(engine, (None, None, None))[1:] != (uid, 'codex-migrate-engine'):
        return None
    matches = []
    for pid, (parent, owner, name) in processes.items():
        if owner != uid or name != 'ssh':
            continue
        rsync = processes.get(parent)
        if rsync and rsync == (engine, uid, 'rsync'):
            matches.append(pid)
    return matches[0] if len(matches) == 1 else None


def load_resources():
    path = SHARED / 'final_recovery_acceptance.py'
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == pwd.getpwnam('jsegeren').pw_uid
            and not info.st_mode & 0o022, 'unsafe_harness')
    spec = importlib.util.spec_from_file_location('recovery_harness', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.load_resources()


def driver():
    resources, f = load_resources()
    f.account(f.SOURCE)
    f.closed()
    h = f.load_handoff()
    f.safe_dir(f.PUBLIC, os.getuid())
    state = f.SOURCE / '.local/state/codex-migrate-linkloss-20260907'
    require(not os.path.lexists(state), 'existing_state_preserve_it')
    state.mkdir(mode=0o700)
    report = {'phase': 'preflight', 'runner_pid': os.getpid(), 'build': 5,
              'full_finalization_attempted': False, 'physical_disconnect_tested': False}
    def update(phase, **extra):
        report.update(phase=phase, updated_at=time.time(), **extra)
        h.save(f.PUBLIC / 'final-connection-loss.json', report, public=True)
    engine = None
    try:
        update('preflight')
        require(hashlib.sha256(f.ARCHIVE.read_bytes()).hexdigest() == f.ARCHIVE_HASH, 'candidate_mismatch')
        h.ENGINE = f.ENGINE
        h.verify_shared_candidate()
        workspace = f.SOURCE / f.NAME
        f.safe_dir(workspace, os.getuid())
        require((workspace / 'transfer-fixture.bin').stat().st_size == 256 * 1024 * 1024)
        reply, options, identity, known = h.connection()
        def remote(staged=False):
            # Existing fixture proof also verifies retained target Codex data.
            body = 'proof=remote_action("prove")\nstaging=TARGET/' + repr(NAME + '-Staging') + '\n'
            if staged:
                body += ('safe_dir(staging,os.getuid())\nsize=0\n'
                         'for folder,dirs,files in os.walk(staging,followlinks=False):\n'
                         ' for name in files:\n'
                         '  info=(Path(folder)/name).lstat()\n'
                         '  if stat.S_ISREG(info.st_mode): size+=info.st_size\n'
                         'require(size>0)\nproof["retained_staging_bytes"]=size\n')
            else:
                body += 'require(not os.path.lexists(staging))\n'
            code = resources['final_device'].split("\nif __name__ == '__main__':")[0]
            process = subprocess.run(['/usr/bin/ssh', *options, reply['target'], '/usr/bin/python3 -I -'],
                input=code + '\n' + body + 'print(json.dumps(proof))\n', text=True,
                capture_output=True, timeout=180)
            require(process.returncode == 0 and len(process.stdout) < 2048, 'target_check_failed')
            return json.loads(process.stdout)
        remote()
        args = [str(f.ENGINE), 'serve', '--apply', '--source-home', str(f.SOURCE),
                '--target', reply['target'], '--target-home', str(f.TARGET),
                '--workspace', str(workspace), '--identity-file', str(identity),
                '--known-hosts-file', str(known), '--host-key-alias', 'codex-migrate-' + reply['id'],
                '--state-dir', str(state), '--staging-name', NAME + '-Staging', '--port', '0', '--no-open']
        def launch():
            process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, start_new_session=True)
            for _ in range(100):
                require(process.poll() is None, 'helper_exited')
                try:
                    port = h.listener(process.pid)
                    token = h.checked(state / 'control-token').read_text().strip()
                    return process, port, token
                except (OSError, h.SafeError):
                    time.sleep(0.2)
            raise RuntimeError('helper_start_timeout')
        engine, port, token = launch()
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
                time.sleep(0.1)
            raise RuntimeError('observation_timeout_preserve_helper')
        update('inspecting', helper_pid=engine.pid)
        action('inspect')
        wait(lambda s: s.get('status') == 'ready', 180)
        action('start')
        update('waiting_for_workspace_ssh')
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            current = status()
            require(current.get('status') not in {'failed', 'interrupted', 'ready_to_finalize'}, 'missed_drop_window')
            if current.get('phase') == 'staging' and str(current.get('current_item', '')).startswith('Workspace'):
                def selected():
                    snapshot = subprocess.run(['/bin/ps', '-axo', 'pid=,ppid=,uid=,comm='],
                                              capture_output=True, text=True, timeout=10)
                    require(snapshot.returncode == 0)
                    return transfer_ssh(snapshot.stdout, engine.pid, os.getuid())
                pid = selected()
                if pid and engine.poll() is None and selected() == pid:
                    migration_id = current['migration_id']
                    os.kill(pid, signal.SIGKILL)
                    break
            time.sleep(0.03)
        else:
            raise RuntimeError('missed_drop_window')
        failed = wait(lambda s: s.get('status') in {'failed', 'interrupted'}, 180)
        require(not failed.get('receipt') and failed['migration_id'] == migration_id)
        proof = remote(True)
        update('unexpected_disconnect_observed', ssh_child_killed=True,
               helper_reported_failure=True, **proof)
        engine.send_signal(signal.SIGINT)
        engine.wait(timeout=30)
        engine, port, token = launch()
        require(status()['migration_id'] == migration_id, 'scope_changed')
        update('resuming_after_helper_restart', restarted_helper_pid=engine.pid)
        action('resume')
        staged = wait(lambda s: s.get('status') in {'ready_to_finalize', 'failed', 'interrupted'})
        require(staged.get('status') == 'ready_to_finalize' and staged['migration_id'] == migration_id
                and not staged.get('receipt'), 'resume_failed')
        proof = remote(True)
        engine.send_signal(signal.SIGINT)
        engine.wait(timeout=30)
        update('passed', resumed_same_migration=True, helper_restart_verified=True,
               destination_not_finalized=True, **proof)
    except Exception as error:
        allowed = {'candidate_mismatch', 'target_check_failed', 'helper_exited',
                   'helper_start_timeout', 'missed_drop_window', 'scope_changed', 'resume_failed',
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
