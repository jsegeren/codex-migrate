const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { test } = require('node:test');
const vm = require('node:vm');

const source = readFileSync(new URL('../src/codex_migrate/vault_dashboard.py', `file://${__filename}`), 'utf8');
const runSearch = source.match(/async function runSearch\(append=false\)\{[\s\S]*?\n\}/)[0];
const completeVisibleConversation = vm.runInNewContext(
  '(' + source.match(/function completeVisibleConversation\([\s\S]*?\n\}/)[0] + ')');
const markdownFile = source.match(/async function markdownFile\(\)\{[\s\S]*?\n\}/)[0];
const backupView = source.match(/function backupView\(data\)\{[\s\S]*?\n\}/)[0];
const scheduleView = source.match(/function scheduleView\(data\)\{[^\n]*\}/)[0];

test('schedule view explicitly disclaims incomplete paginated coverage', () => {
  const elements = new Map();
  const context = {
    $: id => {
      if (!elements.has(id)) elements.set(id, { value: '', textContent: '', checked: false });
      return elements.get(id);
    },
    storageView: () => {}, backupFrequencyView: () => {},
    refreshScheduleButton: () => {}, refreshRestoreButton: () => {},
  };
  vm.createContext(context);
  vm.runInContext('let scheduleEnabled=false; ' + scheduleView, context);
  context.scheduleView({ enabled: true, healthy: false,
    paginated_history_unprotected: true });
  assert.match(elements.get('schedule-status').textContent, /not complete protection/);
});

test('backup view names missing paginated coverage without inventing an earlier safe version', () => {
  const elements = new Map();
  const context = {
    $: id => {
      if (!elements.has(id)) elements.set(id, { value: '', textContent: '', hidden: false, disabled: false });
      return elements.get(id);
    },
    installRunning: false, scheduleEnabled: false, backupTimer: null,
    lastSizedSnapshot: null, pendingAutomaticBackup: false,
    fmt: () => '1 KB', refreshScheduleButton: () => {}, refreshRestoreButton: () => {},
  };
  vm.createContext(context);
  vm.runInContext('let verifiedBackup=false; ' + backupView, context);
  context.backupView({ status: 'needs_attention', at_risk_threads: 0,
    paginated_history_unprotected: true });
  const message = elements.get('backup-status').textContent;
  assert.match(message, /paginated history is not yet fully recoverable/);
  assert.match(message, /may be missing messages/);
  assert.doesNotMatch(message, /earlier saved version|0 conversations/);
});

test('coverage warning keeps the selected daily backup without scheduling a known lost turn', () => {
  const elements = new Map();
  let scheduled = 0;
  const context = {
    $: id => {
      if (!elements.has(id)) elements.set(id, { value: '', textContent: '', hidden: false, disabled: false });
      return elements.get(id);
    },
    installRunning: false, scheduleEnabled: false, backupTimer: null,
    lastSizedSnapshot: null, pendingAutomaticBackup: true,
    fmt: () => '1 KB', refreshScheduleButton: () => {}, refreshRestoreButton: () => {},
    enableRequestedSchedule: () => { scheduled++; },
  };
  vm.createContext(context);
  vm.runInContext('let verifiedBackup=false; ' + backupView, context);
  context.backupView({ status: 'needs_attention', at_risk_threads: 0,
    paginated_history_unprotected: true });
  assert.equal(scheduled, 1);
  context.backupView({ status: 'needs_attention', at_risk_threads: 1,
    paginated_history_unprotected: true });
  assert.equal(scheduled, 1);
});

test('print and share require the whole non-excerpted conversation', () => {
  assert.equal(completeVisibleConversation({ cursor: 100, line: 2 }, false, null), false);
  assert.equal(completeVisibleConversation({ cursor: 0, line: 1 }, false, null), true);
  assert.equal(completeVisibleConversation({ cursor: 0, line: 0 }, true, null), false);
  assert.equal(completeVisibleConversation({ cursor: 0, line: 0 }, false, 200), false);
  assert.equal(completeVisibleConversation({ cursor: 0, line: 0 }, false, null), true);
});

test('share uses the full one-use export but refuses an oversized browser file', async () => {
  let cancelled = false;
  const calls = [];
  const context = {
    selected: { collection: 'active', transcript: 'thread.jsonl', source: 'local' },
    api: async (...args) => { calls.push(args); return { url: '/api/vault/download?ticket=fixture' }; },
    fetch: async () => ({ ok: true, headers: { get: () => String(21 * 1024 * 1024) },
      body: { cancel: async () => { cancelled = true; } } }),
  };
  vm.createContext(context);
  vm.runInContext(markdownFile, context);
  await assert.rejects(context.markdownFile(), /too large for the browser share sheet/);
  assert.equal(cancelled, true);
  assert.equal(calls[0][0], '/api/vault/export-ticket');
  assert.equal(calls[0][1].transcript, 'thread.jsonl');

  context.fetch = async () => ({ ok: true, headers: { get: () => '4' },
    blob: async () => ({ size: 4 }) });
  context.File = class { constructor(parts, name, options) {
    this.parts = parts; this.name = name; this.type = options.type;
  } };
  const file = await context.markdownFile();
  assert.equal(file.name, 'codex-conversation.md');
  assert.equal(file.parts[0].size, 4);
});

