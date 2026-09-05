const test = require('node:test');
const assert = require('node:assert/strict');
const { Readable } = require('node:stream');
const Stripe = require('stripe');
const { configuration, SITE } = require('../commerce/config');
const { service, validatePurchase, tokenFor, tokenSession } = require('../commerce/service');
const { deliveryMail } = require('../commerce/runtime');
const { makeHandler: webhook } = require('../api/stripe-webhook');
const { makeHandler: checkout } = require('../api/checkout');
const { makeHandler: purchase } = require('../api/purchase');

const release = { id: 'fixture-1', kind: 'sandbox-fixture', sha256: 'a'.repeat(64), source: 'b'.repeat(40),
  filename: 'fixture.zip', size: 5000, pathname: `sandbox/${'a'.repeat(64)}/fixture.zip` };
const env = { COMMERCE_MODE: 'sandbox', COMMERCE_STRIPE_KEY: 'rk_test_fixture', COMMERCE_LINK_SECRET: 'c'.repeat(64),
  COMMERCE_STRIPE_ACCOUNT: 'acct_fixture', COMMERCE_PRODUCT: 'prod_fixture', COMMERCE_PRICE: 'price_fixture',
  COMMERCE_WEBHOOK_SECRET: 'whsec_fixture', COMMERCE_RELEASE: release.id, COMMERCE_BLOB_STORE_ID: 'fixturestore' };
