const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const { readFileSync } = require('node:fs');
const { makeHandler } = require('../api/availability');
const script = readFileSync(require.resolve('../site/checkout.js'), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
function fixture(data = { available: true, priceUSD: 50, architecture: 'arm64' }, saved = null) {
  const document = { body: {}, activeElement: null }; document.activeElement = document.body;
  const elements = new Map(); const calls = []; const pending = []; const navigations = []; let stored;
  document.getElementById = id => {
    if (!elements.has(id)) {
      const e = { hidden: id === 'checkout-panel', textContent: '', events: {}, removeAttribute() {}, contains(other) { return other === this; },
        addEventListener(name, fn) { this.events[name] = fn; }, focus() { document.activeElement = this; } };
      let disabled;
      Object.defineProperty(e, 'disabled', { get: () => disabled, set(v) { disabled = v; if (v && document.activeElement === e) document.activeElement = document.body; } });
      elements.set(id, e);
    }
    return elements.get(id);
  };
  vm.runInNewContext(script, { document, URL, AbortSignal, crypto: { randomUUID: () => 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa' },
    sessionStorage: { getItem: () => saved, setItem: (key, value) => stored = value },
    location: { assign: url => navigations.push(url) },
    fetch: (url, options) => {
      calls.push({ url, options });
      if (url === '/api/availability') return Promise.resolve({ ok: true, json: async () => data });
      return new Promise(resolve => pending.push(resolve));
    } });
  return { document, get: document.getElementById, calls, navigations, stored: () => stored,
    finish: async (value, ok = true, status = ok ? 200 : 503) => {
      pending.shift()({ ok, status, json: async () => { if (value instanceof Error) throw value; return value; } }); await tick();
    } };
}
for (const data of [{ available: false }, { available: true, priceUSD: 49, architecture: 'arm64' },
  { available: true, priceUSD: 50, architecture: 'other' }]) test('non-ready response preserves launch-only UI', async () => {
  const f = fixture(data); await tick(); assert.equal(f.get('checkout-panel').hidden, true); assert.equal(f.get('launch-email').hidden, false);
});
test('ready release displays hardware and honest $50 price without starting checkout', async () => {
  const f = fixture(); await tick(); assert.equal(f.get('checkout-panel').hidden, false);
  assert.match(f.get('checkout-platform').textContent, /Apple silicon Macs.*50 USD/);
  assert.equal(f.get('launch-email').hidden, true); assert.equal(f.calls.length, 1); assert.equal(f.navigations.length, 0);
});
test('delayed readiness preserves a focused or filled launch form', async () => {
  const focused = fixture(); focused.get('launch-email').focus(); await tick();
  assert.equal(focused.get('launch-email').hidden, false);
  assert.equal(focused.document.activeElement, focused.get('launch-email'));
  const filled = fixture(); filled.get('launch-address').value = 'test@example.com'; await tick();
  assert.equal(filled.get('launch-email').hidden, false);
  assert.equal(filled.get('checkout-panel').hidden, false);
});
test('explicit click suppresses duplicates, preserves idempotency on retry and restores focus', async () => {
  const f = fixture(); await tick(); const b = f.get('checkout-button'); b.focus(); b.events.click(); b.events.click();
  assert.equal(f.calls.length, 2); await f.finish({ error: 'temporarily_unavailable' }, false);
  assert.equal(f.document.activeElement, b); assert.match(f.get('checkout-status').textContent, /do not pay again/);
  b.events.click(); assert.equal(f.calls[1].options.body, f.calls[2].options.body);
  await f.finish({ url: 'https://checkout.stripe.com/c/pay/cs_test_fixture' });
  assert.deepEqual(f.navigations, ['https://checkout.stripe.com/c/pay/cs_test_fixture']);
  assert.equal(JSON.parse(f.stored()).id, JSON.parse(f.calls[1].options.body).requestId);
});
test('reload retains a recent checkout request and does not steal moved focus', async () => {
  const id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'; const f = fixture(undefined, JSON.stringify({ id, at: Date.now() }));
  await tick(); const b = f.get('checkout-button'); b.focus(); b.events.click(); const help = f.get('help'); help.focus();
  await f.finish({ error: 'checkout_closed' }, false); assert.equal(f.document.activeElement, help);
  assert.equal(JSON.parse(f.calls[1].options.body).requestId, id);
});
test('untrusted checkout redirects are rejected', async () => {
  const f = fixture(); await tick(); f.get('checkout-button').events.click();
  await f.finish({ url: 'https://evil.example/checkout' }); assert.equal(f.navigations.length, 0);
});
test('edge HTML rate-limit response provides a wait instruction and reusable retry', async () => {
  const f = fixture(); await tick(); const button = f.get('checkout-button'); button.focus(); button.events.click();
  await f.finish(Error('not JSON'), false, 429);
  assert.match(f.get('checkout-status').textContent, /Wait a minute/);
  assert.equal(f.document.activeElement, button); assert.equal(button.disabled, false);
  button.events.click(); assert.equal(f.calls[1].options.body, f.calls[2].options.body);
  await f.finish({ url: 'https://checkout.stripe.com/c/pay/fixture' });
  assert.equal(f.navigations.length, 1);
});
function response() { return { setHeader() {}, end(text) { this.value = JSON.parse(text); } }; }
test('availability defaults closed without configuration or network calls', () => {
  const res = response(); makeHandler(() => { throw Error('must not load'); }, {})({ method: 'GET' }, res);
  assert.deepEqual(res.value, { available: false });
});
test('sandbox cannot advertise a live purchase', () => {
  const res = response(); makeHandler(() => { throw Error('must not load'); }, { COMMERCE_CHECKOUT_OPEN: 'yes', COMMERCE_MODE: 'sandbox' })({ method: 'GET' }, res);
  assert.deepEqual(res.value, { available: false });
});
test('availability returns only price and hardware, never secret configuration', () => {
  const res = response(); makeHandler(() => ({ live: true, key: 'private', release: { filename: 'Codex-Migrate-0.1.0-build1-arm64.zip' } }),
    { COMMERCE_CHECKOUT_OPEN: 'yes', COMMERCE_MODE: 'live' })({ method: 'GET' }, res);
  assert.deepEqual(res.value, { available: true, priceUSD: 50, architecture: 'arm64' });
});
