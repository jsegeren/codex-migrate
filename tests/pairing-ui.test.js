// Execute the shipped async interaction, not a rewritten approximation.
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { test } = require('node:test');
const vm = require('node:vm');

const source = readFileSync(new URL('../src/codex_migrate/setup.py', `file://${__filename}`), 'utf8');
const script = source.match(/async function connectionAction\([\s\S]*?\n\}/)[0];

function fixture() {
  const document = { body: {}, activeElement: null };
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) {
      let disabled = false;
      const control = { id, hidden: false, textContent: '',
        focus() { document.activeElement = this; },
        getClientRects() { return this.hidden ? [] : [{}]; } };
      Object.defineProperty(control, 'disabled', {
        get: () => disabled,
        set(value) {
          disabled = value;
          if (value && document.activeElement === control) document.activeElement = document.body;
        },
      });
      elements.set(id, control);
    }
    return elements.get(id);
  }
  let resolve, reject, calls = 0;
  const response = new Promise((yes, no) => { resolve = yes; reject = no; });
  const context = { document, $: element, api: () => { calls++; return response; } };
  vm.runInNewContext(script, context);
  return { document, element, resolve, reject, calls: () => calls, run: context.connectionAction };
}

for (const success of [true, false]) {
  for (const moved of [true, false]) {
    test(`connection ${success ? 'success' : 'failure'} preserves useful ${moved ? 'moved' : 'original'} focus`, async () => {
      const f = fixture(), button = f.element('approve'), next = f.element('copy-reply'), other = f.element('help');
      button.focus();
      let completed = 0;
      const done = () => { completed++; button.hidden = true; return next; };
      const pending = f.run(button, 'approve', {}, done);
      assert.equal(button.disabled, true);
      await f.run(button, 'approve', {}, done);
      assert.equal(f.calls(), 1, 'duplicate action is ignored');
      if (moved) other.focus();
      if (success) f.resolve({}); else f.reject(Error('Try again'));
      await pending;
      assert.equal(button.disabled, false);
      assert.equal(completed, success ? 1 : 0);
      assert.equal(f.document.activeElement, moved ? other : success ? next : button);
      assert.equal(f.element('error').textContent, success ? '' : 'Try again');
    });
  }
}

test('a programmatic action does not steal focus', async () => {
  const f = fixture(), other = f.element('help'); other.focus();
  const pending = f.run(f.element('approve'), 'approve', {}, () => f.element('copy-reply'));
  f.resolve({}); await pending;
  assert.equal(f.document.activeElement, other);
});