const config = configuration(env, { [release.id]: release });
const signDownload = async r => ({ url: `https://fixturestore.private.blob.vercel-storage.com/${r.pathname}?fixture=1`, expiresAt: Date.now() + 300000 });
function fixture() {
  const s = { id: 'cs_test_fixture', livemode: false, mode: 'payment', status: 'complete', payment_status: 'paid',
    managed_payments: { enabled: true }, metadata: { product: 'codex-migrate', release: release.id },
    currency: 'usd', amount_subtotal: 5000, amount_total: 5400, total_details: { amount_discount: 0 },
    line_items: { has_more: false, data: [{ quantity: 1, amount_subtotal: 5000,
      price: { id: 'price_fixture', product: 'prod_fixture', livemode: false, type: 'one_time', recurring: null, currency: 'usd', unit_amount: 5000 } }] },
    payment_intent: { id: 'pi_fixture', status: 'succeeded', livemode: false, amount_received: 5400,
      latest_charge: { paid: true, livemode: false, status: 'succeeded', currency: 'usd', amount: 5400,
        refunded: false, amount_refunded: 0, disputed: false } }, customer_details: { email: 'buyer@example.invalid' } };
  const records = new Map(); let sends = 0;
  const store = { ensure: async p => { if (!records.has(p.sessionId)) records.set(p.sessionId, { ...p, state: 'pending' }); },
    claim: async id => { const row = records.get(id); if (row.state !== 'pending') return null; row.state = 'sending'; return 'lease'; },
    mailResult: async (id, mode, lease, result) => { records.get(id).state = result; } };
  const stripe = { accounts: { retrieve: async () => ({ id: 'acct_fixture' }) },
    checkout: { sessions: { retrieve: async () => structuredClone(s) } } };
  const api = service({ config, stripe, store, signDownload, sendMail: async () => { sends++; return 'accepted'; } });
  return { s, api, records, stripe, store, sends: () => sends };
}
test('commerce defaults closed and requires reviewed release, matching key mode and valid secrets', () => {
  assert.throws(() => configuration({}), /checkout_closed/);
  assert.throws(() => configuration(env), /release_unavailable/);
  assert.throws(() => configuration({ ...env, COMMERCE_STRIPE_KEY: 'rk_live_fixture' }, { [release.id]: release }), /not_configured/);
  for (const patch of [{ kind: 'unsigned' }, { url: 'https://evil.example/app.zip' }, { sha256: 'bad' }]) {
    assert.throws(() => configuration(env, { [release.id]: { ...release, ...patch } }), /release_unavailable/);
  }
  assert.throws(() => configuration({ ...env, COMMERCE_MODE: 'live', COMMERCE_STRIPE_KEY: 'rk_live_fixture' }, { [release.id]: release }), /release_unavailable/);
});
test('valid paid purchase verifies actual product, charge, and email', () => {
  assert.equal(validatePurchase(fixture().s, config).sessionId, 'cs_test_fixture');
});
for (const [name, mutate] of [
  ['unpaid', s => s.payment_status = 'unpaid'], ['open', s => s.status = 'open'],
  ['live event', s => s.livemode = true], ['subscription', s => s.mode = 'subscription'],
  ['wrong product metadata', s => s.metadata.product = 'you-one'], ['wrong release', s => s.metadata.release = 'other'],
  ['wrong price', s => s.line_items.data[0].price.id = 'price_other'],
  ['wrong product', s => s.line_items.data[0].price.product = 'prod_other'],
  ['discount', s => s.total_details.amount_discount = 500], ['wrong subtotal', s => s.amount_subtotal = 4900],
  ['wrong quantity', s => s.line_items.data[0].quantity = 2], ['paginated items', s => s.line_items.has_more = true],
  ['multiple items', s => s.line_items.data.push(s.line_items.data[0])],
  ['unexpanded charge', s => s.payment_intent.latest_charge = 'ch_fixture'],
  ['wrong charge amount', s => s.payment_intent.latest_charge.amount = 4000],
  ['pending payment', s => s.payment_intent.status = 'processing'],
  ['refund', s => s.payment_intent.latest_charge.refunded = true],
  ['partial refund', s => s.payment_intent.latest_charge.amount_refunded = 100],
  ['dispute', s => s.payment_intent.latest_charge.disputed = true],
  ['invalid email', s => s.customer_details.email = 'buyer@example.invalid\r\nInjected'],
]) test(`${name} never grants or sends`, async () => {
  const f = fixture(); mutate(f.s);
  await assert.rejects(f.api.fulfill(f.s.id));
  assert.equal(f.records.size, 0); assert.equal(f.sends(), 0);
});
test('concurrent and replayed fulfillment retains one grant and one accepted mail', async () => {
  const f = fixture(); await Promise.all(Array.from({ length: 10 }, () => f.api.fulfill(f.s.id)));
  await f.api.fulfill(f.s.id); assert.equal(f.records.size, 1); assert.equal(f.sends(), 1);
});
test('refund after fulfillment blocks a previously issued download link', async () => {
  const f = fixture(); await f.api.fulfill(f.s.id);
  const token = tokenFor(f.s.id, config);
  assert.equal((await f.api.download(token)).sha256, release.sha256);
  f.s.payment_intent.latest_charge.refunded = true;
  await assert.rejects(f.api.download(token), /requires_support/);
});
test('purchases recover their original artifact after a new current release', async () => {
  const f = fixture();
  const next = { ...release, id: 'fixture-2' };
  const api = service({ config: { ...config, release: next, catalog: { ...config.catalog, [next.id]: next } },
    stripe: f.stripe, store: f.store, signDownload, sendMail: async () => 'accepted' });
  assert.equal((await api.download(tokenFor(f.s.id, config))).release, release.id);
});
test('unapproved historical artifacts cannot become download redirects', async () => {
  const f = fixture();
  const api = service({ config: { ...config, catalog: { [release.id]: { ...release, url: 'https://evil.example/app.zip' } } },
    stripe: f.stripe, store: f.store, sendMail: async () => 'accepted' });
  await assert.rejects(api.download(tokenFor(f.s.id, config)), /release_unavailable/);
});
test('recovery tokens reject tampering, mode mismatch and malformed input', () => {
  const t = tokenFor('cs_test_fixture', config);
  assert.equal(tokenSession(t, config), 'cs_test_fixture');
  for (const bad of [null, '', `${t}.extra`, t.replace('fixture', 'other'), `${t.slice(0, -1)}z`]) assert.throws(() => tokenSession(bad, config));
  assert.throws(() => tokenSession(t, { ...config, live: true }));
});
test('email timeout is recorded as uncertain, with grant preserved', async () => {
  const f = fixture();
  const api = service({ config, stripe: f.stripe, store: f.store, signDownload, sendMail: async () => { throw Error('private provider text'); } });
  await assert.rejects(api.fulfill(f.s.id), /delivery_needs_retry/);
  assert.equal(f.records.get(f.s.id).state, 'uncertain');
  assert.equal((await api.download(tokenFor(f.s.id, config))).release, release.id);
});
test('wrong Stripe account stops before reading a session', async () => {
  const f = fixture(); f.stripe.accounts.retrieve = async () => ({ id: 'acct_other' });
  await assert.rejects(f.api.fulfill(f.s.id), /account_mismatch/);
  assert.equal(f.records.size, 0);
});
function response() {
  return { headers: {}, setHeader(k, v) { this.headers[k] = v; }, end(value) { this.body = JSON.parse(value); } };
}
async function eventRequest(event, signature = true) {
  const raw = JSON.stringify(event); const req = Readable.from([Buffer.from(raw)]);
  req.method = 'POST'; req.headers = { 'stripe-signature': signature ? Stripe.webhooks.generateTestHeaderString({ payload: raw, secret: config.webhookSecret }) : 'bad' };
  return req;
}
test('webhook verifies raw signature, ignores unrelated events and rejects mixed environments', async () => {
  let count = 0;
  const handler = webhook(async () => ({ service: { fulfill: async () => count++ } }), () => config);
  const base = { id: 'evt_fixture', type: 'checkout.session.completed', livemode: false,
    data: { object: fixture().s } };
  let res = response(); await handler(await eventRequest(base, false), res); assert.equal(res.statusCode, 400);
  res = response(); await handler(await eventRequest({ ...base, livemode: true }), res); assert.equal(res.statusCode, 400);
  const unrelated = structuredClone(base); unrelated.data.object.metadata.product = 'you-one';
  res = response(); await handler(await eventRequest(unrelated), res); assert.equal(res.statusCode, 200); assert.equal(count, 0);
  res = response(); await handler(await eventRequest(base), res); assert.equal(res.statusCode, 200); assert.equal(count, 1);
});
test('webhook durable processing failure asks Stripe to retry without leaking provider errors', async () => {
  const handler = webhook(async () => { throw Error('credential-private'); }, () => config);
  const res = response(); await handler(await eventRequest({ type: 'checkout.session.completed', livemode: false, data: { object: fixture().s } }), res);
  assert.equal(res.statusCode, 503); assert.equal(JSON.stringify(res).includes('credential-private'), false);
});
test('checkout stays closed by default without network access', async () => {
  const res = response(); await checkout(() => { throw Error('must not load'); }, {})({ method: 'POST', headers: {} }, res);
  assert.equal(res.statusCode, 503); assert.equal(res.body.error, 'checkout_closed');
});
test('purchase endpoint rejects foreign origins and keeps credentials out of URLs/responses', async () => {
  const res = response(); await purchase(() => { throw Error('must not load'); })({ method: 'POST', headers: { origin: 'https://evil.example' }, body: {} }, res);
  assert.equal(res.statusCode, 403); assert.equal(res.headers['Cache-Control'], 'no-store');
});
test('invalid purchase credentials fail before database access', async () => {
  const res = response();
  await purchase(() => { throw Error('must not load'); }, () => config)({ method: 'POST',
    headers: { origin: SITE, 'content-type': 'application/json' }, body: { action: 'download', credential: 'bad' } }, res);
  assert.equal(res.statusCode, 403); assert.equal(res.body.error, 'invalid_link');
});
test('delivery mail disables tracking and limits sandbox to its approved sink', async () => {
  let count = 0; let sent;
  const request = async (url, options) => { count++; sent = JSON.parse(options.body); return { status: 202 }; };
  const mailEnv = { SENDGRID_API_KEY: 'fixture', LAUNCH_FROM_EMAIL: 'sender@example.invalid', COMMERCE_SANDBOX_EMAIL: 'buyer@example.invalid' };
  const value = { to: 'other@example.invalid', link: 'https://example.invalid/private', release, live: false };
  assert.equal(await deliveryMail(value, mailEnv, request), 'rejected'); assert.equal(count, 0);
  assert.equal(await deliveryMail({ ...value, to: mailEnv.COMMERCE_SANDBOX_EMAIL }, mailEnv, request), 'accepted');
  assert.equal(sent.tracking_settings.click_tracking.enable, false); assert.equal(sent.tracking_settings.open_tracking.enable, false);
  assert.match(sent.subject, /TEST ONLY/);
});
test('mail explicit rejection and uncertain network outcomes remain distinct', async () => {
  const value = { to: 'buyer@example.invalid', link: 'https://example.invalid/private', release, live: true };
  const e = { SENDGRID_API_KEY: 'fixture', LAUNCH_FROM_EMAIL: 'sender@example.invalid' };
  assert.equal(await deliveryMail(value, e, async () => ({ status: 429 })), 'rejected');
  assert.equal(await deliveryMail(value, e, async () => ({ status: 500 })), 'uncertain');
  assert.equal(await deliveryMail(value, e, async () => { throw Error('secret'); }), 'uncertain');
});
