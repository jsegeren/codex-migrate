"""Private two-Mac acceptance runner. Never installed in the customer app.

Run only as codexmigratesource. The existing pinned test-account connection is
reused; no account password or Codex credential is read, copied or logged.
The recipient receives this same fixed program, not an arbitrary-command queue.
"""
import argparse
import base64
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import queue
import re
import shlex
import signal
import stat
import subprocess
import tempfile
import threading
import time
import urllib.request
import uuid

SOURCE = Path('/Users/codexmigratesource')
TARGET = Path('/Users/codexmigratetarget')
SHARED = Path('/Users/Shared/CodexMigrate-Authentic-20260906')
PUBLIC = Path('/Users/Shared/CodexMigrate-Authentic-Status-20260906')
STATE_NAME = '.codex-migrate-authentic-test-20260906'
WORKSPACE_NAME = 'Authentic-Migration-Test'
HOST = 'SHA256:uWR56FSP0RUbcQX8a+t/rsClg4/oYC73zSoFz4Q8r5c'
LEGACY_ENGINE = SHARED / 'Codex Migrate.app/Contents/Resources/engine/codex-migrate-engine'
ENGINE = SHARED / 'isolated-candidate/Codex Migrate.app/Contents/Resources/engine/codex-migrate-engine'
MIGRATION_STATE = 'migration-isolated'
RUNTIME_RECORD = 'runtime-isolated.json'
STAGING_NAME = 'Codex-Migrate-Authentic-Staging-20260906'


class SafeError(RuntimeError):
    """Only fixed operator-facing diagnostics; never a subprocess error body."""


TURN_ERROR_CODES = frozenset({
    'contextWindowExceeded', 'sessionBudgetExceeded', 'usageLimitExceeded',
    'rateLimitExceeded', 'serverOverloaded', 'cyberPolicy',
    'misalignmentPolicyViolation', 'internalServerError', 'unauthorized',
    'badRequest', 'threadRollbackFailed', 'sandboxError', 'other',
})
TURN_HTTP_ERRORS = frozenset({
    'httpConnectionFailed', 'responseStreamConnectionFailed',
    'responseStreamDisconnected', 'responseTooManyFailedAttempts',
})


def turn_failure(turn):
    """Map protocol fields to bounded diagnostics, never provider error text."""
    if not isinstance(turn, dict):
        return 'Codex turn failed; error category unavailable'
    if turn.get('status') == 'interrupted':
        return 'Codex test turn was interrupted'
    error = turn.get('error')
    code = error.get('codexErrorInfo') if isinstance(error, dict) else None
    if isinstance(code, str) and code in TURN_ERROR_CODES:
        return 'Codex turn failed: ' + code
    if isinstance(code, dict) and len(code) == 1:
        name = next(iter(code))
        detail = code[name]
        if name in TURN_HTTP_ERRORS and isinstance(detail, dict):
            status = detail.get('httpStatusCode')
            suffix = (' (HTTP ' + str(status) + ')'
                      if type(status) is int and 100 <= status <= 599 else '')
            return 'Codex turn failed: ' + name + suffix
    return 'Codex turn failed; error category unavailable'


def model_selection(app, pinned=None):
    """Choose the advertised default once; never fall back after a failed turn."""
    entries, cursor = [], None
    for _ in range(5):
        params = {'limit': 100, 'includeHidden': False}
        if cursor is not None:
            params['cursor'] = cursor
        page = app.call('model/list', params)
        require(isinstance(page, dict) and isinstance(page.get('data'), list), 'Invalid model catalog')
        entries.extend(page['data'])
        cursor = page.get('nextCursor')
        if cursor is None:
            break
        require(isinstance(cursor, str) and len(cursor) <= 4096, 'Invalid model catalog cursor')
    else:
        raise SafeError('Model catalog pagination limit reached')
    if pinned is not None:
        require(isinstance(pinned, dict) and set(pinned) == {'model', 'effort'}, 'Invalid pinned test model')
    candidates = [item for item in entries if isinstance(item, dict) and item.get('hidden') is not True
                  and (item.get('model') == pinned['model'] if pinned else item.get('isDefault') is True)]
    require(len(candidates) == 1, 'No unique available test model; no automatic fallback')
    item = candidates[0]
    model = item.get('model')
    effort = pinned['effort'] if pinned else item.get('defaultReasoningEffort')
    require(isinstance(model, str) and re.fullmatch(r'[a-zA-Z0-9_.-]{1,100}', model) is not None
            and model != 'gpt-5', 'Unsupported default test model; no automatic fallback')
    require(effort in ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra')
            and any(isinstance(value, dict) and value.get('reasoningEffort') == effort
                    for value in item.get('supportedReasoningEfforts', [])), 'Unsupported test reasoning effort')
    return {'model': model, 'effort': effort}


