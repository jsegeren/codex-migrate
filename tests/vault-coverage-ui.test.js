const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { test } = require('node:test');
const vm = require('node:vm');

const setup = readFileSync(new URL('../src/codex_migrate/setup.py', `file://${__filename}`), 'utf8');
const vault = readFileSync(new URL('../src/codex_migrate/vault_dashboard.py', `file://${__filename}`), 'utf8');
const overviewScript = setup.match(/async function loadOverview\(\)\{[\s\S]*?\n\}/)[0];
const backupScript = vault.match(/function backupView\(data\)\{[\s\S]*?\n\}/)[0];
const scheduleScript = vault.match(/function scheduleView\(data\)\{[\s\S]*?\n\}/)[0];

function elements() {
  const values = new Map();
  const get = id => {
    if (!values.has(id)) {
      const classes = new Set();
      values.set(id, {
        value: '', textContent: '', hidden: false, disabled: false, checked: false,
        classes,
        classList: { add: name => classes.add(name),
          toggle: (name, present) => present ? classes.add(name) : classes.delete(name) },
      });
    }
    return values.get(id);
  };
  return { get, values };
}

test('overview never presents current paginated history as protected', async () => {
  const { get } = elements();
  const responses = {
    '/api/vault/summary': { active_transcripts: 1, archived_transcripts: 0 },
    '/api/vault/schedule': { enabled: true, healthy: false,
      paginated_history_unprotected: true, last_run: { status: 'completed' } },
    '/api/vault/backup-status': { status: 'completed' },
  };
  const context = { $: get, api: async path => responses[path] };
  vm.runInNewContext(overviewScript, context);
  await context.loadOverview();
  assert.equal(get('overview-health-icon').textContent, '!');
  assert.equal(get('overview-health-card').classes.has('attention'), true);
  assert.match(get('overview-health').textContent, /coverage needs review/);
  assert.match(get('overview-health-detail').textContent, /may not contain every message/);
});

test('manual-only snapshot is not presented as fully protected when new history appears', async () => {
  const { get } = elements();
  const responses = {
    '/api/vault/summary': { active_transcripts: 1, archived_transcripts: 0 },
    '/api/vault/schedule': { enabled: false, paginated_history_unprotected: true },
    '/api/vault/backup-status': { status: 'completed' },
  };
  const context = { $: get, api: async path => responses[path] };
  vm.runInNewContext(overviewScript, context);
  await context.loadOverview();
  assert.match(get('overview-health').textContent, /coverage needs review/);
  assert.equal(get('overview-health-icon').textContent, '!');
});

test('manual backup warning names the coverage gap without inventing lost conversations', () => {
  const { get } = elements();
  const context = {
    $: get, installRunning: false, scheduleEnabled: false, backupTimer: null,
    pendingAutomaticBackup: false, fmt: () => '1 KB',
    storageView: () => {}, refreshScheduleButton: () => {}, refreshRestoreButton: () => {},
  };
  vm.runInNewContext('let verifiedBackup=false; ' + backupScript, context);
  context.backupView({ status: 'needs_attention', at_risk_threads: 0,
    paginated_history_unprotected: true });
  const message = get('backup-status').textContent;
  assert.match(message, /paginated history is not yet fully recoverable/);
  assert.match(message, /may be missing messages/);
  assert.doesNotMatch(message, /0 conversations|earlier saved version/);
});

test('coverage warning permits daily transcript backups but content-loss warning does not', () => {
  const { get } = elements();
  let scheduled = 0;
  const context = {
    $: get, installRunning: false, scheduleEnabled: false, backupTimer: null,
    pendingAutomaticBackup: true, fmt: () => '1 KB',
    refreshScheduleButton: () => {}, refreshRestoreButton: () => {},
    enableRequestedSchedule: () => { scheduled++; },
  };
  vm.runInNewContext('let verifiedBackup=false; ' + backupScript, context);
  context.backupView({ status: 'needs_attention', at_risk_threads: 0,
    paginated_history_unprotected: true });
  assert.equal(scheduled, 1);
  context.backupView({ status: 'needs_attention', at_risk_threads: 1,
    paginated_history_unprotected: true });
  assert.equal(scheduled, 1);
});

test('scheduled backup status disclaims incomplete protection', () => {
  const { get } = elements();
  const context = { $: get, storageView: () => {}, backupFrequencyView: () => {},
    refreshScheduleButton: () => {}, refreshRestoreButton: () => {} };
  vm.runInNewContext('let scheduleEnabled=false; ' + scheduleScript, context);
  context.scheduleView({ enabled: true, healthy: false,
    paginated_history_unprotected: true });
  assert.match(get('schedule-status').textContent, /not complete protection/);
});
