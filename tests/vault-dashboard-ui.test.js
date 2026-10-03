const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { test } = require('node:test');
const vm = require('node:vm');

const source = readFileSync(new URL('../src/codex_migrate/vault_dashboard.py', `file://${__filename}`), 'utf8');
const displayTitle = vm.runInNewContext(
  '(' + source.match(/function displayTitle\([\s\S]*?\n\}/)[0] + ')');
const runSearch = source.match(/async function runSearch\(append=false\)\{[\s\S]*?\n\}/)[0];
const completeVisibleConversation = vm.runInNewContext(
  '(' + source.match(/function completeVisibleConversation\([\s\S]*?\n\}/)[0] + ')');
const threadParams = vm.runInNewContext(
  '(' + source.match(/function params\([\s\S]*?\n\}/)[0] + ')', { URLSearchParams });
const markdownFile = source.match(/async function markdownFile\(\)\{[\s\S]*?\n\}/)[0];
const backupView = source.match(/function backupView\(data\)\{[\s\S]*?\n\}/)[0];
const scheduleView = source.match(/function scheduleView\(data\)\{[\s\S]*?\n\}/)[0];
const summaryCallback = source.match(/api\("\/api\/vault\/summary"\)\.then\(data=>\{([\s\S]*?)\}\)\.catch/)[1];
const hostedRecoveryView = source.match(/function hostedRecoveryView\(data\)\{[\s\S]*?\n\}/)[0];
const hostedRecoveryStep = source.match(/async function hostedRecoveryStep\(action,step=\{\}\)\{[\s\S]*?\n\}/)[0];
const refreshHostedRecovery = source.match(/async function refreshHostedRecovery\(\)\{[\s\S]*?\n\}/)[0];
const hostedSetupView = source.match(/function hostedSetupView\(data\)\{[\s\S]*?\n\}/)[0];
const hostedSetupStep = source.match(/async function hostedSetupStep\(action,step=\{\}\)\{[\s\S]*?\n\}/)[0];
const refreshHostedSetup = source.match(/async function refreshHostedSetup\(\)\{[\s\S]*?\n\}/)[0];
const reviewPathLabel = source.match(/function reviewPathLabel\(path\)\{[\s\S]*?\n\}/)[0];

function setupFixture() {
  const phases = ['start', 'email', 'pairing_checkpoint', 'pairing_uncertain', 'paired', 'key_save', 'key_ready', 'backup_ready', 'pending_upload', 'deletion_review'];
  const blocks = phases.map(phase => ({ dataset: { setupPhase: phase }, hidden: false }));
  const document = { activeElement: { outside: true } };
  const controls = phases.map(phase => ({ phase, disabled: false, focus() { document.activeElement = this; } }));
  const elements = new Map();
  const panel = {
    hidden: true, contains: element => Boolean(element && !element.outside),
    querySelectorAll: selector => selector === '[data-setup-phase]' ? blocks : controls,
    querySelector: selector => controls.find(control => control.phase === selector.match(/phase="([^"]+)"/)[1]),
  };
  const context = {
    $: id => {
      if (id === 'hosted-setup-panel') return panel;
      if (!elements.has(id)) elements.set(id, { id, textContent: '', removeAttribute(name) { delete this[name]; }, focus() { document.activeElement = this; } });
      return elements.get(id);
    }, document, clearInterval: () => {}, setInterval: () => 1,
  };
  vm.createContext(context);
  vm.runInContext('let hostedSetupTimer=null,hostedSetupInterval=0,hostedSetupPhase=null,hostedSetupEpoch=0,hostedUploadReservation=null,hostedDeletionReview=null,hostedBillingUnconfirmed=false; ' + reviewPathLabel + '\n' + hostedSetupView + '\n' + refreshHostedSetup + '\n' + hostedSetupStep, context);
  return { context, panel, controls, elements, blocks, document };
}