test('a slow local search explains the wait without claiming it has finished', async () => {
  const elements = new Map([
    ['search-source', { value: 'local' }],
    ['query', { value: 'Unification Foundation' }],
    ['error', { textContent: '' }],
    ['thread', { hidden: false }],
    ['more-results', { hidden: false, disabled: false }],
    ['status', { textContent: '' }],
    ['index-build', { disabled: false }],
    ['salvage-controls', { open: false }],
    ['salvage-status', { textContent: '' }],
    ['results-panel', { hidden: true }],
    ['results', { children: [], replaceChildren(...nodes) { this.children = nodes; },
      append(...nodes) { this.children.push(...nodes); } }],
  ]);
  let notice, rejectSearch, cleared = false;
  const context = {
    $: id => elements.get(id),
    URLSearchParams,
    api: url => url.includes('source=local_titles') ? Promise.resolve({ results: [] }) :
      new Promise((resolve, reject) => { rejectSearch = reject; }),
    fail: error => { elements.get('error').textContent = error.message; },
    setTimeout: callback => { notice = callback; return 1; },
    clearTimeout: id => { assert.equal(id, 1); cleared = true; },
  };
  vm.createContext(context);
  vm.runInContext('let searchPage=null; let searchRequest=0; ' + runSearch, context);
  const pending = context.runSearch();
  assert.equal(elements.get('status').textContent, 'Searching this Mac…');
  notice();
  assert.match(elements.get('status').textContent, /Still searching conversation text/);
  assert.match(elements.get('status').textContent, /optional search cache/);
  await new Promise(resolve => setImmediate(resolve));
  rejectSearch(new Error('Search stopped'));
  await pending;
  assert.equal(elements.get('error').textContent, 'Search stopped');
  assert.equal(elements.get('salvage-controls').open, true);
  assert.match(elements.get('salvage-status').textContent, /find it by title or date/);
  assert.equal(cleared, true);
  assert.equal(elements.get('more-results').disabled, false);
});

test('matching titles appear before full-text search and are not duplicated', async () => {
  function node() {
    return { children: [], textContent: '', append(...items) { this.children.push(...items); },
      replaceChildren(...items) { this.children = items; } };
  }
  const elements = new Map([
    ['search-source', { value: 'local' }],
    ['query', { value: 'Unification Foundation' }],
    ['error', { textContent: '' }],
    ['thread', { hidden: false }],
    ['more-results', { hidden: false, disabled: false }],
    ['status', { textContent: '' }],
    ['index-build', { disabled: false }],
    ['results-panel', { hidden: true }],
    ['results', node()],
    ['salvage-controls', { open: false }],
    ['salvage-status', { textContent: '' }],
  ]);
  const title = { collection: 'active', transcript: 'found.jsonl',
    title: 'You One - P00 Unification Foundation', snippet: 'Title match' };
  let finishText, opened, notice;
  const context = {
    $: id => elements.get(id), document: { createElement: node }, URLSearchParams,
    api: url => url.includes('source=local_titles') ?
      Promise.resolve({ results: [title] }) :
      new Promise(resolve => { finishText = resolve; }),
    openThread: item => { opened = item; },
    fail: error => { elements.get('error').textContent = error.message; },
    setTimeout: callback => { notice = callback; return 1; }, clearTimeout: () => {},
  };
  vm.createContext(context);
  vm.runInContext('let searchPage=null; let searchRequest=0; ' + runSearch, context);
  const pending = context.runSearch();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(elements.get('results-panel').hidden, false);
  assert.equal(elements.get('results').children.length, 1);
  assert.match(elements.get('status').textContent, /matching title found/);
  notice();
  assert.match(elements.get('status').textContent, /1 matching title found. Still searching conversation text/);
  elements.get('results').children[0].onclick();
  assert.equal(opened.transcript, title.transcript);
  assert.equal(opened.source, 'local');

  finishText({ results: [title, { collection: 'active', transcript: 'other.jsonl',
    title: 'Another thread', snippet: 'Content match' }], has_more: false });
  await pending;
  assert.equal(elements.get('results').children.length, 2);
  assert.equal(elements.get('more-results').hidden, true);
  assert.equal(vm.runInContext('searchPage.offset', context), 2);
});
