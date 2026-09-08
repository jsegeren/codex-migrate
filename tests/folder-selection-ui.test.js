// Run the shipped folder-selection interaction with a delayed helper response.
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { test } = require('node:test');
const vm = require('node:vm');
const source = readFileSync(new URL('../src/codex_migrate/setup.py', `file://${__filename}`), 'utf8');
const script = source.slice(source.indexOf('async function folders('), source.indexOf('$("folders").onclick='));

test('compact mode label retains the separate selected-folder scope explanation', () => {
  assert.match(source, /<option value="full">Full Codex migration<\/option>/);
  assert.match(source, /other folders are not automatically included/);
});

function fixture() {
  const document = { body: {}, activeElement: null }, elements = new Map();
  function element(id) {
    if (!elements.has(id)) {
      let disabled = false;
      const control = {value: '', textContent: '', hidden: false,
        focus() { document.activeElement = this; },
        getClientRects() { return this.hidden ? [] : [{}]; }};
      Object.defineProperty(control, 'disabled', {get: () => disabled, set(value) {
        disabled = value;
        if (value && document.activeElement === control) document.activeElement = document.body;
      }});
      elements.set(id, control);
    }
    return elements.get(id);
  }
  let resolve, reject, calls = 0, summaries = 0;
  const response = new Promise((yes, no) => { resolve = yes; reject = no; });
  const context = {document, $: element,
    roots: () => element('workspaces').value.split('\n').filter(Boolean),
    folderSummary: () => summaries++, api: () => { calls++; return response; }};
  vm.runInNewContext(script, context);
  return {document, element, resolve, reject, calls: () => calls,
    summaries: () => summaries, run: context.folders};
}

for (const path of ['/api/folders', '/api/suggestions']) {
  test(`${path}: scope cannot be reviewed while the selection is unresolved`, async () => {
    const f = fixture();
    const pending = f.run(path);
    assert.equal(f.element('next-2').disabled, true);
    await f.run(path);
    assert.equal(f.calls(), 1);
    f.element('workspaces').value = '/fixture/existing';
    f.resolve({paths: ['/fixture/existing', '/fixture/new'], message: 'Review folders'});
    await pending;
    assert.equal(f.element('workspaces').value, '/fixture/existing\n/fixture/new');
    assert.equal(f.summaries(), 1);
    assert.equal(f.element('folder-message').textContent, 'Review folders');
    assert.equal(f.element('folder-error').textContent, '');
    for (const id of ['folders', 'suggest', 'next-2']) assert.equal(f.element(id).disabled, false);
  });
}

for (const fails of [false, true]) for (const moved of [false, true]) {
  test(`folder selection restores useful focus: failure=${fails}, moved=${moved}`, async () => {
    const f = fixture(), button = f.element('folders'), help = f.element('help');
    f.element('error').textContent = 'Previous error';
    f.element('message').textContent = 'Previous global status';
    f.element('folder-error').textContent = 'Previous picker error';
    f.element('workspaces').value = '/fixture/keep';
    button.focus();
    const pending = f.run('/api/folders');
    if (moved) help.focus();
    const cancellation = 'No folders added. Your existing selection is unchanged.';
    if (fails) f.reject(Error('Picker unavailable')); else f.resolve({paths: [], message: cancellation});
    await pending;
    assert.equal(f.document.activeElement, moved ? help : button);
    assert.equal(f.element('workspaces').value, '/fixture/keep');
    assert.equal(f.element('error').textContent, '');
    assert.equal(f.element('message').textContent, '');
    assert.equal(f.element('folder-error').textContent, fails ? 'Picker unavailable' : '');
    assert.equal(f.element('folder-message').textContent, fails ? '' : cancellation);
    assert.equal(f.element('next-2').disabled, false);
  });
}

test('completion does not focus a picker hidden by switching to the receiver', async () => {
  const f = fixture(), button = f.element('suggest'); button.focus();
  const pending = f.run('/api/suggestions'); button.hidden = true;
  f.resolve({paths: [], message: 'Review folders'}); await pending;
  assert.equal(f.document.activeElement, f.document.body);
});
