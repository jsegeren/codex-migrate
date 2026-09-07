"""One-shot browser skills repair, isolated from genuine retained Codex data."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import signal
import stat
import subprocess
import sys
import time

SHARED = Path('/Users/Shared/CodexMigrate-Authentic-20260906')
NAME = 'Codex-Migrate-BrowserSkills-20260907'
SKILL = '.agents/skills/browser-device-check/SKILL.md'
NEW = '---\nname: browser-device-check\ndescription: Disposable browser acceptance skill.\n---\nNew browser test skill.\n'
OLD = 'Original disposable browser test skill.\n'


def require(value):
    if not value:
        raise RuntimeError('check_failed')


def load_resources():
    path = SHARED / 'final_recovery_acceptance.py'
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == pwd.getpwnam('jsegeren').pw_uid and not info.st_mode & 0o022)
    spec = importlib.util.spec_from_file_location('recovery_fixture', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.load_resources()


def driver():
    resources, f = load_resources()
    f.account(f.SOURCE)
    f.closed()
    h = f.load_handoff()
    f.safe_dir(f.PUBLIC, os.getuid())
    root = f.SOURCE / NAME
    require(not os.path.lexists(root))
    root.mkdir(mode=0o700)
    skill = root / SKILL
    skill.parent.mkdir(parents=True, mode=0o700)
    skill.write_text(NEW)
    report = {'phase': 'preflight', 'runner_pid': os.getpid(), 'build': 5,
              'full_migration_selected': False}
    def update(phase, **extra):
        report.update(phase=phase, updated_at=time.time(), **extra)
        h.save(f.PUBLIC / 'final-skills-browser.json', report, public=True)
    engine = None
    try:
        update('preflight')
        require(hashlib.sha256(f.ARCHIVE.read_bytes()).hexdigest() == f.ARCHIVE_HASH)
        h.ENGINE = f.ENGINE
        h.verify_shared_candidate()
        reply, options, _, _ = h.connection()
        def remote(prove=False):
            code = resources['final_device'].split("\nif __name__ == '__main__':")[0]
            body = '\nproof=remote_action("prove")\nroot=TARGET/' + repr(NAME) + '\nskill=root/' + repr(SKILL) + '\n'
            if not prove:
                body += ('require(not os.path.lexists(root))\nroot.mkdir(mode=0o700)\n'
                    'skill.parent.mkdir(parents=True,mode=0o700)\nskill.write_text(' + repr(OLD) + ')\n'
                    '(root/"outside.txt").write_text("Keep outside the skills selection.")\n')
            else:
                body += ('safe_dir(root,os.getuid())\nrequire(skill.read_text()==' + repr(NEW) + ')\n'
                    'require((root/"outside.txt").read_text()=="Keep outside the skills selection.")\n'
                    'proof.update(browser_skill_updated=True,outside_file_preserved=True)\n')
            result = subprocess.run(['/usr/bin/ssh', *options, reply['target'], '/usr/bin/python3 -I -'],
                input=code + body + 'print(json.dumps(proof))\n', text=True, capture_output=True, timeout=180)
            require(result.returncode == 0 and len(result.stdout) < 2048)
            return json.loads(result.stdout)
        remote()
        # Reuse its existing accepted pairing in place; do not copy credentials.
        # Registry keys isolate each distinct scope and preserve prior migrations.
        state = f.SOURCE / '.local/state/codex-migrate-browser'
        h.checked(state, directory=True)
        engine = subprocess.Popen([str(f.ENGINE), 'launch', '--source-home', str(f.SOURCE),
            '--state-dir', str(state), '--port', '0', '--no-open'], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        for _ in range(100):
            require(engine.poll() is None)
            try:
                port = h.listener(engine.pid)
                token = h.checked(state / 'control-token').read_text().strip()
                break
            except (OSError, h.SafeError):
                time.sleep(0.2)
        else:
            raise RuntimeError('helper_start_failed')
        update('browser_workflow', helper_pid=engine.pid)
        process = subprocess.Popen(['/Users/jsegeren/.nvm/versions/node/v24.19.0/bin/node',
            str(SHARED / 'final_skills_browser.js'), '--apply'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True)
        output, _ = process.communicate(input=json.dumps({'port': port, 'token': token,
            'workspace': str(root)}).encode(), timeout=600)
        browser = json.loads(output)
        require(len(output) < 4096)
        if not browser.get('passed'):
            update('needs_review', browser=browser)
            return 1
        require(process.returncode == 0)
        proof = remote(True)
        engine.send_signal(signal.SIGINT)
        engine.wait(timeout=30)
        update('passed', browser=browser, **proof)
    except Exception:
        update('needs_review', failed_phase=report['phase'])
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
