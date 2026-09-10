const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const { readFileSync } = require('node:fs');
const source = readFileSync(require.resolve('../site/purchase.js'), 'utf8');
const sha256 = 'a'.repeat(64);
const good = { url: `https://fixturestore.private.blob.vercel-storage.com/sandbox/${sha256}/fixture.zip?signed=fixture`,
  sha256, filename: 'fixture.zip', expiresAt: 1788580000000, expiresInMs: 300000 };
const tick = () => new Promise(resolve => setImmediate(resolve));
const privateToken = 'cs_test_fixture.' + 'b'.repeat(64);
function fixture(options = {}) {
  const document = { body: {}, activeElement: null }; document.activeElement = document.body;
  const analyticsEvents = [];
  document.dispatchEvent = event => analyticsEvents.push(event.detail);
  const elements = new Map();
  document.getElementById = id => {
    if (!elements.has(id)) {
      const attributes = new Map();
      const e = { hidden: id !== 'purchase-status', textContent: '', events: {},
        addEventListener(name, fn) { this.events[name] = fn; }, focus() { document.activeElement = this; },
        setAttribute(name, value) { attributes.set(name, String(value)); },
        getAttribute(name) { return attributes.has(name) ? attributes.get(name) : null; },
        removeAttribute(name) { attributes.delete(name); } };
      let disabled = false;
      Object.defineProperty(e, 'disabled', { get: () => disabled, set(value) {
        disabled = value; if (value && document.activeElement === e) document.activeElement = document.body;
      } });
      elements.set(id, e);
    }
    return elements.get(id);
  };
  const calls = []; const pending = [];
  let wall = options.now ?? 9000000000000, monotonic = 0;
  const storage = options.storage || new Map();
  const location = { hash: options.hash ?? '#' + privateToken, pathname: '/purchase' };
  vm.runInNewContext(source, { document, location, URL, AbortSignal,
    CustomEvent: class CustomEvent { constructor(type, init) { this.type = type; this.detail = init.detail; } },
    sessionStorage: { getItem: key => { if (options.storageBlocked) throw Error('blocked'); return storage.get(key) ?? null; },
      setItem: (key, value) => { if (options.storageBlocked) throw Error('blocked'); storage.set(key, value); },
      removeItem: key => { if (options.storageBlocked) throw Error('blocked'); storage.delete(key); } },
    Date: { now: () => wall }, performance: { now: () => monotonic }, window: { addEventListener() {} },
    history: { replaceState() { location.hash = ''; } }, fetch: (url, options) => {
      calls.push({ url, options }); return new Promise(resolve => pending.push(resolve));
    } });
  const finish = async (data = good, ok = true, status = ok ? 200 : 503) => {
    pending.shift()({ ok, status, json: async () => { if (data instanceof Error) throw data; return data; } }); await tick();
  };
  return { document, get: document.getElementById, location, calls, finish, storage, analyticsEvents,
    advance(ms, monotonicMs = ms) { wall += ms; monotonic += monotonicMs; } };
}
test('reload rechecks a tab-scoped token and never reuses the old signed file URL', async () => {
  const first = fixture(); await first.finish();
  const stored = first.storage.get('codex-migrate-purchase-v1');
  assert.equal(stored.includes(good.url), false);
  const refreshed = fixture({ hash: '', storage: first.storage });
  assert.equal(refreshed.get('purchase-download').hidden, true);
  assert.equal(JSON.parse(refreshed.calls[0].options.body).credential, privateToken);
  await refreshed.finish({ ...good, url: good.url + 'fresh' });
  assert.equal(refreshed.get('purchase-download').getAttribute('href'), good.url + 'fresh');
});
test('verified purchases emit one conversion across checks and reloads', async () => {
  const first = fixture();
  await first.finish();
  assert.deepEqual(first.analyticsEvents, ['purchase']);
  first.get('purchase-retry').events.click();
  await first.finish({ ...good, url: good.url + 'refresh' });
  assert.deepEqual(first.analyticsEvents, ['purchase']);

  const refreshed = fixture({ hash: '', storage: first.storage });
  await refreshed.finish({ ...good, url: good.url + 'reload' });
  assert.deepEqual(refreshed.analyticsEvents, []);
});
test('checkout session exchange becomes a reloadable token only after verified download response', async () => {
  const f = fixture({ hash: '#session=cs_test_fixture' });
  await f.finish({ token: privateToken }); assert.equal(f.storage.size, 0);
  await f.finish(); assert.equal(JSON.parse(f.storage.get('codex-migrate-purchase-v1')).token, privateToken);
});
for (const offset of [1800000, 1800001, -1]) test(`expired or future recovery record is discarded: ${offset}`, async () => {
  const f = fixture(); await f.finish();
  const next = fixture({ hash: '', storage: f.storage, now: 9000000000000 + offset });
  assert.equal(next.calls.length, 0); assert.equal(next.storage.size, 0);
});
test('a new explicit link replaces the previous tab purchase without fallback', async () => {
  const f = fixture(); await f.finish();
  const next = fixture({ hash: '#invalid-new-link', storage: f.storage });
  assert.equal(next.storage.size, 0);
  assert.equal(JSON.parse(next.calls[0].options.body).credential, 'invalid-new-link');
  await next.finish({ error: 'invalid_link' }, false); assert.equal(next.storage.size, 0);
});
test('refund on reload hides download and clears tab recovery', async () => {
  const f = fixture(); await f.finish();
  const next = fixture({ hash: '', storage: f.storage });
  await next.finish({ error: 'purchase_requires_support' }, false);
  assert.equal(next.get('purchase-download').hidden, true); assert.equal(next.storage.size, 0);
});
test('blocked storage does not prevent emailed-link downloads', async () => {
  const f = fixture({ storageBlocked: true }); await f.finish();
  assert.equal(f.get('purchase-download').hidden, false); assert.equal(f.storage.size, 0);
});
test('malformed tab storage is discarded without requesting a purchase', () => {
  const f = fixture({ hash: '', storage: new Map([['codex-migrate-purchase-v1', '{bad']]) });
  assert.equal(f.calls.length, 0); assert.equal(f.storage.size, 0);
});
test('page strips bearer fragment and gives a verified URL to the buyer click; no browser clock gate', async () => {
  const f = fixture(); assert.equal(f.location.hash, '');
  await f.finish(); assert.equal(f.get('purchase-download').hidden, false);
  assert.equal(f.calls[0].url, '/api/purchase'); assert.equal(f.calls[0].options.method, 'POST');
  assert.equal(f.calls[0].options.credentials, 'same-origin');
  const link = f.get('purchase-download'); assert.equal(link.getAttribute('href'), good.url);
  link.focus(); const click = { defaultPrevented: false, preventDefault() { this.defaultPrevented = true; } };
  link.events.click(click); assert.equal(click.defaultPrevented, false); assert.equal(f.calls.length, 1);
  assert.equal(f.document.activeElement, link);
  assert.match(f.get('purchase-status').textContent, /Download requested/);
  assert.equal(f.get('purchase-retry').hidden, false);
  assert.equal(f.get('purchase-retry').textContent, 'Get a fresh link');
});
for (const [name, wall, mono] of [['ordinary expiry', 300000, 300000],
  ['sleep pauses monotonic clock', 300000, 0], ['wall clock moves backward', -300000, 300000]]) {
  test(`${name} refreshes without navigating to the stale URL`, async () => {
    const f = fixture(); await f.finish(); f.advance(wall, mono);
    const link = f.get('purchase-download'); link.focus();
    const event = { prevented: false, preventDefault() { this.prevented = true; } };
    link.events.click(event);
    assert.equal(event.prevented, true); assert.equal(link.getAttribute('href'), null);
    assert.equal(f.calls.length, 2);
    link.events.click(event); assert.equal(f.calls.length, 2, 'no duplicate refresh while busy');
    await f.finish({ ...good, url: good.url + '2' });
    assert.equal(link.getAttribute('href'), good.url + '2');
    assert.equal(f.document.activeElement, link);
    assert.match(f.get('purchase-status').textContent, /Select Download for Mac/);
  });
}
test('slow response cannot make an already stale link navigable', async () => {
  const f = fixture(); f.advance(300000); await f.finish();
  let prevented = false;
  f.get('purchase-download').events.click({ preventDefault() { prevented = true; } });
  assert.equal(prevented, true); assert.equal(f.calls.length, 2);
});
test('explicit refresh rechecks authority and leaves support recovery after a refund', async () => {
  const f = fixture(); await f.finish();
  f.get('purchase-download').events.click({ preventDefault() {} });
  const retry = f.get('purchase-retry'); retry.focus(); retry.events.click();
  await f.finish({ error: 'purchase_requires_support' }, false);
  assert.equal(f.get('purchase-download').hidden, true);
  assert.equal(retry.textContent, 'Check again');
  assert.equal(f.document.activeElement, retry);
});
for (const expiresInMs of [undefined, 0, -1, 300001, '300000', NaN]) {
  test(`invalid remaining lifetime ${expiresInMs} never exposes a file link`, async () => {
    const f = fixture(); await f.finish({ ...good, expiresInMs });
    assert.equal(f.get('purchase-download').getAttribute('href'), null);
    assert.equal(f.get('purchase-retry').hidden, false);
  });
}
test('edge HTML rate-limit response leaves recovery available without another purchase', async () => {
  const f = fixture(); await f.finish(Error('not JSON'), false, 429);
  assert.match(f.get('purchase-status').textContent, /Wait a minute.*Do not purchase again/);
  assert.equal(f.get('purchase-retry').hidden, false);
  f.get('purchase-retry').focus(); f.get('purchase-retry').events.click(); await f.finish();
  assert.equal(f.document.activeElement, f.get('purchase-download'));
});
for (const moved of [false, true]) test(`failed download preserves useful focus, user moved=${moved}`, async () => {
  const f = fixture(); await f.finish();
  const button = f.get('purchase-download'); button.removeAttribute('href'); button.focus();
  button.events.click({ preventDefault() {} });
  const help = f.get('help'); if (moved) help.focus();
  await f.finish({ error: 'purchase_requires_support' }, false);
  assert.equal(f.get('purchase-retry').hidden, false);
  assert.equal(f.document.activeElement, moved ? help : f.get('purchase-retry'));
  f.get('purchase-retry').focus(); f.get('purchase-retry').events.click(); await f.finish();
  assert.equal(f.document.activeElement, f.get('purchase-download'));
});
for (const url of ['https://github.com/jsegeren/codex-migrate/releases/download/v1/app.zip',
  good.url.replace('.private.', '.public.'), good.url.replace('sandbox/', '../'),
  good.url + '#private', 'https://evil.example/app.zip?signed=fixture']) {
  test('page rejects a non-private or malformed destination', async () => {
    const f = fixture(); await f.finish({ ...good, url });
    assert.equal(f.get('purchase-download').hidden, true);
    assert.equal(f.get('purchase-download').getAttribute('href'), null);
  });
}