def unsupported_legacy_fixture(turn, marker):
    """Only the observed, rejected pre-fix request is eligible for one repair."""
    if not isinstance(turn, dict) or turn.get('status') != 'failed':
        return False
    error = turn.get('error')
    if not isinstance(error, dict) or error.get('codexErrorInfo') != 'other':
        return False
    message = error.get('message')
    try:
        body = json.loads(message)
        message = body.get('error', {}).get('message') if body.get('status') == 400 else None
    except (TypeError, ValueError, AttributeError):
        pass
    expected = "The 'gpt-5' model is not supported when using Codex with a ChatGPT account."
    if message != expected:
        return False
    items = turn.get('items')
    prompt = 'Remember this test marker: ' + marker + '. Reply only with that marker.'
    return (isinstance(items, list) and len(items) == 1 and isinstance(items[0], dict)
            and items[0].get('type') == 'userMessage'
            and items[0].get('content') == [{'type': 'text', 'text': prompt, 'text_elements': []}])


def require(ok, message):
    if not ok:
        raise SafeError(message)


def account(role):
    expected = SOURCE if role == 'source' else TARGET
    user = pwd.getpwuid(os.getuid())
    require(os.getuid() == os.geteuid() != 0 and user.pw_name == expected.name
            and user.pw_dir == str(expected), 'Run in the disposable ' + role + ' account')
    require(not expected.is_symlink() and expected.stat().st_uid == os.getuid(), 'Unsafe home')
    return expected


def checked(path, directory=False, private=True):
    info = path.lstat()
    require((stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
            and info.st_uid == os.getuid()
            and not info.st_mode & (0o077 if private else 0o022), 'Unsafe test path')
    return path


def root_for(home):
    root = home / STATE_NAME
    root.mkdir(mode=0o700, exist_ok=True)
    return checked(root, directory=True)


def save(path, data, public=False):
    # Atomic replacement in an already checked owner-controlled directory.
    descriptor, temporary = tempfile.mkstemp(prefix='.receipt-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(data, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o644 if public else 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read(path):
    return json.loads(checked(path).read_text())


def run(command, timeout=30, **kwargs):
    result = subprocess.run(command, capture_output=True, timeout=timeout, **kwargs)
    require(result.returncode == 0, 'Subprocess failed (' + Path(command[0]).name
            + '; exit ' + str(result.returncode) + '); raw output withheld')
    return result.stdout


def verify_shared_candidate():
    """Check public artifact access before asking another account to run it."""
    app = SHARED / 'isolated-candidate/Codex Migrate.app'
    message = 'Shared test package permissions need repair; no migration started'
    try:
        for folder in (SHARED, app.parent, app):
            info = folder.lstat()
            require(stat.S_ISDIR(info.st_mode) and info.st_mode & 0o005 == 0o005,
                    message)
        def traversal_error(error):
            raise error
        for folder, directories, files in os.walk(app, followlinks=False, onerror=traversal_error):
            for path in [Path(folder)] + [Path(folder) / name for name in directories + files]:
                info = path.lstat()
                if stat.S_ISLNK(info.st_mode):
                    continue  # codesign verifies bundle links below.
                needed = 0o005 if stat.S_ISDIR(info.st_mode) else 0o004
                require(info.st_mode & needed == needed, message)
        require(ENGINE.is_file() and ENGINE.stat().st_mode & 0o005 == 0o005, message)
    except OSError:
        raise SafeError(message) from None
    run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)])


def processes():
    output = run(['/bin/ps', '-U', str(os.getuid()), '-o', 'pid=,comm=']).decode()
    return [(int(parts[0]), parts[1]) for line in output.splitlines()
            if len(parts := line.strip().split(None, 1)) == 2]


def codex_closed():
    names = {'Codex', 'ChatGPT', 'codex', 'codex-cli', 'codex_chronicle'}
    return not any(Path(command).name in names for _, command in processes())


def codex_binary():
    for app in ('/Applications/ChatGPT.app', '/Applications/Codex.app'):
        path = Path(app) / 'Contents/Resources/codex'
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    raise SafeError('Codex application is not installed in Applications')


def prepare(home, role):
    """Adopt the marked test account in place; never reset a completed login."""
    root = root_for(home)
    journal = root / 'preparation.json'
    if journal.exists():
        record = read(journal)
        require(record == {'role': role, 'phase': 'prepared'}, 'Preparation needs review')
        return
    require(codex_closed(), 'Quit Codex in the disposable ' + role + ' account first')
    require(not (home / '.codex-migrate-transaction.json').exists(), 'Pending recovery needs review')
    marker_name = ('.codex-migrate-acceptance-fixture.json' if role == 'source'
                   else '.codex-migrate-destination-fixture.json')
    marker = json.loads(checked(home / marker_name, private=False).read_text())
    require(marker.get('synthetic') is True, 'Disposable fixture marker missing')
    # The user may sign in before launching this program. Retain all existing
    # state, including earlier synthetic fixtures, and create genuine test
    # conversations alongside it. Never move, read or copy credential files.
    # Codex itself can create a 755 root; reject writable-by-others roots rather
    # than requiring a permission change just to run this test.
    current = home / '.codex'
    current.mkdir(mode=0o700, exist_ok=True)
    checked(current, directory=True, private=False)
    save(journal, {'role': role, 'phase': 'prepared'})


