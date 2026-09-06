// Small state regression against the shipped browser script, not a reimplementation.
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { test } = require('node:test');
const vm = require('node:vm');

const source = readFileSync(new URL('../src/codex_migrate/dashboard.py', `file://${__filename}`), 'utf8');
const script = source.match(/function renderTransferControls\(s\)\{[\s\S]*?\n\}/)[0];

test('home-path next action is beside the status, ahead of secondary details', () => {
  const markup = source.slice(0, source.indexOf('<script>'));
  assert.equal((markup.match(/id="path-next"/g) || []).length, 1);
  assert(markup.indexOf('id="message"') < markup.indexOf('id="path-next"'));
  assert(markup.indexOf('id="path-next"') < markup.indexOf('class="grid"'));
  assert.match(markup, /#transfer-controls\[hidden\]\s*\{\s*display:none/);
});

test('installed workspace hides obsolete transfer controls without hiding retryable work', () => {
  const controls = { hidden: false };
  const context = { $: id => { assert.equal(id, 'transfer-controls'); return controls; } };
  vm.createContext(context);
  vm.runInContext(script, context);
  for (const phase of ['path_compatibility', 'git_verification']) {
    context.renderTransferControls({status:'needs_attention',phase,receipt:{backup_verified:true}});
    assert.equal(controls.hidden, true);
    context.renderTransferControls({status:'failed',phase});
    assert.equal(controls.hidden, false);
  }
  context.renderTransferControls({status:'complete',phase:'verified'});
  assert.equal(controls.hidden, true);
  for (const status of ['idle','ready','running','paused','cancelled','failed','interrupted','ready_to_finalize']) {
    context.renderTransferControls({status,phase:'staging'});
    assert.equal(controls.hidden, false, status);
  }
});
