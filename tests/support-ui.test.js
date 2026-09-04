// Execute the shipped shared Help script with a bounded DOM/fetch fixture.
// Real-browser checks complement these deterministic async focus regressions.
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { test } = require('node:test');
const vm = require('node:vm');

const source = readFileSync(new URL('../src/codex_migrate/support.py', `file://${__filename}`), 'utf8');
const script = source.match(/SUPPORT_SCRIPT = r"""\n([\s\S]*?)\n"""/)[1];

function fixture() {
  const document = { body: {}, activeElement: null };
  const elements = new Map();
  document.getElementById = id => {
    if (!elements.has(id)) {
      let disabled = false;
      const element = { id, hidden: false, value: '', textContent: '', scrollTop: 50,
        focus() { document.activeElement = this; }, setSelectionRange() {} };
      Object.defineProperty(element, 'disabled', {
        get() { return disabled; },
        set(value) {
          disabled = value;
          if (value && document.activeElement === element) document.activeElement = document.body;
        },
      });
      elements.set(id, element);
    }
    return elements.get(id);
  };
  let finish;
  let calls = 0;
  const response = new Promise(resolve => { finish = resolve; });
  const context = { document, token: 'fixture-only', fetch: () => { calls++; return response; } };
  vm.runInNewContext(script, context);
  const button = document.getElementById('prepare-support');
  button.focus();
  return { document, button, get: document.getElementById, finish, calls: () => calls };
}

for (const outcome of ['success', 'http-error', 'invalid-json']) {
  for (const moved of [false, true]) {
    test(`Help ${outcome}: ${moved ? 'preserves moved focus' : 'keeps a useful focus target'}`, async () => {
      const f = fixture();
      const pending = f.button.onclick();
      assert.equal(f.button.disabled, true);
      await f.button.onclick();
      assert.equal(f.calls(), 1, 'duplicate preparation must not start');
      const other = f.get('other-control');
      if (moved) other.focus();
      f.finish({ ok: outcome !== 'http-error', json: async () => {
        if (outcome === 'invalid-json') throw Error('fixture');
        return { report_format: 1, notes: 'Sample data only' };
      } });
      await pending;
      assert.equal(f.button.disabled, false);
      assert.equal(f.document.activeElement, moved ? other :
        outcome === 'success' ? f.get('support-report') : f.button);
      assert.equal(f.get('support-preview').hidden, outcome !== 'success');
      assert.match(f.get('support-status').textContent,
        outcome === 'success' ? /has not been sent/ : /can still email support/);
    });
  }
}
