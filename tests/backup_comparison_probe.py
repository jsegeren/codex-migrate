"""One-shot, read-only probe for the exact disposable failed migration.

No repair, migration restart, password storage, command queue or access grant.
Only fixed counts and booleans leave the two test accounts.
"""
import collections
import json
import os
from pathlib import Path
import pwd
import re
import runpy
import shlex
import stat
import subprocess
import sys
import tempfile
import time

SOURCE = Path('/Users/codexmigratesource')
TARGET = Path('/Users/codexmigratetarget')
SHARED = Path('/Users/Shared/CodexMigrate-Authentic-20260906')
PUBLIC = Path('/Users/Shared/CodexMigrate-Authentic-Status-20260906')
BACKUP = re.compile(r'Codex-Migrate-Backup-\d{8}T\d{6}Z-[a-f0-9]{16}')
MAX_NODES = 50000


def require(condition):
    if not condition:
        raise RuntimeError('diagnostic_guard_failed')


def owned_directory(path):
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and not info.st_mode & 0o022)


def backup_name(value):
    require(isinstance(value, str) and Path(value).parent == TARGET
            and BACKUP.fullmatch(Path(value).name) is not None)
    return Path(value).name


def node_kind(mode):
    for kind, predicate in [('file', stat.S_ISREG), ('directory', stat.S_ISDIR),
                            ('link', stat.S_ISLNK), ('fifo', stat.S_ISFIFO),
                            ('socket', stat.S_ISSOCK)]:
        if predicate(mode):
            return kind
    return 'other'


def tree(root):
    """Metadata only; never follow links or open file contents."""
    owned_directory(root)
    result = {}
    pending = [root]
    while pending:
        folder = pending.pop()
        with os.scandir(folder) as entries:
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                path = Path(entry.path)
                result[str(path.relative_to(root))] = node_kind(info.st_mode)
                require(len(result) <= MAX_NODES)
                if stat.S_ISDIR(info.st_mode):
                    require(info.st_uid == os.getuid() and not info.st_mode & 0o022)
                    pending.append(path)
    return result


def differences(original, copied):
    return {
        'missing_by_type': dict(collections.Counter(original[k] for k in original.keys() - copied.keys())),
        'extra_by_type': dict(collections.Counter(copied[k] for k in copied.keys() - original.keys())),
        'changed_type_count': sum(original[k] != copied[k] for k in original.keys() & copied.keys()),
        'original_types': dict(collections.Counter(original.values())),
        'backup_types': dict(collections.Counter(copied.values())),
    }


def compare(original, copied, specials):
    command = ['/usr/bin/rsync', '-rlnc', '--delete', '--out-format=%i']
    if specials:
        command.append('--specials')
    # -n is mandatory. No filenames or checksum values are exported. A private
    # temporary captures bounded tool output; stderr is not surfaced.
    command.extend([str(original) + '/', str(copied) + '/'])
    with tempfile.TemporaryFile() as output:
        run = subprocess.run(command, stdout=output, stderr=subprocess.DEVNULL, timeout=90)
        require(output.tell() <= 2 * 1024 * 1024)
        output.seek(0)
        lines = output.read().decode('utf-8', errors='replace').splitlines()
    codes = collections.Counter()
    other = 0
    for line in lines:
        if re.fullmatch(r'[<>ch.][fdLDS][cstpoguax?.+ ]{9}', line):
            codes[line] += 1
        elif line:
            other += 1
    return {'completed': run.returncode == 0, 'clean': run.returncode == 0 and not lines,
            'itemized_codes': dict(codes), 'other_output_lines': other}


def target_probe(name):
    user = pwd.getpwuid(os.getuid())
    require(os.getuid() == os.geteuid() != 0 and user.pw_name == TARGET.name
            and user.pw_dir == str(TARGET) and BACKUP.fullmatch(name) is not None)
    owned_directory(TARGET)
    backup = TARGET / name
    owned_directory(backup)
    original, copied = TARGET / '.codex', backup / '.codex'
    before_a, before_b = tree(original), tree(copied)
    old = compare(original, copied, False)
    new = compare(original, copied, True)
    return {'format': 1, 'read_only': True, 'checked_at': int(time.time()),
            'comparison_build2': old, 'comparison_build3': new,
            'structure': differences(before_a, before_b),
            'structure_changed_during_probe': before_a != tree(original) or before_b != tree(copied),
            'backup_receipt_present': os.path.lexists(backup / 'verification.json'),
            'pending_transaction_present': os.path.lexists(TARGET / '.codex-migrate-transaction.json')}


def source_probe():
    # Reuse the reviewed owner/pairing checks, not root or the personal account's
    # SSH credentials. run_path does not run the harness's main entry point.
    helper = runpy.run_path(str(SHARED / 'authentic_mac_handoff.py'))
    home = helper['account']('source')
    root = helper['checked'](home / helper['STATE_NAME'], directory=True)
    state_dir = helper['checked'](root / helper['MIGRATION_STATE'], directory=True)
    state = helper['read'](state_dir / 'state.json')
    require(state.get('status') == 'failed' and state.get('phase') == 'installing'
            and not state.get('receipt'))
    name = backup_name(state.get('pending_backup'))
    reply, options, _, _ = helper['connection']()
    command = ['/usr/bin/ssh', *options, reply['target'],
               '/usr/bin/python3 -I - --target-probe ' + shlex.quote(name)]
    response = subprocess.run(command, input=Path(__file__).read_bytes(),
                              capture_output=True, timeout=210)
    require(response.returncode == 0 and len(response.stdout) <= 16384)
    report = json.loads(response.stdout)
    # Reject arbitrary remote strings before writing anything shared.
    require(set(report) == {'format', 'read_only', 'checked_at', 'comparison_build2',
            'comparison_build3', 'structure', 'structure_changed_during_probe',
            'backup_receipt_present', 'pending_transaction_present'})
    def bounded(value):
        if type(value) is bool or type(value) is int:
            return 0 <= value <= 10000000000
        return isinstance(value, dict) and all(isinstance(k, str) and
            (k in ALLOWED_KEYS or re.fullmatch(r'[<>ch.][fdLDS][cstpoguax?.+ ]{9}', k))
            and bounded(v) for k, v in value.items())
    require(bounded(report) and report['read_only'] is True and report['format'] == 1)
    helper['checked'](PUBLIC, directory=True, private=False)
    helper['save'](PUBLIC / 'backup-comparison-diagnostic.json', report, public=True)
    print('Backup diagnostic saved in Shared. No migration or repair was performed.')


ALLOWED_KEYS = frozenset(('format', 'read_only', 'checked_at', 'comparison_build2',
    'comparison_build3', 'structure', 'structure_changed_during_probe',
    'backup_receipt_present', 'pending_transaction_present', 'completed', 'clean',
    'itemized_codes', 'other_output_lines', 'missing_by_type', 'extra_by_type',
    'changed_type_count', 'original_types', 'backup_types', 'file', 'directory',
    'link', 'fifo', 'socket', 'other'))

if __name__ == '__main__':
    try:
        if len(sys.argv) == 3 and sys.argv[1] == '--target-probe':
            print(json.dumps(target_probe(sys.argv[2])))
        else:
            require(len(sys.argv) == 1)
            source_probe()
    except Exception:
        print('Diagnostic could not complete; no migration or repair was performed.')
        sys.exit(1)
