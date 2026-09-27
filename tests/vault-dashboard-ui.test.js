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
  ]);
  let notice, rejectSearch, cleared = false;
  const context = {
    $: id => elements.get(id),
    URLSearchParams,
    api: () => new Promise((resolve, reject) => { rejectSearch = reject; }),
    fail: error => { elements.get('error').textContent = error.message; },
    setTimeout: callback => { notice = callback; return 1; },
    clearTimeout: id => { assert.equal(id, 1); cleared = true; },
  };
  vm.createContext(context);
  vm.runInContext('let searchPage=null; let searchRequest=0; ' + runSearch, context);
  const pending = context.runSearch();
  assert.equal(elements.get('status').textContent, 'Searching this Mac…');
  notice();
  assert.match(elements.get('status').textContent, /Still searching this Mac/);
  assert.match(elements.get('status').textContent, /optional search cache/);
  rejectSearch(new Error('Search stopped'));
  await pending;
  assert.equal(elements.get('error').textContent, 'Search stopped');
  assert.equal(elements.get('salvage-controls').open, true);
  assert.match(elements.get('salvage-status').textContent, /find it by title or date/);
  assert.equal(cleared, true);
  assert.equal(elements.get('more-results').disabled, false);
});