class AppServer:
    def __init__(self, cwd):
        # No inherited API keys, provider configuration or personal credentials.
        env = {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'LANG': 'en_US.UTF-8',
               'TMPDIR': tempfile.gettempdir()}
        self.process = subprocess.Popen([codex_binary(), 'app-server', '--stdio'],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, cwd=cwd, env=env,
                                        start_new_session=True)
        self.events = queue.Queue(maxsize=2048)
        self.completed = []
        self.serial = 0
        threading.Thread(target=self._read, daemon=True).start()
        try:
            self.call('initialize', {'clientInfo': {'name': 'codex_migrate_acceptance',
                      'version': '1.0'}, 'capabilities': {'experimentalApi': False}})
            self.send({'method': 'initialized'})
        except Exception:
            self.close()
            raise

    def _read(self):
        try:
            while True:
                line = self.process.stdout.readline(2 * 1024 * 1024)
                if not line:
                    break
                require(len(line) < 2 * 1024 * 1024, 'Oversized protocol message')
                self.events.put(json.loads(line), timeout=1)
        except Exception:
            pass
        finally:
            with contextlib.suppress(queue.Full):
                self.events.put_nowait(None)

    def send(self, message):
        self.process.stdin.write((json.dumps(message) + '\n').encode())
        self.process.stdin.flush()

    def receive(self, deadline):
        try:
            event = self.events.get(timeout=max(0.01, deadline - time.monotonic()))
        except queue.Empty:
            raise SafeError('Codex protocol timed out') from None
        require(event is not None, 'Codex process ended unexpectedly')
        if 'method' in event and 'id' in event:
            self.send({'id': event['id'], 'error': {'code': -32601,
                       'message': 'Acceptance fixture does not approve tools or permissions'}})
            raise SafeError('Unexpected tool/permission request')
        return event

    def call(self, method, params):
        self.serial += 1
        identifier = self.serial
        self.send({'id': identifier, 'method': method, 'params': params})
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            event = self.receive(deadline)
            if event.get('id') == identifier:
                require('error' not in event, 'Codex rejected ' + method)
                return event['result']
            if event.get('method') == 'turn/completed':
                self.completed.append(event)
        raise SafeError('Codex request timed out')

    def signed_in(self):
        value = self.call('account/read', {'refreshToken': False}).get('account')
        return isinstance(value, dict) and value.get('type') == 'chatgpt'

    def turn(self, identifier, prompt, selection=None):
        params = {'threadId': identifier,
                  'input': [{'type': 'text', 'text': prompt, 'text_elements': []}]}
        if selection is not None:
            params.update(selection)
        response = self.call('turn/start', params)
        turn_id = response['turn']['id']
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            event = self.completed.pop(0) if self.completed else self.receive(deadline)
            if event.get('method') == 'turn/completed':
                params = event['params']
                if params.get('threadId') == identifier and params['turn']['id'] == turn_id:
                    require(params['turn']['status'] == 'completed', turn_failure(params['turn']))
                    return
        raise SafeError('Codex test turn timed out')

    def close(self):
        if self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGTERM)
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(timeout=5)
        self.process.stdin.close()
        self.process.stdout.close()


@contextlib.contextmanager
def server(home):
    instance = None
    try:
        instance = AppServer(home)
        yield instance
    finally:
        if instance:
            instance.close()


def login_ready(home):
    if not codex_closed():
        return False
    # Presence only. Codex owns and validates the credential contents.
    if not all((home / '.codex' / name).is_file() for name in ('auth.json', 'installation_id')):
        return False
    with server(home) as app:
        return app.signed_in()


