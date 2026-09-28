// Execute the shipped home-screen classifier with representative backup states.
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { test } = require('node:test');
const vm = require('node:vm');

const source = readFileSync(new URL('../src/codex_migrate/setup.py', `file://${__filename}`), 'utf8');
const script = source.match(/async function loadOverview\(\)\{[\s\S]*?\n\}/)[0];

async function overview(schedule, backup = { status: 'idle' }) {
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) {
      const classes = new Set();
      elements.set(id, {
        textContent: '', classes,
        classList: {
          add(name) { classes.add(name); },
          toggle(name, present) {
            if (present) classes.add(name); else classes.delete(name);
          },
        },
      });
    }
    return elements.get(id);
  }
  const responses = {
    '/api/vault/summary': { active_transcripts: 2, archived_transcripts: 3 },
    '/api/vault/schedule': schedule,
    '/api/vault/backup-status': backup,
  };
  const context = { $: element, api: async path => responses[path] };
  vm.runInNewContext(script, context);
  await context.loadOverview();
  return {
    title: element('overview-health').textContent,
    detail: element('overview-health-detail').textContent,
    icon: element('overview-health-icon').textContent,
    attention: element('overview-health-card').classes.has('attention'),
  };
}

test('verified scheduled run is the only healthy automatic-protection state', async () => {
  const result = await overview({ enabled: true, healthy: true,
    last_run: { status: 'completed' } });
  assert.equal(result.title, 'Automatic backup verified');
  assert.equal(result.icon, '✓');
  assert.equal(result.attention, false);
});

test('a loaded schedule without a completed run is still pending', async () => {
  const result = await overview({ enabled: true, healthy: true });
  assert.equal(result.title, 'First scheduled backup pending');
  assert.match(result.detail, /Initial snapshot alone is not scheduled protection/);
  assert.equal(result.attention, true);
});

test('a running scheduled backup is reported as running, not verified', async () => {
  const result = await overview({ enabled: true, healthy: true,
    last_run: { status: 'running' } });
  assert.equal(result.title, 'Scheduled backup running');
  assert.equal(result.attention, true);
});

for (const schedule of [
  { enabled: true, healthy: false, last_run: { status: 'failed' },
    error: 'The latest automatic backup needs attention.' },
  { enabled: true, healthy: true, last_run: { status: 'failed' } },
  { enabled: true, healthy: true, last_run: { status: 'unknown' } },
  { enabled: true, healthy: false, last_run: { status: 'completed' },
    error: 'Automatic backup is overdue.' },
  { enabled: false, healthy: false,
    error: 'Automatic backup setup is incomplete.' },
]) {
  test(`a broken schedule is never presented as pending: ${schedule.error || schedule.last_run.status}`, async () => {
    const result = await overview(schedule);
    assert.equal(result.title, 'Automatic backup needs attention');
    if (schedule.error) assert.equal(result.detail, schedule.error);
    else assert.match(result.detail, /check the schedule and last good snapshot/);
    assert.equal(result.attention, true);
  });
}

test('possible thread-content loss outranks schedule health', async () => {
  const result = await overview({ enabled: true, healthy: false,
    last_run: { status: 'needs_attention' }, error: 'Backup needs attention.' });
  assert.equal(result.title, 'Conversation backup needs review');
  assert.match(result.detail, /earlier verified version/);
});

test('paginated history coverage is never presented as a healthy backup', async () => {
  const result = await overview({ enabled: true, healthy: false,
    last_run: { status: 'needs_attention', paginated_history_unprotected: true } });
  assert.equal(result.title, 'Conversation coverage needs review');
  assert.match(result.detail, /paginated history is not yet fully recoverable/);
  assert.doesNotMatch(result.detail, /earlier verified version/);
  assert.equal(result.attention, true);
});

test('an older green schedule receipt cannot override current paginated coverage', async () => {
  const result = await overview({ enabled: true, healthy: false,
    paginated_history_unprotected: true, last_run: { status: 'completed' } });
  assert.equal(result.title, 'Conversation coverage needs review');
  assert.equal(result.icon, '!');
  assert.equal(result.attention, true);
});

test('manual backup failure is not mistaken for absent backup', async () => {
  const result = await overview({ enabled: false }, { status: 'failed' });
  assert.equal(result.title, 'Backup attempt failed');
  assert.equal(result.attention, true);
});

test('an idle new browser session does not claim no past backups exist', async () => {
  const result = await overview({ enabled: false }, { status: 'idle' });
  assert.equal(result.title, 'Backup status not checked');
  assert.match(result.detail, /choose or verify a Vault/);
  assert.equal(result.attention, true);
});
