const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { test } = require('node:test');
const vm = require('node:vm');

const source = readFileSync(new URL('../src/codex_migrate/vault_dashboard.py', `file://${__filename}`), 'utf8');
const runSearch = source.match(/async function runSearch\(append=false\)\{[\s\S]*?\n\}/)[0];

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
