const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const { readFileSync } = require('node:fs');
const source = readFileSync(require.resolve('../site/purchase.js'), 'utf8');
const sha256 = 'a'.repeat(64);
const good = { url: `https://fixturestore.private.blob.vercel-storage.com/sandbox/${sha256}/fixture.zip?signed=fixture`,
  sha256, filename: 'fixture.zip', expiresAt: 1788580000000 };
const tick = () => new Promise(resolve => setImmediate(resolve));
function fixture() {
  const document = { body: {}, activeElement: null }; document.activeElement = document.body;
  const elements = new Map();
  document.getElementById = id => {
    if (!elements.has(id)) {
      const e = { hidden: id !== 'purchase-status', textContent: '', events: {},
        addEventListener(name, fn) { this.events[name] = fn; }, focus() { document.activeElement = this; } };
      let disabled = false;
      Object.defineProperty(e, 'disabled', { get: () => disabled, set(value) {
        disabled = value; if (value && document.activeElement === e) document.activeElement = document.body;
      } });
      elements.set(id, e);
    }
    return elements.get(id);
  };
  const calls = []; const pending = []; const navigations = [];
  const location = { hash: '#private-fixture', pathname: '/purchase', assign: u => navigations.push(u) };
  vm.runInNewContext(source, { document, location, URL, AbortSignal, window: { addEventListener() {} },
    history: { replaceState() { location.hash = ''; } }, fetch: (url, options) => {
      calls.push({ url, options }); return new Promise(resolve => pending.push(resolve));
    } });
  const finish = async (data = good, ok = true, status = ok ? 200 : 503) => {
    pending.shift()({ ok, status, json: async () => { if (data instanceof Error) throw data; return data; } }); await tick();
  };
  return { document, get: document.getElementById, location, calls, finish, navigations };
}
test('page strips bearer fragment and waits for explicit download; no browser clock gate', async () => {
  const f = fixture(); assert.equal(f.location.hash, '');
  await f.finish(); assert.equal(f.get('purchase-download').hidden, false); assert.equal(f.navigations.length, 0);
  assert.equal(f.calls[0].url, '/api/purchase'); assert.equal(f.calls[0].options.method, 'POST');
  assert.equal(f.calls[0].options.credentials, 'same-origin');
  const button = f.get('purchase-download'); button.focus(); button.events.click(); button.events.click();
  assert.equal(f.calls.length, 2); await f.finish();
  assert.deepEqual(f.navigations, [good.url]); assert.equal(f.document.activeElement, button);
  assert.match(f.get('purchase-status').textContent, /Download requested/);
});
test('edge HTML rate-limit response leaves recovery available without another purchase', async () => {
  const f = fixture(); await f.finish(Error('not JSON'), false, 429);
  assert.match(f.get('purchase-status').textContent, /Wait a minute.*Do not purchase again/);
  assert.equal(f.get('purchase-retry').hidden, false);
  f.get('purchase-retry').focus(); f.get('purchase-retry').events.click(); await f.finish();
  assert.equal(f.document.activeElement, f.get('purchase-download'));
  assert.equal(f.navigations.length, 0);
});
for (const moved of [false, true]) test(`failed download preserves useful focus, user moved=${moved}`, async () => {
  const f = fixture(); await f.finish();
  const button = f.get('purchase-download'); button.focus(); button.events.click();
  const help = f.get('help'); if (moved) help.focus();
  await f.finish({ error: 'purchase_requires_support' }, false);
  assert.equal(f.navigations.length, 0); assert.equal(f.get('purchase-retry').hidden, false);
  assert.equal(f.document.activeElement, moved ? help : f.get('purchase-retry'));
  f.get('purchase-retry').focus(); f.get('purchase-retry').events.click(); await f.finish();
  assert.equal(f.document.activeElement, f.get('purchase-download'));
});
for (const url of ['https://github.com/jsegeren/codex-migrate/releases/download/v1/app.zip',
  good.url.replace('.private.', '.public.'), good.url.replace('sandbox/', '../'),
  good.url + '#private', 'https://evil.example/app.zip?signed=fixture']) {
  test('page rejects a non-private or malformed destination', async () => {
    const f = fixture(); await f.finish({ ...good, url });
    assert.equal(f.get('purchase-download').hidden, true); assert.equal(f.navigations.length, 0);
  });
}