def fixture_threads(home):
    root = root_for(home)
    manifest = root / 'threads.json'
    records = read(manifest) if manifest.exists() else []
    require(isinstance(records, list) and len(records) <= 3, 'Invalid fixture receipt')
    workspace = home / WORKSPACE_NAME
    if not workspace.exists():
        workspace.mkdir(mode=0o700)
        run(['/usr/bin/git', 'init', '-q', str(workspace)])
        (workspace / 'README.md').write_text('Disposable Codex migration acceptance project.\n')
        run(['/usr/bin/git', '-C', str(workspace), 'add', 'README.md'])
        run(['/usr/bin/git', '-C', str(workspace), '-c', 'user.name=Migration Test',
             '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'Fixture baseline'])
        run(['/usr/bin/git', '-C', str(workspace), 'switch', '-c', 'acceptance/unfinished'])
        (workspace / 'README.md').write_text('Disposable project with an uncommitted edit.\n')
        (workspace / 'unfinished.txt').write_text('Preserve this untracked test work.\n')
    checked(workspace, directory=True)
    with server(home) as app:
        require(app.signed_in(), 'Sign into Codex with ChatGPT in the source test account')
        selection = None
        def selected_model():
            nonlocal selection
            if selection is None:
                path = root / 'model.json'
                selection = model_selection(app, read(path) if path.exists() else None)
                save(path, selection)
            return selection
        for index, kind in enumerate(('project', 'loose', 'archived')):
            if index < len(records):
                if records[index].get('complete') is not True:
                    # Read only the exact fixture recorded before the failure.
                    # The only retry is the exactly matched, rejected legacy
                    # gpt-5 request below. Never edit Codex's storage directly.
                    record = records[index]
                    require(isinstance(record.get('id'), str)
                            and re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', record['id']) is not None
                            and record.get('kind') == kind
                            and isinstance(record.get('marker'), str)
                            and re.fullmatch(r'migration-fixture-[a-f0-9]{32}', record['marker']) is not None,
                            'Partial conversation receipt needs review')
                    history = app.call('thread/read', {'threadId': record['id'], 'includeTurns': True})
                    thread = history.get('thread') if isinstance(history, dict) else None
                    require(isinstance(thread, dict) and thread.get('id') == record['id'],
                            'Partial conversation response needs review')
                    turns = thread.get('turns')
                    if (index == 0 and len(records) == 1 and isinstance(turns, list) and len(turns) == 1
                            and 'model' not in record and 'model_repair_attempted' not in record
                            and unsupported_legacy_fixture(turns[0], record['marker'])):
                        chosen = selected_model()
                        record.update(model=chosen, model_repair_attempted=True)
                        save(manifest, records)  # Bound repair before any model request.
                        resumed = app.call('thread/resume', {'threadId': record['id'], 'model': chosen['model'],
                                           'approvalPolicy': 'never', 'sandbox': 'read-only'})
                        require(resumed.get('model') == chosen['model'], 'Codex did not honor the test model pin')
                        app.turn(record['id'], 'Remember this test marker: ' + record['marker']
                                 + '. Reply only with that marker.', chosen)
                        record['complete'] = True
                        save(manifest, records)
                        continue
                    if isinstance(turns, list) and turns and isinstance(turns[-1], dict):
                        if turns[-1].get('status') in ('failed', 'interrupted'):
                            raise SafeError(turn_failure(turns[-1]))
                    raise SafeError('Partial conversation needs review; no automatic model retry')
                continue
            marker = 'migration-fixture-' + uuid.uuid4().hex
            chosen = selected_model()
            response = app.call('thread/start', {'cwd': str(workspace if kind == 'project' else home),
                'model': chosen['model'],
                'approvalPolicy': 'never', 'sandbox': 'read-only', 'ephemeral': False,
                'baseInstructions': 'This is a tiny migration test. Reply without using any tools.'})
            require(response.get('model') == chosen['model'], 'Codex did not honor the test model pin')
            identifier = response['thread']['id']
            record = {'id': identifier, 'kind': kind, 'marker': marker, 'complete': False, 'model': chosen}
            records.append(record)
            save(manifest, records)
            app.call('thread/name/set', {'threadId': identifier, 'name': 'Migration test: ' + kind})
            app.turn(identifier, 'Remember this test marker: ' + marker + '. Reply only with that marker.', chosen)
            if kind == 'archived':
                app.call('thread/archive', {'threadId': identifier})
            record['complete'] = True
            save(manifest, records)
    return records


def prove_threads(home, records):
    require(isinstance(records, list) and len(records) == 3, 'Expected three test conversations')
    with server(home) as app:
        require(app.signed_in(), 'Destination must retain its ChatGPT sign-in')
        chosen = model_selection(app, records[0].get('model'))
        require(all(item.get('model') == chosen for item in records), 'Test model pin mismatch')
        for item in records:
            require(re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', item['id']) is not None,
                    'Invalid test thread ID')
            require(re.fullmatch(r'migration-fixture-[a-f0-9]{32}', item['marker']) is not None,
                    'Invalid test marker')
            history = app.call('thread/read', {'threadId': item['id'], 'includeTurns': True})
            require(item['marker'] in json.dumps(history), 'Original conversation content missing')
            before_turns = len(history['thread']['turns'])
            if item['kind'] == 'archived':
                app.call('thread/unarchive', {'threadId': item['id']})
            resumed = app.call('thread/resume', {'threadId': item['id'],
                                               'model': chosen['model'],
                                               'approvalPolicy': 'never', 'sandbox': 'read-only'})
            require(resumed.get('model') == chosen['model'], 'Codex did not honor the test model pin')
            app.turn(item['id'], 'What test marker did I ask you to remember? Reply only with it. No tools.', chosen)
            updated = app.call('thread/read', {'threadId': item['id'], 'includeTurns': True})
            turns = updated['thread']['turns']
            require(len(turns) > before_turns and any(
                value.get('type') == 'agentMessage' and item['marker'] in value.get('text', '')
                for value in turns[-1].get('items', [])), 'Conversation continuation failed')
            if item['kind'] == 'archived':
                app.call('thread/archive', {'threadId': item['id']})
    return {'app_server_reopened_and_continued': 3, 'desktop_visual_check': 'not_yet_performed'}


def connection():
    folder = SOURCE / '.local/state/codex-migrate-browser/connection'
    # Check each in-home ancestor before opening the owner-only pairing record.
    cursor = SOURCE
    for part in folder.relative_to(SOURCE).parts:
        cursor /= part
        checked(cursor, directory=True, private=False)
    value = checked(folder / 'accepted.json').read_text().strip()
    require(value.startswith('CM-CONNECT-1:') and len(value) <= 8192, 'Invalid pairing')
    reply = json.loads(base64.urlsafe_b64decode(value.split(':', 1)[1]))
    require(reply['kind'] == 'accepted' and reply['home'] == str(TARGET)
            and re.fullmatch(r'codexmigratetarget@[A-Za-z0-9][A-Za-z0-9.-]*', reply['target'])
            and re.fullmatch(r'[a-f0-9]{32}', reply['id']), 'Wrong paired account')
    fingerprint = 'SHA256:' + base64.b64encode(hashlib.sha256(
        base64.b64decode(reply['host_key'].split()[1])).digest()).decode().rstrip('=')
    require(fingerprint == HOST, 'Wrong pinned Mac')
    identity, known = checked(folder / 'identity'), checked(folder / 'known_hosts')
    options = ['-F', '/dev/null', '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
               '-o', 'IdentityAgent=none', '-o', 'StrictHostKeyChecking=yes',
               '-o', 'ConnectTimeout=10', '-o', 'GlobalKnownHostsFile=/dev/null',
               '-o', 'UserKnownHostsFile=' + str(known),
               '-o', 'HostKeyAlias=codex-migrate-' + reply['id'], '-i', str(identity)]
    return reply, options, identity, known


def remote(options, target, action, payload=None):
    require(action in ('prepare', 'ready', 'prove', 'diagnose'), 'Unsupported remote action')
    code = Path(__file__).read_text()
    command = ['/usr/bin/ssh', *options, target,
               '/usr/bin/python3 - ' + shlex.quote('--remote-action=' + action)]
    # Only fixed test actions and invented test-thread metadata cross the wire.
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    command[-1] += ' --payload=' + shlex.quote(encoded)
    result = subprocess.run(command, timeout=720 if action == 'prove' else 90,
                            input=code.encode(), capture_output=True)
    require(result.returncode != 255, 'Destination SSH connection failed; pairing and network need review')
    try:
        response = json.loads(result.stdout)
    except (ValueError, UnicodeError):
        raise SafeError('Destination ' + action + ' returned no valid report (exit '
                        + str(result.returncode) + '); raw output withheld') from None
    require(isinstance(response, dict), 'Destination returned an invalid report')
    if 'error' in response:
        # Only program-defined diagnostics may cross into the public report.
        # Never reflect arbitrary remote output or an exception body.
        allowed = {
            'Quit Codex in the disposable target account first',
            'Destination migration helper must be idle and closed',
            'Codex application is not installed in Applications',
            'Unsafe test path', 'Unsafe home',
            'Run in the disposable target account',
            'Pending recovery needs review', 'Disposable fixture marker missing',
            'Preparation needs review',
        }
        message = response['error']
        raise SafeError(message if isinstance(message, str) and message in allowed
                        else 'Destination ' + action + ' needs review; private details withheld')
    require(result.returncode == 0, 'Destination ' + action + ' failed (exit '
            + str(result.returncode) + '); raw output withheld')
    return response


def staging_diagnostic(home, migration_id):
    """Read only fixed staging metadata; never adopt, remove or unlock it."""
    require(isinstance(migration_id, str)
            and re.fullmatch(r'[a-f0-9]{32}', migration_id), 'Invalid test migration reference')
    staging = home / 'Codex-Migrate-Staging'
    result = {'staging': 'missing', 'pending_recovery':
              os.path.lexists(home / '.codex-migrate-transaction.json')}
    if not os.path.lexists(staging):
        return result
    try:
        checked(staging, directory=True)
        descriptor = os.open(staging / '.codex-migrate-owner',
                             os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor) as stream:
            info = os.fstat(stream.fileno())
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                    and info.st_nlink == 1 and not info.st_mode & 0o077
                    and info.st_size <= 64, 'Unsafe test path')
            owner = stream.read(128).strip()
        if not re.fullmatch(r'[a-f0-9]{32}', owner):
            result['staging'] = 'invalid_owner_marker'
        else:
            result['staging'] = 'matching_owner' if owner == migration_id else 'different_owner'
    except FileNotFoundError:
        result['staging'] = 'missing_owner_marker'
    except (OSError, SafeError, UnicodeError):
        result['staging'] = 'unsafe_or_unreadable'
    return result


def diagnose():
    """Observe the failed test without restarting any app, transfer or model."""
    home = account('source')
    root = checked(home / STATE_NAME, directory=True)
    state_root = checked(root / 'migration', directory=True)
    state = read(state_root / 'state.json')
    require(isinstance(state, dict), 'Invalid test state')
    reply, options, _, _ = connection()
    result = remote(options, reply['target'], 'diagnose', state.get('migration_id'))
    # A compromised/malformed remote reply must not become a public data export.
    staging = result.get('staging')
    require(staging in ('missing', 'matching_owner', 'different_owner',
                       'invalid_owner_marker', 'missing_owner_marker', 'unsafe_or_unreadable')
            and type(result.get('pending_recovery')) is bool, 'Invalid diagnostic response')
    error = state.get('error')
    known_errors = {
        'remote command failed': 'remote_command_failed_without_details',
        'Cannot safely lock the destination. No migration data was changed; contact support.':
            'destination_lock_validation_failed',
        'Planning mode is read-only; restart with --apply to transfer': 'changes_disabled',
    }
    report = {'checked_at': time.time(), 'read_only': True,
              'failed_before_copy': state.get('status') == 'failed'
                  and state.get('phase') == 'preflight_complete',
              'error_code': known_errors.get(error, 'unclassified_private_error')
                  if isinstance(error, str) else 'unclassified_private_error',
              'staging': staging, 'pending_recovery': result['pending_recovery']}
    checked(PUBLIC, directory=True, private=False)
    save(PUBLIC / 'staging-diagnostic.json', report, public=True)
    print('Read-only diagnostic saved. No transfer, account or backup was changed.')


def api(port, token, path, payload=None):
    request = urllib.request.Request('http://127.0.0.1:' + str(port) + path,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={'X-Codex-Migrate-Token': token, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def listener(pid):
    output = run(['/usr/sbin/lsof', '-nP', '-a', '-p', str(pid), '-iTCP', '-sTCP:LISTEN', '-Fn']).decode()
    ports = re.findall(r'^n127\.0\.0\.1:(\d+)$', output, re.M)
    require(len(ports) == 1, 'Expected one loopback listener')
    return int(ports[0])


def stop_old_helper():
    helpers = [(pid, cmd) for pid, cmd in processes() if Path(cmd).name == 'codex-migrate-engine']
    require(len(helpers) <= 1, 'Multiple migration helpers require review')
    for pid, command in helpers:
        if command == str(ENGINE):
            state_root = root_for(SOURCE)
            require(read(state_root / RUNTIME_RECORD).get('pid') == pid, 'Unknown test helper process')
            token = checked(state_root / MIGRATION_STATE / 'control-token').read_text().strip()
            current = api(listener(pid), token, '/api/status')
            require(current.get('status') in ('idle', 'ready', 'ready_to_finalize', 'complete', 'needs_attention')
                    and current.get('phase') not in ('restoring', 'restored', 'recovery_required')
                    and current.get('git_verification', {}).get('status') != 'checking'
                    and current.get('path_compatibility', {}).get('status') != 'checking',
                    'Existing test migration needs observation; leave its helper running')
            return  # Attach only after it is safe to inspect Codex state again.
        require(command.startswith('/Users/Shared/CodexMigrateAcceptance-'), 'Unknown helper')
        token = checked(SOURCE / '.local/state/codex-migrate-browser/control-token').read_text().strip()
        status = api(listener(pid), token, '/api/status')
        require(bool(status.get('receipt')) and status.get('status') in ('complete', 'needs_attention')
                and status.get('phase') in ('verified', 'git_verification', 'path_compatibility')
                and status.get('git_verification', {}).get('status') != 'checking'
                and status.get('path_compatibility', {}).get('status') != 'checking'
                and status.get('recovery', {}).get('status') != 'checking', 'Old operation is not idle')
        require((pid, command) in processes(), 'Helper changed during check')
        os.kill(pid, signal.SIGTERM)
        for _ in range(50):
            if (pid, command) not in processes():
                break
            time.sleep(0.1)
        require((pid, command) not in processes(), 'Old helper did not stop')


def retire_failed_staging_helper(options, target):
    """Retire only the diagnosed pre-copy observer; preserve both migrations' data."""
    legacy = [(pid, cmd) for pid, cmd in processes() if cmd == str(LEGACY_ENGINE)]
    require(len(legacy) <= 1, 'Multiple old test helpers require review')
    if not legacy:
        return
    pid, command = legacy[0]
    root = checked(SOURCE / STATE_NAME, directory=True)
    require(read(root / 'runtime.json').get('pid') == pid, 'Unknown old test helper process')
    old_state = checked(root / 'migration', directory=True)
    token = checked(old_state / 'control-token').read_text().strip()
    port = listener(pid)
    def safe(value):
        config = value.get('config', {})
        return (isinstance(config, dict) and config.get('source_home') == str(SOURCE)
                and config.get('target_home') == str(TARGET) and config.get('target') == target
                and config.get('staging_name') == 'Codex-Migrate-Staging'
                and value.get('status') == 'failed' and value.get('phase') == 'preflight_complete'
                and not value.get('receipt') and not value.get('pending_backup')
                and value.get('staging_complete') is False
                and all(isinstance(value.get(key, {}), dict)
                        and value.get(key, {}).get('status') != 'checking'
                        for key in ('recovery', 'path_compatibility', 'git_verification')))
    before = api(port, token, '/api/status')
    require(safe(before), 'Old test helper is not safely stopped before copying')
    result = remote(options, target, 'diagnose', before.get('migration_id'))
    require(result == {'staging': 'different_owner', 'pending_recovery': False},
            'Old staging conflict changed; preserve both migrations for review')
    after = api(port, token, '/api/status')
    require(safe(after) and after.get('migration_id') == before.get('migration_id')
            and (pid, command) in processes(), 'Old test helper changed during review')
    os.kill(pid, signal.SIGTERM)
    for _ in range(100):
        if (pid, command) not in processes():
            return
        time.sleep(0.1)
    raise SafeError('Old test helper did not stop; no replacement started')


def driver():
    home = account('source')
    root = root_for(home)
    lock_path = root / 'runner.lock'
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    lock = os.fdopen(fd, 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SafeError('The test runner is already running') from None
    PUBLIC.mkdir(mode=0o755, exist_ok=True)
    checked(PUBLIC, directory=True, private=False)
    report = {'phase': 'preparing', 'runner_pid': os.getpid(), 'migration_started': False,
              'desktop_visual_check': 'not_yet_performed'}
    def update(phase, **fields):
        report.update(phase=phase, updated_at=time.time(), **fields)
        save(PUBLIC / 'result.json', report, public=True)
        print(phase.replace('_', ' '), flush=True)
    engine = None
    try:
        reply, options, identity, known = connection()
        codex_binary()
        verify_shared_candidate()
        retire_failed_staging_helper(options, reply['target'])
        stop_old_helper()
        update('preparing_destination_test_account')
        deadline = time.monotonic() + 3 * 3600
        while True:
            try:
                remote(options, reply['target'], 'prepare')
                break
            except SafeError as error:
                require(str(error) in ('Quit Codex in the disposable target account first',
                        'Destination migration helper must be idle and closed'), str(error))
                require(time.monotonic() < deadline, 'Destination app-close wait expired; rerun launcher')
                update('waiting_for_target_apps_to_close', reason=str(error))
                time.sleep(15)
        update('preparing_source_test_account')
        while not codex_closed():
            require(time.monotonic() < deadline, 'Source app-close wait expired; rerun launcher')
            update('waiting_for_source_Codex_to_close')
            time.sleep(15)
        prepare(home, 'source')
        update('sign_into_Codex_in_both_test_accounts_then_quit_Codex')
        # Opening an app here is only appropriate when this script was launched
        # by the source account's logged-in desktop, not sudo from another user.
        if not login_ready(home) and Path('/dev/console').stat().st_uid == os.getuid():
            subprocess.run(['/usr/bin/open', '-b', 'com.openai.codex'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 3 * 3600
        while time.monotonic() < deadline:
            source_ready = login_ready(home)
            destination_ready = remote(options, reply['target'], 'ready')['ready']
            update('waiting_for_sign_in_and_quit', source_ready=source_ready, target_ready=destination_ready)
            if source_ready and destination_ready:
                break
            time.sleep(15)
        else:
            raise SafeError('Sign-in wait expired; rerun the same launcher to resume')
        update('creating_genuine_test_conversations')
        records = fixture_threads(home)
        update('three_genuine_conversations_created', conversations=3, test_model=records[0]['model']['model'])
        state = root / MIGRATION_STATE
        command = [str(ENGINE), 'serve', '--apply', '--no-open', '--port', '0',
            '--source-home', str(home), '--target', reply['target'], '--target-home', str(TARGET),
            '--workspace', str(home / WORKSPACE_NAME), '--state-dir', str(state),
            '--staging-name', STAGING_NAME,
            '--identity-file', str(identity), '--known-hosts-file', str(known),
            '--host-key-alias', 'codex-migrate-' + reply['id']]
        existing = [(pid, cmd) for pid, cmd in processes() if cmd == str(ENGINE)]
        require(len(existing) <= 1, 'Multiple test helpers require review')
        if existing:
            runtime = read(root / RUNTIME_RECORD)
            require(runtime.get('pid') == existing[0][0], 'Unknown test helper process')
            port = listener(existing[0][0])
            token = checked(state / 'control-token').read_text().strip()
        else:
            engine = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                      start_new_session=True)
            save(root / RUNTIME_RECORD, {'pid': engine.pid})
            for _ in range(60):
                time.sleep(0.5)
                if engine.poll() is not None:
                    raise SafeError('Packaged helper failed to start')
                try:
                    port = listener(engine.pid)
                    token = checked(state / 'control-token').read_text().strip()
                    break
                except (OSError, SafeError):
                    continue
            else:
                raise SafeError('Packaged helper startup timed out')
        def wait_for(phase, desired):
            end = time.monotonic() + 900
            while time.monotonic() < end:
                value = api(port, token, '/api/status')
                update(phase, migration_status=value.get('status'), migration_phase=value.get('phase'))
                if desired(value):
                    return value
                require(value.get('status') not in ('failed', 'interrupted', 'cancelled', 'waiting'),
                        'Migration stopped; preserve state and inspect the protected dashboard')
                time.sleep(2)
            raise SafeError('Operation observation timed out; helper remains available')
        status = api(port, token, '/api/status')
        if not status.get('receipt'):
            require(status.get('status') in ('idle', 'ready', 'ready_to_finalize'),
                    'Existing transfer requires review; no automatic reset')
            if status.get('status') != 'ready_to_finalize':
                api(port, token, '/api/action', {'action': 'inspect'})
                wait_for('inspecting', lambda s: s.get('status') == 'ready')
                api(port, token, '/api/action', {'action': 'start'})
                report['migration_started'] = True
                wait_for('staging', lambda s: s.get('status') == 'ready_to_finalize')
            api(port, token, '/api/action', {'action': 'finalize', 'confirmed': True})
            status = wait_for('finalizing', lambda s: bool(s.get('receipt'))
                              and s.get('path_compatibility', {}).get('status') != 'checking')
        require(bool(status.get('receipt')), 'Missing installation receipt')
        if status.get('git_verification', {}).get('status') != 'checking':
            api(port, token, '/api/action', {'action': 'check_git'})
        status = wait_for('checking_git', lambda s: s.get('git_verification', {}).get('status')
                          in ('verified', 'failed', 'unavailable', 'source_issues'))
        require(status.get('git_verification', {}).get('status') == 'verified', 'Git verification needs review')
        update('reopening_and_continuing_on_new_Mac', installation_receipt=True)
        result = remote(options, reply['target'], 'prove', records)
        update('automated_acceptance_passed_visual_check_remaining', **result)
    except Exception as error:
        # No exception text, account records, subprocess output or control token
        # is copied into the public report.
        update('needs_review', failed_phase=report['phase'], error_type=type(error).__name__,
               reason=str(error) if isinstance(error, SafeError) else 'Unexpected error; raw details withheld')
        print('Stopped safely. Tell the supervising Codex task; do not reset either test account.', flush=True)
    finally:
        # Do not interrupt an in-progress protected install on an observation
        # timeout. The helper owns its operation independently and keeps running.
        if engine is not None and engine.poll() is None and report['phase'].startswith('automated_acceptance'):
            engine.terminate()
            engine.wait(timeout=30)
        lock.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--remote-action', choices=('prepare', 'ready', 'prove', 'diagnose'))
    parser.add_argument('--payload', default='bnVsbA==')
    parser.add_argument('--background', action='store_true')
    parser.add_argument('--diagnose', action='store_true')
    args = parser.parse_args()
    require(not args.diagnose or not (args.background or args.remote_action), 'Conflicting test actions')
    if args.diagnose:
        diagnose()
    elif args.background:
        account('source')
        worker = subprocess.Popen(['/usr/bin/python3', str(Path(__file__).resolve())],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        time.sleep(1)
        exit_code = worker.poll()
        if exit_code is not None:
            # A read-only diagnostic can finish before this one-second check.
            # Even exit 0 can mean driver() recorded needs_review, not success.
            print('The runner has already stopped; it is not running in the background.')
            print('Tell the supervising Codex task to check the latest status report.')
            print('Do not repeat setup or launch again until that report is reviewed.')
            return
        print('Test preparation is running in the background. This window can close.')
        print('Existing Codex sign-ins are retained. Keep Codex closed in both test accounts.')
        print('If a sign-in is still needed: sign in normally, then Command-Q.')
        print('You can then return to your personal accounts. The test continues automatically.')
    elif args.remote_action:
        home = account('target')
        if args.remote_action == 'prepare':
            codex_binary()
            require(not any(Path(cmd).name == 'codex-migrate-engine' for _, cmd in processes()),
                    'Destination migration helper must be idle and closed')
            prepare(home, 'target')
            result = {'prepared': True}
        elif args.remote_action == 'ready':
            result = {'ready': login_ready(home)}
        elif args.remote_action == 'diagnose':
            result = staging_diagnostic(home, json.loads(base64.b64decode(args.payload)))
        else:
            require(codex_closed(), 'Quit destination Codex before automated reopening check')
            result = prove_threads(home, json.loads(base64.b64decode(args.payload)))
        print(json.dumps(result))
    else:
        driver()


if __name__ == '__main__':
    try:
        main()
    except SafeError as error:
        # Messages are fixed by this program, never credential/provider output.
        print(json.dumps({'error': str(error)}))
        raise SystemExit(1)
