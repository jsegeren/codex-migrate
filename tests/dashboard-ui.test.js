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

test('recovery next action is beside status and opens the actual recovery disclosure', () => {
  const markup = source.slice(0, source.indexOf('<script>'));
  assert.equal((markup.match(/id="recovery-next"/g) || []).length, 1);
  assert(markup.indexOf('id="message"') < markup.indexOf('id="recovery-next"'));
  assert(markup.indexOf('id="recovery-next"') < markup.indexOf('class="grid"'));
  assert.match(markup, /#recovery-next\[hidden\]/);
  let handler, scrolled = false, focused = false, prevented = false;
  const disclosure = {open:false, scrollIntoView() { scrolled = true; },
    querySelector(name) { assert.equal(name, 'summary'); return {focus() { focused = true; }}; }};
  const context = {$: id => {
    if (id === 'recovery-help') return disclosure;
    assert.equal(id, 'recovery-next');
    return {addEventListener(event, fn) { assert.equal(event, 'click'); handler = fn; }};
  }};
  vm.runInNewContext(source.split('\n').find(line => line.startsWith("$('recovery-next').addEventListener")), context);
  handler({preventDefault() { prevented = true; }});
  assert(disclosure.open && scrolled && focused && prevented);
});

test('interrupted installation and recovery expose guidance without calling an action', () => {
  const next = {hidden:true, textContent:''};
  const context = {$: id => { assert.equal(id, 'recovery-next'); return next; }};
  vm.createContext(context);
  vm.runInContext(source.match(/function renderRecoveryNext\(s\)\{[\s\S]*?\n\}/)[0], context);
  const cases = [
    [{status:'failed',phase:'installing'}, false, 'Review recovery options'],
    [{status:'interrupted',phase:'verifying'}, false, 'Review recovery options'],
    [{status:'failed',phase:'final_delta'}, true],
    [{status:'paused',phase:'staging'}, true],
    [{status:'interrupted',phase:'staging'}, true],
    [{status:'ready',phase:'inspected'}, true],
    [{status:'running',phase:'installing',pending_backup:'/fixture/backup'}, true],
    [{status:'failed',phase:'installing',pending_backup:'/fixture/backup',recovery:{status:'checking'}}, false, 'View recovery check'],
    [{status:'running',phase:'restoring'}, false, 'View restoration progress'],
    [{status:'interrupted',phase:'restored',recovery_attempt:{resolved:true},recovery:{status:'restore_verified'}}, false, 'Review restored files'],
    [{status:'failed',phase:'recovery_required',recovery:{status:'restore_changed'}}, false, 'Review recovery options'],
    [{status:'failed',phase:'staging',recovery_attempt:{resolved:false}}, false],
    [{status:'failed',phase:'staging',recovery:{status:'backup_verified'}}, false],
    [{status:'complete',phase:'verified',pending_backup:'/stale'}, true],
  ];
  for (const [state, hidden, label] of cases) {
    context.renderRecoveryNext(state);
    assert.equal(next.hidden, hidden, JSON.stringify(state));
    if (label) assert.equal(next.textContent, label);
  }
});

test('backup summary stays concise and opens details only when action is needed', () => {
  const elements = new Map([
    ['backup-safety', {classList:{toggle() {}}}],
    ['backup-details', {open:false}],
    ['backup-heading', {textContent:''}],
    ['backup-space', {textContent:''}],
    ['backup-location', {textContent:''}],
  ]);
  const context = {
    $: id => elements.get(id),
    fmt: value => `${value} B`,
  };
  vm.createContext(context);
  vm.runInContext(source.match(/function renderBackup\(s\)\{.*\}/)[0], context);

  context.renderBackup({status:'running',space_check:'ok',receipt:{}});
  assert.equal(elements.get('backup-details').open, false);
  assert.equal(elements.get('backup-heading').textContent, 'Backup required before replacement');

  context.renderBackup({status:'failed',space_check:'ok',receipt:{}});
  assert.equal(elements.get('backup-details').open, true);

  context.renderBackup({status:'complete',space_check:'ok',receipt:{backup_verified:true,backup:'/fixture/backup'}});
  assert.equal(elements.get('backup-details').open, false);
  assert.equal(elements.get('backup-heading').textContent, 'Backup verified');
});

test('only context-relevant migration actions stay visible', () => {
  const actions = new Map(['inspect','start','pause','resume','finalize','cancel'].map(id => [id, {hidden:false,disabled:false}]));
  const context = {$: id => actions.get(id)};
  vm.createContext(context);
  vm.runInContext(source.split('\n').find(line => line.startsWith('const setAction=')), context);
  vm.runInContext(source.match(/function renderActions\(s\)\{.*\}/)[0], context);

  context.renderActions({status:'running',phase:'staging',apply:true});
  assert.deepEqual([...actions].filter(([,value]) => !value.hidden).map(([id]) => id), ['pause','cancel']);

  context.renderActions({status:'ready',phase:'inspected',apply:true});
  assert.deepEqual([...actions].filter(([,value]) => !value.hidden).map(([id]) => id), ['inspect','start']);

  context.renderActions({status:'failed',phase:'staging',apply:true});
  assert.deepEqual([...actions].filter(([,value]) => !value.hidden).map(([id]) => id), ['inspect','resume']);
});