test('test checkout is separate, default-off and never substitutes for a backup receipt', () => {
  const { context, elements } = setupFixture();
  const data = { enabled: true, phase: 'key_ready', status: 'ready' };
  context.hostedSetupView(data);
  assert.equal(elements.get('setup-subscription').hidden, true);
  assert.equal(elements.get('setup-first-backup').disabled, false);
  for (const status of ['unchecked', 'not_entitled', 'checkout_required', 'needs_support']) {
    context.hostedSetupView({ ...data, subscription: { enabled: true, status } });
    assert.equal(elements.get('setup-subscription').hidden, false);
    assert.equal(elements.get('setup-first-backup').disabled, true);
    assert.equal(elements.get('setup-begin-subscription').disabled, status !== 'not_entitled');
  }
  context.hostedSetupView({ ...data, subscription: { enabled: true, status: 'subscribed' } });
  assert.equal(elements.get('setup-first-backup').disabled, false);
  assert.match(elements.get('setup-subscription-status').textContent, /protection is not active/);
  assert.match(source, /No real charge is authorized by this preview/);
  assert.match(source, /rel="noopener noreferrer"/);
  assert.match(source, /setup-check-subscription"\)\.onclick=\(\)=>hostedSetupStep\("check_subscription"\)/);
  assert.match(source, /setup-begin-subscription"\)\.onclick=\(\)=>hostedSetupStep\("begin_subscription"\)/);
});

test('test checkout links refuse foreign/live destinations and disappear during uncertainty', async () => {
  const { context, elements } = setupFixture();
  const valid = 'https://checkout.stripe.com/c/pay/cs_test_Synthetic#test';
  const data = { enabled: true, phase: 'key_ready', status: 'ready',
    subscription: { enabled: true, status: 'checkout_required', checkout_url: valid } };
  context.hostedSetupView(data);
  const link = elements.get('setup-subscription-link');
  assert.equal(link.href, valid);
  assert.equal(link.hidden, false);
  for (const url of ['https://foreign.example/c/pay/cs_test_Synthetic',
    'https://checkout.stripe.com/c/pay/cs_live_Synthetic', 'javascript:alert(1)',
    'https://checkout.stripe.com:443/c/pay/cs_test_Synthetic',
    'https://checkout.stripe.com/c/pay/cs_test_Synthetic?bad=\\x']) {
    context.hostedSetupView({ ...data, subscription: { ...data.subscription, checkout_url: url } });
    assert.equal(link.hidden, true);
    assert.equal(link.href, undefined);
  }
  context.hostedSetupView(data);
  context.hostedSetupView({ ...data, status: 'running', step: 'check_subscription' });
  assert.equal(link.href, undefined);
  assert.equal(link.hidden, true);
  context.hostedSetupView(data);
  context.api = async () => { throw Error('unavailable'); };
  await context.refreshHostedSetup();
  assert.equal(link.href, undefined);
  assert.equal(link.hidden, true);
});

test('test entitlement cannot enable background backup and never blocks stopping', () => {
  const { context, elements } = setupFixture();
  const data = { enabled: true, phase: 'backup_ready', status: 'ready',
    last_backup: { source_coverage: 'complete', at_risk_threads: 0 }, background: { enabled: false },
    subscription: { enabled: true, status: 'unchecked' } };
  context.hostedSetupView(data);
  assert.equal(elements.get('setup-enable-schedule').disabled, true);
  context.hostedSetupView({ ...data, background: { enabled: true } });
  assert.equal(elements.get('setup-disable-schedule').disabled, false);
  context.hostedSetupView({ ...data, subscription: { enabled: true, status: 'subscribed' } });
  assert.equal(elements.get('setup-enable-schedule').disabled, false);
});

test('checkout completion retains checkout focus without jumping to the connection step', () => {
  const { context, elements, document } = setupFixture();
  const data = { enabled: true, phase: 'key_ready', status: 'running', step: 'check_subscription',
    subscription: { enabled: true, status: 'unchecked' } };
  context.hostedSetupView(data);
  document.activeElement = elements.get('hosted-setup-status');
  context.hostedSetupView({ ...data, status: 'ready', subscription: { enabled: true, status: 'not_entitled' } });
  assert.equal(document.activeElement.id, 'setup-check-subscription');
  document.activeElement = elements.get('hosted-setup-status');
  const checkout = { enabled: true, status: 'checkout_required',
    checkout_url: 'https://checkout.stripe.com/c/pay/cs_test_Synthetic' };
  context.hostedSetupView({ ...data, status: 'ready', step: 'begin_subscription', subscription: checkout });
  assert.equal(document.activeElement.id, 'setup-subscription-link');
  document.activeElement = { outside: true };
  context.hostedSetupView({ ...data, status: 'ready', step: 'begin_subscription', subscription: checkout });
  assert.equal(document.activeElement.outside, true);
});

test('hosted setup is gated and pairing never claims backup or automatic protection', () => {
  const { context, panel, controls, blocks, elements } = setupFixture();
  context.hostedSetupView({ enabled: false });
  assert.equal(panel.hidden, true);
  context.hostedSetupView({ enabled: true, phase: 'email', status: 'running', step: 'pair' });
  assert.equal(panel.hidden, false);
  assert.ok(controls.every(control => control.disabled));
  assert.equal(blocks.filter(block => !block.hidden).length, 0);
  context.hostedSetupView({ enabled: true, phase: 'pairing_uncertain', status: 'failed', error: 'Not confirmed.' });
  assert.equal(blocks.filter(block => !block.hidden)[0].dataset.setupPhase, 'pairing_uncertain');
  context.hostedSetupView({ enabled: true, phase: 'paired', status: 'ready' });
  assert.match(elements.get('hosted-setup-status').textContent, /Automatic protection is not active/);
  assert.equal(elements.get('hosted-setup-error').textContent, '');
  assert.match(source, /This setup has not created a backup/);
  assert.match(source, /\.brand small,\.protection\{font-size:14px\}/);
  assert.match(source, /if\(view==="backup"\)refreshHostedSetup\(\)/);
  assert.match(source, /@media print\{#hosted-setup-panel,#hosted-recovery-panel\{display:none!important\}\}/);
});

test('unfinished-upload release is separately confirmed and publication disables it', () => {
  const { context, elements } = setupFixture();
  const pending = { reservation_id: 'synthetic-id', remote_status: 'active', can_abandon: true };
  const data = { enabled: true, phase: 'pending_upload', status: 'ready', pending_upload: pending };
  context.hostedSetupView(data);
  assert.equal(elements.get('setup-abandon-upload').disabled, true);
  assert.equal(elements.get('setup-upload-confirmation').hidden, false);
  elements.get('setup-abandon-confirm').checked = true;
  context.hostedSetupView(data);
  assert.equal(elements.get('setup-abandon-upload').disabled, false);
  context.hostedSetupView({ ...data, pending_upload: { ...pending, reservation_id: 'replacement' } });
  assert.equal(elements.get('setup-abandon-confirm').checked, false);
  assert.equal(elements.get('setup-abandon-upload').disabled, true);
  context.hostedSetupView({ ...data, pending_upload: { ...pending, remote_status: 'published', can_abandon: false } });
  assert.equal(elements.get('setup-abandon-upload').hidden, true);
  assert.equal(elements.get('setup-upload-confirmation').hidden, true);
  assert.match(elements.get('setup-upload-detail').textContent, /resume verification/);
});

test('cleanup pending never claims protection or clears the reviewed reference', () => {
  const { context, elements } = setupFixture();
  for (const state of ['cleanup_pending', 'released']) {
    context.hostedSetupView({ enabled: true, phase: 'pending_upload', status: 'ready',
      pending_upload: { reservation_id: 'same-id', remote_status: state, can_abandon: true } });
    assert.equal(elements.get('setup-abandon-upload').textContent, 'Finish upload cleanup');
    assert.match(elements.get('setup-upload-reference').textContent, /same-id/);
    assert.match(elements.get('hosted-setup-status').textContent, /New work may not be backed up/);
    assert.equal(elements.get('setup-enable-schedule').disabled, true);
  }
});

test('release handler sends only an explicitly checked exact reservation and clears confirmation', () => {
  const elements = new Map([['setup-abandon-confirm', { checked: false }], ['setup-abandon-upload', {}]]);
  const calls = [];
  const context = { $: id => elements.get(id), hostedUploadReservation: 'exact-id',
    hostedSetupStep: (action, step) => calls.push({ action, step }) };
  vm.createContext(context);
  vm.runInContext(source.match(/\$\("setup-abandon-upload"\)\.onclick=.*?;\n/)[0], context);
  elements.get('setup-abandon-upload').onclick();
  assert.equal(calls.length, 0);
  elements.get('setup-abandon-confirm').checked = true;
  elements.get('setup-abandon-upload').onclick();
  assert.equal(elements.get('setup-abandon-confirm').checked, false);
  assert.equal(calls[0].action, 'abandon_upload');
  assert.equal(calls[0].step.reservation_id, 'exact-id');
  assert.equal(calls[0].step.confirm_abandon, true);
  assert.doesNotMatch(source, /(?:localStorage|sessionStorage)\.setItem\([^\n]*reservation/);
});

test('deletion review displays every item as text and resets consent on replacement or action', () => {
  const { context, elements } = setupFixture();
  const review = { review_id: 'exact-review', missing_thread_ids: Array.from({length:30},(_,i)=>'thread-'+i),
    missing_files: [{collection:'active',path:'<img src=x onerror=attack>.jsonl\nfake-heading'}],
    missing_attachments:['attachment/pasted-text.txt'] };
  const data = {enabled:true, phase:'deletion_review',status:'ready',deletion_review:review};
  context.hostedSetupView(data);
  const list=elements.get('setup-deletion-list');
  assert.match(list.textContent,/thread-29/);
  assert.match(list.textContent,/<img src=x onerror=attack>/);
  assert.equal(list.innerHTML,undefined);
  assert.match(list.textContent,/\\nfake-heading/);
  assert.equal(elements.get('setup-confirm-deletions').disabled,true);
  elements.get('setup-deletion-confirm').checked=true;
  context.hostedSetupView(data);
  assert.equal(elements.get('setup-confirm-deletions').disabled,false);
  context.hostedSetupView({...data,deletion_review:{...review,review_id:'replacement'}});
  assert.equal(elements.get('setup-deletion-confirm').checked,false);
  elements.get('setup-deletion-confirm').checked=true;
  context.hostedSetupView({...data,status:'running',step:'confirm_deletions'});
  assert.equal(elements.get('setup-deletion-confirm').checked,false);
  assert.equal(elements.get('setup-confirm-deletions').disabled,true);
  context.hostedSetupView({...data,phase:'backup_ready'});
  assert.equal(elements.get('setup-enable-schedule').disabled,true);
  assert.match(elements.get('hosted-setup-status').textContent,/unresolved.*New work may not be backed up/);
  assert.doesNotMatch(source,/setup-deletion-list"\)\.innerHTML/);
});

test('intentional-deletion action names only the checked review and clears consent before request', () => {
  const elements=new Map([['setup-deletion-confirm',{checked:false}],['setup-confirm-deletions',{}]]);
  const calls=[];
  const context={$:id=>elements.get(id),hostedDeletionReview:'exact-review',
    hostedSetupStep:(action,step)=>calls.push({action,step})};
  vm.createContext(context);
  vm.runInContext(source.match(/\$\("setup-confirm-deletions"\)\.onclick=.*?;\n/)[0],context);
  elements.get('setup-confirm-deletions').onclick();
  assert.equal(calls.length,0);
  elements.get('setup-deletion-confirm').checked=true;
  elements.get('setup-confirm-deletions').onclick();
  assert.equal(elements.get('setup-deletion-confirm').checked,false);
  assert.equal(calls[0].action,'confirm_deletions');
  assert.equal(calls[0].step.review_id,'exact-review');
  assert.equal(calls[0].step.confirm_intentional_deletions,true);
  assert.doesNotMatch(source,/(?:localStorage|sessionStorage)\.setItem\([^\n]*review/);
});

test('path labels visibly escape Unicode line separators, bidi and invisible display controls', () => {
  const {context,elements}=setupFixture();
  const path='2026/ok\u2028Missing conversation IDs (999)\u202etxt.lnosj.jsonl';
  const attachment='\u0085\u2029\u2066\u200b\u{e0001}/pasted-text.txt';
  context.hostedSetupView({enabled:true,phase:'deletion_review',status:'ready',deletion_review:{
    review_id:'exact-review',missing_thread_ids:['real-thread'],
    missing_files:[{collection:'active',path}],missing_attachments:[attachment]}});
  const text=elements.get('setup-deletion-list').textContent;
  assert.doesNotMatch(text,/[\u0085\u2028\u2029\u202e\u2066\u200b\u{e0001}]/u);
  for(const escape of ['\\u2028','\\u202e','\\u0085','\\u2029','\\u2066','\\u200b','\\u{e0001}'])assert.ok(text.includes(escape));
  assert.equal(text.split('\n').filter(line=>line.startsWith('Missing conversation IDs')).length,1);
});

test('setup lost reply reads status exactly once without repeating pairing or echoing a private proof', async () => {
  const { context, controls, elements } = setupFixture();
  const calls = [];
  context.api = async (path, payload) => {
    calls.push({ path, payload });
    if (payload) throw Error('private proof must never appear');
    return { enabled: true, phase: 'pairing_uncertain', status: 'failed' };
  };
  await context.hostedSetupStep('pair', { code: 'synthetic' });
  assert.equal(calls.length, 2);
  assert.equal(calls[0].path, '/api/vault/hosted-setup');
  assert.equal(calls[0].payload.step.apply, true);
  assert.equal(calls[1].path, '/api/vault/hosted-setup-status');
  assert.equal(calls[1].payload, undefined);
  assert.ok(controls.every(control => !control.disabled));
  assert.match(elements.get('hosted-setup-error').textContent, /do not repeat a pairing request/);
  assert.doesNotMatch(elements.get('hosted-setup-error').textContent, /private proof/);
});

test('unavailable setup status keeps controls disabled and never retries a mutation', async () => {
  const { context, controls, elements } = setupFixture();
  const calls = [];
  context.api = async (path, payload) => { calls.push({ path, payload }); throw Error('private'); };
  await context.hostedSetupStep('pair', { code: 'synthetic' });
  assert.equal(calls.filter(call => call.payload).length, 1);
  assert.ok(controls.every(control => control.disabled));
  assert.match(elements.get('hosted-setup-error').textContent, /status is unavailable/);
  assert.doesNotMatch(elements.get('hosted-setup-error').textContent, /private/);
});

test('setup phase changes move owned focus without stealing outside focus', () => {
  const { context, controls, document } = setupFixture();
  context.hostedSetupView({ enabled: true, phase: 'start', status: 'ready' });
  assert.equal(document.activeElement.outside, true);
  document.activeElement = controls[0];
  context.hostedSetupView({ enabled: true, phase: 'email', status: 'running', step: 'send_code' });
  assert.equal(document.activeElement.id, 'hosted-setup-status');
  context.hostedSetupView({ enabled: true, phase: 'email', status: 'ready' });
  assert.equal(document.activeElement.phase, 'email');
});

test('setup private fields clear before requests and never enter browser storage', async () => {
  const elements = new Map([['setup-purchase', { value: ' synthetic receipt ' }], ['setup-code', { value: ' synthetic code ' }]]);
  const calls = [];
  const context = { $: id => elements.get(id), hostedSetupStep: (action, step) => {
    assert.equal(elements.get(action === 'pair' ? 'setup-code' : 'setup-purchase').value, '');
    calls.push({ action, step });
  } };
  vm.createContext(context);
  for (const id of ['setup-send-code', 'setup-pair']) {
    elements.set(id, {});
    vm.runInContext(source.match(new RegExp('\\$\\("' + id + '"\\)\\.onclick=.*?;\\n'))[0], context);
    elements.get(id).onclick();
  }
  assert.equal(calls[0].step.purchase_link, 'synthetic receipt');
  assert.equal(calls[1].step.code, 'synthetic code');
  assert.match(source, /id="setup-purchase" type="password" autocomplete="off"/);
  assert.match(source, /id="setup-code" type="password" autocomplete="off"/);
  assert.doesNotMatch(source, /(?:sessionStorage|localStorage)\.setItem\([^\n]*(?:purchase_link|setup-code|setup-purchase)/);
});

test('recovery key display clears on running, success, disable and failed status', async () => {
  const { context, elements } = setupFixture();
  context.hostedSetupView({ enabled: true, phase: 'key_save', status: 'ready', recovery_key: 'synthetic' });
  assert.equal(elements.get('setup-recovery').value, 'synthetic');
  context.hostedSetupView({ enabled: true, phase: 'key_save', status: 'running', step: 'confirm_key' });
  assert.equal(elements.get('setup-recovery').value, '');
  context.hostedSetupView({ enabled: true, phase: 'key_ready', status: 'ready' });
  assert.equal(elements.get('setup-recovery').value, '');
  assert.match(elements.get('hosted-setup-status').textContent, /Automatic protection is not active/);
  context.hostedSetupView({ enabled: true, phase: 'key_save', status: 'ready', recovery_key: 'synthetic' });
  context.api = async () => { throw Error('private'); };
  await context.refreshHostedSetup();
  assert.equal(elements.get('setup-recovery').value, '');
  context.hostedSetupView({ enabled: false });
  assert.equal(elements.get('setup-recovery').value, '');
  assert.match(source, /This check does not prove recovery on another Mac/);
  assert.match(source, /Do not keep the only copy on this Mac or inside its backup/);
});

test('saved recovery-key input clears before confirmation and is never persisted', () => {
  const elements = new Map([['setup-saved-key', { value: ' synthetic saved key ' }], ['setup-confirm-key', {}]]);
  let captured;
  const context = { $: id => elements.get(id), hostedSetupStep: (action, step) => {
    assert.equal(elements.get('setup-saved-key').value, '');
    captured = { action, step };
  } };
  vm.createContext(context);
  vm.runInContext(source.match(/\$\("setup-confirm-key"\)\.onclick=.*?;\n/)[0], context);
  elements.get('setup-confirm-key').onclick();
  assert.equal(captured.action, 'confirm_key');
  assert.equal(captured.step.recovery_key, 'synthetic saved key');
  assert.match(source, /id="setup-saved-key" type="password" autocomplete="off"/);
  assert.doesNotMatch(source, /(?:localStorage|sessionStorage)\.setItem\([^\n]*(?:setup-recovery|setup-saved-key|recovery_key)/);
});

test('an older status response cannot repaint recovery material after confirmation', async () => {
  const { context, elements } = setupFixture();
  context.hostedSetupView({ enabled: true, phase: 'key_save', status: 'ready', recovery_key: 'synthetic' });
  let resolveOldStatus;
  context.api = async (path, payload) => payload ?
    { enabled: true, phase: 'key_ready', status: 'ready' } :
    new Promise(resolve => { resolveOldStatus = resolve; });
  const old = context.refreshHostedSetup();
  await context.hostedSetupStep('confirm_key', { recovery_key: 'synthetic' });
  resolveOldStatus({ enabled: true, phase: 'key_save', status: 'ready', recovery_key: 'synthetic' });
  await old;
  assert.equal(elements.get('setup-recovery').value, '');
  assert.match(elements.get('hosted-setup-status').textContent, /Saved recovery key confirmed/);
});

test('first hosted backup is an explicit action and never claims automatic protection', async () => {
  const { context, elements, blocks } = setupFixture();
  const calls = [];
  context.api = async (path, payload) => {
    calls.push({ path, payload });
    return { enabled: true, status: 'running', phase: 'key_ready', step: 'first_backup' };
  };
  await context.hostedSetupStep('first_backup');
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [{ path: '/api/vault/hosted-setup',
    payload: { action: 'first_backup', step: { apply: true } } }]);
  assert.match(elements.get('hosted-setup-status').textContent, /Encrypting, uploading and verifying/);
  assert.ok(blocks.every(block => block.hidden));
  for (const status of ['published', 'unchanged', 'needs_attention']) {
    context.hostedSetupView({ enabled: true, status: 'ready', phase: 'backup_ready',
      last_backup: { status }, last_backup_checked_at: '2026-10-01T00:00:00+00:00' });
    assert.match(elements.get('hosted-setup-status').textContent, /Automatic protection is not active/);
    assert.equal(blocks.find(block => block.dataset.setupPhase === 'backup_ready').hidden, false);
    assert.equal(elements.get('setup-recovery').value, '');
    assert.match(elements.get('setup-backup-receipt').textContent,
      status === 'needs_attention' ? /incomplete or at-risk/ : status === 'unchanged' ?
        /existing hosted snapshot was verified again/ : /encrypted conversation manifest/);
  }
  assert.match(source, /This does not back up your Git repositories or your whole Mac/);
  assert.match(source, /Recovery on a clean Mac still needs verification/);
  assert.match(source, /A hosted backup has not yet been confirmed/);
  assert.match(source, /Create or resume hosted backup/);
});

test('background states separate enabled from verified and stop remains available after restart', () => {
  const { context, elements } = setupFixture();
  const intervals = [];
  let clears = 0;
  context.setInterval = (_fn, interval) => { intervals.push(interval); return intervals.length; };
  context.clearInterval = () => { clears++; };
  const ready = { enabled: true, status: 'ready', phase: 'backup_ready',
    last_backup: { status: 'published', source_coverage: 'complete', at_risk_threads: 0 },
    last_backup_checked_at: '2026-10-01T00:00:00+00:00' };
  context.hostedSetupView(ready);
  assert.equal(elements.get('setup-enable-schedule').disabled, false);
  assert.equal(elements.get('setup-disable-schedule').disabled, true);
  assert.equal(elements.get('setup-background').hidden, false);
  for (const status of ['awaiting_check', 'running', 'failed', 'needs_attention', 'verified', 'unchanged']) {
    context.hostedSetupView({ ...ready, background: { enabled: true, status,
      last_checked_at: '2026-10-01T00:00:00+00:00' } });
    assert.equal(elements.get('setup-enable-schedule').disabled, true);
    assert.equal(elements.get('setup-disable-schedule').disabled, false);
    assert.match(elements.get('hosted-setup-status').textContent, /Automatic protection is not active/);
    if (status === 'failed') assert.match(elements.get('setup-background-status').textContent, /may not be backed up/);
    if (status === 'awaiting_check') assert.match(elements.get('setup-background-status').textContent, /has not finished/);
  }
  assert.deepEqual(intervals, [15000]);
  context.hostedSetupView({ ...ready, phase: 'pairing_uncertain', background: { enabled: true } });
  assert.equal(elements.get('setup-disable-schedule').disabled, false);
  context.hostedSetupView({ ...ready, background: { enabled: false, can_stop: true,
    error: 'Hosted backup setup is incomplete.' } });
  assert.equal(elements.get('setup-disable-schedule').disabled, false);
  context.hostedSetupView({ ...ready, status: 'running', step: 'disable_schedule', background: { enabled: true } });
  assert.deepEqual(intervals, [15000, 1500]);
  context.hostedSetupView(ready);
  assert.equal(clears, 2);
  assert.match(source, /Stopping the schedule does not delete backups or cancel hosted storage/);
});

test('incomplete captures cannot enable background backups and controls send explicit actions', () => {
  const { context, elements } = setupFixture();
  context.hostedSetupView({ enabled: true, phase: 'backup_ready', status: 'ready',
    last_backup: { source_coverage: 'needs_attention', at_risk_threads: 1 } });
  assert.equal(elements.get('setup-enable-schedule').disabled, true);
  const actions = [];
  context.hostedSetupStep = action => { actions.push(action); };
  for (const id of ['setup-enable-schedule', 'setup-disable-schedule']) {
    vm.runInContext(source.match(new RegExp('\\$\\("' + id + '"\\)\\.onclick=.*?;\\n'))[0], context);
    elements.get(id).onclick();
  }
  assert.deepEqual(actions, ['enable_schedule', 'disable_schedule']);
});

test('background action completion keeps owned focus on the relevant background control', () => {
  const { context, elements, document } = setupFixture();
  const ready = { enabled: true, status: 'ready', phase: 'backup_ready',
    last_backup: { status: 'published', source_coverage: 'complete', at_risk_threads: 0 } };
  context.hostedSetupView(ready);
  document.activeElement = elements.get('setup-enable-schedule');
  context.hostedSetupView({ ...ready, status: 'running', step: 'enable_schedule' });
  assert.equal(document.activeElement.id, 'hosted-setup-status');
  context.hostedSetupView({ ...ready, step: 'enable_schedule', background: { enabled: true } });
  assert.equal(document.activeElement.id, 'setup-disable-schedule');
  context.hostedSetupView({ ...ready, status: 'running', step: 'disable_schedule', background: { enabled: true } });
  context.hostedSetupView({ ...ready, step: 'disable_schedule', background: { enabled: false } });
  assert.equal(document.activeElement.id, 'setup-enable-schedule');
  context.hostedSetupView({ ...ready, status: 'running', phase: 'pairing_uncertain', step: 'disable_schedule' });
  context.hostedSetupView({ ...ready, phase: 'pairing_uncertain', step: 'disable_schedule' });
  assert.equal(document.activeElement.id, 'setup-background-status');
});

test('hosted recovery stays hidden until enabled and key verification is not recovery', () => {
  const elements = new Map();
  const blocks = ['start', 'prepared', 'key_verified', 'verified'].map(phase => ({
    dataset: { hostedPhase: phase }, hidden: false,
  }));
  const context = {
    $: id => {
      if (!elements.has(id)) elements.set(id, {
        hidden: false, textContent: '', disabled: false, querySelectorAll: () => [],
        contains: () => false,
      });
      return elements.get(id);
    },
    document: { querySelectorAll: () => blocks },
    fmt: value => String(value), clearInterval: () => {}, setInterval: () => 1,
    refreshHostedRecovery: () => {},
  };
  vm.createContext(context);
  vm.runInContext('let hostedRecoveryTimer=null,hostedRecoveryState=null,hostedRecoveryPhase=null; ' + hostedRecoveryView, context);
  context.hostedRecoveryView({ enabled: false });
  assert.equal(elements.get('hosted-recovery-panel').hidden, true);
  context.hostedRecoveryView({ enabled: true, status: 'ready', phase: 'key_verified' });
  assert.equal(elements.get('hosted-recovery-panel').hidden, false);
  assert.match(elements.get('hosted-recovery-status').textContent, /Full backup verification is still needed/);
  assert.equal(blocks.find(block => block.dataset.hostedPhase === 'verified').hidden, true);
  const progress = {stage:'verifying',processed_bytes:100,checked_bytes:100,total_bytes:100,checked_objects:3,total_objects:3};
  context.hostedRecoveryView({enabled:true,status:'running',step:'download',phase:'key_verified',progress});
  assert.equal(elements.get('hosted-stop').hidden, false);
  assert.equal(elements.get('hosted-stop').disabled, false);
  assert.equal(elements.get('hosted-progress').value, 100);
  assert.match(elements.get('hosted-progress-detail').textContent, /Verifying the full encrypted backup/);
  assert.equal(blocks.find(block => block.dataset.hostedPhase === 'verified').hidden, true);
  context.hostedRecoveryView({enabled:true,status:'running',step:'download',phase:'key_verified',progress,stop_requested:true});
  assert.equal(elements.get('hosted-stop').disabled, true);
  assert.match(elements.get('hosted-recovery-status').textContent, /Stopping after the current/);
  context.hostedRecoveryView({enabled:true,status:'stopped',step:'download',phase:'key_verified',progress});
  assert.equal(elements.get('hosted-stop').hidden, true);
  assert.equal(elements.get('hosted-download').textContent, 'Resume and verify backup');
  assert.match(elements.get('hosted-progress-detail').textContent, /Full backup verification is still required/);
  assert.doesNotMatch(elements.get('hosted-progress-detail').textContent, /Verifying the full/);
  context.hostedRecoveryView({ enabled: true, status: 'ready', phase: 'verified', needs_attention: true });
  assert.match(elements.get('hosted-coverage').textContent, /missing or damaged/);
  assert.match(source, /id="hosted-key" type="password" autocomplete="off"/);
  assert.match(source, /\$\("hosted-key"\)\.value=""/);
  assert.doesNotMatch(source, /sessionStorage\.setItem\([^\n]*(?:recovery_key|purchase_link|code)/);
});

function recoveryRequestFixture() {
  const elements = new Map();
  const controls = [{disabled:false}, {disabled:false}];
  const views = [];
  const context = {
    $: id => {
      if (!elements.has(id)) elements.set(id, {querySelectorAll: () => controls,
        textContent: '', contains: () => false});
      return elements.get(id);
    },
    document: { activeElement: null },
    setInterval: () => 1,
    hostedRecoveryView: data => {views.push(data);},
  };
  vm.createContext(context);
  vm.runInContext('let hostedRecoveryTimer=null,hostedRecoveryEpoch=0,hostedRecoveryPoll=0,hostedRecoveryPending=false; ' +
    hostedRecoveryStep + '\n' + refreshHostedRecovery, context);
  return {context, elements, controls, views};
}

test('uncertain hosted response polls state without repeating pairing or exposing private diagnostics', async () => {
  const {context, elements, views} = recoveryRequestFixture();
  const calls = [];
  context.api = async (path, payload) => {
    calls.push({path,payload});
    if (payload) throw Error('private recovery proof');
    return {enabled:true,phase:'pairing_uncertain',status:'failed'};
  };
  await context.hostedRecoveryStep('pair', { vault_id: 'synthetic' });
  assert.equal(calls.length, 2);
  assert.equal(calls[0].payload.step.apply, true);
  assert.equal(calls[1].path, '/api/vault/hosted-recovery-status');
  assert.equal(calls[1].payload, undefined);
  assert.equal(views.length, 1);
  assert.match(elements.get('hosted-recovery-error').textContent, /do not repeat a pairing request/);
  assert.doesNotMatch(elements.get('hosted-recovery-error').textContent, /private recovery proof/);
});

test('recovery ignores a status reply started before a newer action', async () => {
  const {context, views} = recoveryRequestFixture();
  let oldReply;
  context.api = (path, payload) => payload
    ? Promise.resolve({phase:'key_verified',status:'running'})
    : new Promise(resolve => {oldReply=resolve;});
  const pending = context.refreshHostedRecovery();
  await context.hostedRecoveryStep('import_key', {recovery_key:'synthetic'});
  oldReply({phase:'prepared',status:'ready'});
  await pending;
  assert.deepEqual(views.map(value=>value.phase), ['key_verified']);
});

test('recovery holds polling and disabled controls until the action reply is resolved', async () => {
  const {context, views, controls} = recoveryRequestFixture();
  let actionReply;
  let polls=0;
  context.api = (_path, payload) => new Promise(resolve => {
    if (payload) actionReply=resolve;
    else {polls++;resolve({phase:'verified',status:'ready'});}
  });
  const action = context.hostedRecoveryStep('download');
  await context.refreshHostedRecovery();
  assert.equal(polls, 0);
  assert.ok(controls.every(control=>control.disabled));
  actionReply({phase:'key_verified',status:'running'});
  await action;
  assert.deepEqual(views.map(value=>value.status), ['running']);
  await context.refreshHostedRecovery();
  assert.equal(polls, 1);
  assert.deepEqual(views.map(value=>value.phase), ['key_verified','verified']);
});

test('recovery ignores older overlapping poll successes and failures', async () => {
  for (const failOlder of [false,true]) {
    const {context, views, elements} = recoveryRequestFixture();
    const pending = [];
    context.api = () => new Promise((resolve,reject) => {pending.push({resolve,reject});});
    const older = context.refreshHostedRecovery();
    const newer = context.refreshHostedRecovery();
    pending[1].resolve({phase:'verified',status:'ready'});
    await newer;
    if (failOlder) pending[0].reject(Error('stale failure'));
    else pending[0].resolve({phase:'key_verified',status:'running'});
    await older;
    assert.deepEqual(views.map(value=>value.phase), ['verified']);
    assert.notEqual(elements.get('hosted-recovery-error')?.textContent, 'stale failure');
    assert.equal(elements.get('hosted-recovery-error')?.textContent || '', '');
  }
});

test('unavailable current recovery status keeps controls disabled without retrying mutations', async () => {
  const {context, controls, elements, views} = recoveryRequestFixture();
  const calls = [];
  context.api = async (path,payload) => {calls.push({path,payload});throw Error('private proof');};
  await context.hostedRecoveryStep('pair', {vault_id:'synthetic'});
  assert.equal(calls.length, 2);
  assert.ok(controls.every(control=>control.disabled));
  assert.equal(views.length, 0);
  assert.match(elements.get('hosted-recovery-error').textContent, /status is unavailable/);
  assert.doesNotMatch(elements.get('hosted-recovery-error').textContent, /private proof/);
});

test('hosted phase transitions move owned focus and never steal outside focus', () => {
  const elements = new Map();
  const controls = { prepared: { id: 'key' }, key_verified: { id: 'download' } };
  const document = { activeElement: { outside: true }, querySelectorAll: () => [] };
  const context = {
    $: id => {
      if (!elements.has(id)) elements.set(id, { id, textContent: '',
        querySelectorAll: () => [], contains: element => !!element && !element.outside,
        querySelector: selector => controls[selector.match(/phase="([^"]+)"/)[1]],
        focus() { document.activeElement = this; },
      });
      return elements.get(id);
    }, document, clearInterval: () => {}, setInterval: () => 1, refreshHostedRecovery: () => {},
  };
  for (const control of Object.values(controls)) control.focus = () => { document.activeElement = control; };
  vm.createContext(context);
  vm.runInContext('let hostedRecoveryTimer=null,hostedRecoveryState=null,hostedRecoveryPhase=null; ' + hostedRecoveryView, context);
  context.hostedRecoveryView({ enabled: true, phase: 'prepared', status: 'ready' });
  assert.equal(document.activeElement.outside, true);
  document.activeElement = controls.prepared;
  context.hostedRecoveryView({ enabled: true, phase: 'key_verified', status: 'running', step: 'import_key' });
  assert.equal(document.activeElement.id, 'hosted-recovery-status');
  context.hostedRecoveryView({ enabled: true, phase: 'key_verified', status: 'ready' });
  assert.equal(document.activeElement.id, 'download');
  context.hostedRecoveryView({ enabled: true, phase: 'key_verified', status: 'running', step: 'download' });
  assert.match(elements.get('hosted-recovery-status').textContent, /retry this version to resume/);
  document.activeElement = { outside: true };
  context.hostedRecoveryView({ enabled: true, phase: 'verified', status: 'ready' });
  assert.equal(document.activeElement.outside, true);
});

test('local history shows database-backed threads without double-counting them', () => {
  const elements = new Map();
  const render = vm.runInNewContext('(data => {' + summaryCallback + '})', {
    $: id => {
      if (!elements.has(id)) elements.set(id, { textContent: '', hidden: false });
      return elements.get(id);
    },
    fmt: bytes => `${bytes} bytes`,
  });
  assert.match(source, /id="paginated"/);
  assert.match(source, /Database-backed threads may also have transcript files/);
  assert.match(source, /conversations:\["Conversations","Find any conversation\.","Search local Codex transcripts and database-backed history\."\]/);
  render({ active_transcripts: 2, archived_transcripts: 1, transcript_bytes: 12,
    paginated_database_present: true, paginated_threads: 2,
    paginated_database_bytes: 34, attachment_files: 0 });
  assert.equal(elements.get('paginated').textContent, '2');
  assert.equal(elements.get('paginated-note').hidden, false);
  render({ active_transcripts: 2, archived_transcripts: 1, transcript_bytes: 12,
    paginated_database_present: false, paginated_threads: 0,
    paginated_database_bytes: 0, attachment_files: 0 });
  assert.equal(elements.get('paginated').textContent, 'None found');
  assert.equal(elements.get('paginated-note').hidden, true);
});

test('long Codex prompt-titles stay scannable without hiding the matching phrase', () => {
  const title = 'Opening prompt '.repeat(30) + 'Unification Foundation' + ' tail'.repeat(30);
  const excerpt = displayTitle(title, 'Unification Foundation');
  assert.ok(excerpt.length <= 122);
  assert.match(excerpt, /Unification Foundation/);
  assert.match(excerpt, /^…/);
  assert.equal(displayTitle('Line one\n  line two'), 'Line one line two');
  assert.equal(displayTitle('🙂'.repeat(130)).includes('\ufffd'), false);
  assert.match(source, /title\.textContent=displayTitle\(item\.title,query\)/);
  assert.match(source, /displayTitle\(version\.titles\.at\(-1\)/);
});

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
  context.scheduleView({ enabled: true, healthy: false,
    paginated_history_unprotected: true, last_run: { status: 'failed' } });
  assert.match(elements.get('schedule-status').textContent, /latest automatic backup failed/);
  assert.match(elements.get('schedule-status').textContent, /do not assume new conversations are protected/);
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
    displayTitle,
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

test('search warns when ambiguous history copies make results incomplete', async () => {
  const elements = new Map([
    ['search-source', { value: 'local' }],
    ['query', { value: 'lost thread' }],
    ['error', { textContent: '' }],
    ['thread', { hidden: false }],
    ['more-results', { hidden: false, disabled: false }],
    ['status', { textContent: '' }],
    ['index-build', { disabled: false }],
    ['results-panel', { hidden: true }],
    ['results', { children: [], replaceChildren(...nodes) { this.children = nodes; },
      append(...nodes) { this.children.push(...nodes); } }],
    ['salvage-controls', { open: false }],
    ['salvage-status', { textContent: '' }],
  ]);
  const context = {
    $: id => elements.get(id), URLSearchParams,
    api: async url => url.includes('source=local_titles') ? { results: [] } :
      { results: [], has_more: false, partial_results: true },
    fail: error => { elements.get('error').textContent = error.message; },
    setTimeout: () => 1, clearTimeout: () => {},
  };
  vm.createContext(context);
  vm.runInContext('let searchPage=null; let searchRequest=0; ' + runSearch, context);
  await context.runSearch();
  assert.equal(elements.get('error').textContent, '');
  assert.match(elements.get('status').textContent, /Results may be incomplete/);
  assert.equal(elements.get('salvage-controls').open, false);
});

test('physical-copy results carry the explicit read mode and cannot offer copy-back', () => {
  const incomplete = { collection: 'active', transcript: 'rollout-child.jsonl',
    source: 'backup', physical_only: true };
  assert.equal(threadParams(incomplete).get('physical'), '1');
  assert.equal(threadParams({ ...incomplete, physical_only: false }).has('physical'), false);
  assert.match(source, /Incomplete physical copy: inherited fork history is not included/);
  assert.match(source, /thread\.physical_only/);
  assert.match(source, /selected\.physical_only\)return;if\(!confirm\("Restore only/);
  assert.match(source, /physical_only:!!selected\.physical_only/);
});

test('search identifies damaged-file omissions and opens read-only inspection', async () => {
  const elements = new Map([
    ['search-source', { value: 'local' }],
    ['query', { value: 'lost thread' }],
    ['error', { textContent: '' }],
    ['thread', { hidden: false }],
    ['more-results', { hidden: false, disabled: false }],
    ['status', { textContent: '' }],
    ['index-build', { disabled: false }],
    ['results-panel', { hidden: true }],
    ['results', { children: [], replaceChildren(...nodes) { this.children = nodes; },
      append(...nodes) { this.children.push(...nodes); } }],
    ['salvage-controls', { open: false }],
    ['salvage-status', { textContent: '' }],
  ]);
  const context = {
    $: id => elements.get(id), URLSearchParams,
    api: async url => url.includes('source=local_titles') ? { results: [] } :
      { results: [], has_more: false, partial_results: true,
        partial_reasons: ['damaged_transcript'] },
    fail: error => { elements.get('error').textContent = error.message; },
    setTimeout: () => 1, clearTimeout: () => {},
  };
  vm.createContext(context);
  vm.runInContext('let searchPage=null; let searchRequest=0; ' + runSearch, context);
  await context.runSearch();
  assert.equal(elements.get('error').textContent, '');
  assert.match(elements.get('status').textContent, /damaged conversation file was skipped/);
  assert.match(elements.get('status').textContent, /Results may be incomplete/);
  assert.equal(elements.get('salvage-controls').open, true);
});
