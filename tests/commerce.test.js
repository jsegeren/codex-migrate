const test = require('node:test');
const assert = require('node:assert/strict');
const { Readable } = require('node:stream');
const Stripe = require('stripe');
const { configuration, SITE } = require('../commerce/config');
const { service, checkoutRecovery, validatePurchase, validateCheckoutRecovery,
  purchasePriceCents, tokenFor, tokenSession } = require('../commerce/service');
const { deliveryMail, recoveryMail, PURCHASE_NOTIFY_EMAILS } = require('../commerce/runtime');
const { makeHandler: webhook } = require('../api/stripe-webhook');
const { makeHandler: checkout } = require('../api/checkout');
const { makeHandler: purchase } = require('../api/purchase');

const release = { id: 'fixture-1', kind: 'sandbox-fixture', sha256: 'a'.repeat(64), source: 'b'.repeat(40),
  filename: 'fixture.zip', size: 5000, pathname: `sandbox/${'a'.repeat(64)}/fixture.zip` };
const env = { COMMERCE_MODE: 'sandbox', COMMERCE_STRIPE_KEY: 'rk_test_fixture', COMMERCE_LINK_SECRET: 'c'.repeat(64),
  COMMERCE_STRIPE_ACCOUNT: 'acct_fixture', COMMERCE_PRODUCT: 'prod_fixture', COMMERCE_PRICE: 'price_fixture',
  COMMERCE_WEBHOOK_SECRET: 'whsec_fixture', COMMERCE_RELEASE: release.id, COMMERCE_BLOB_STORE_ID: 'fixturestore' };
const config = configuration(env, { [release.id]: release });
const signDownload = async r => ({ url: `https://fixturestore.private.blob.vercel-storage.com/${r.pathname}?fixture=1`, expiresAt: Date.now() + 300000, expiresInMs: 300000 });
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
function recoveryFixture() {
  const f = fixture();
  delete f.s.managed_payments;
  f.s.metadata.checkout_provider = 'stripe';
  f.s.status = 'expired';
  f.s.payment_status = 'unpaid';
  f.s.payment_intent = null;
  f.s.amount_total = 5000;
  f.s.consent = { promotions: 'opt_in' };
  f.s.after_expiration = { recovery: { enabled: true, url: 'https://buy.stripe.com/r/test_fixture' } };
  let sends = 0;
  const api = checkoutRecovery({ config, stripe: f.stripe, store: f.store,
    sendMail: async () => { sends++; return 'accepted'; } });
  return { ...f, api, sends: () => sends };
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
test('only explicitly approved signed beta manifests are eligible for live distribution', () => {
  const { validRelease } = require('../commerce/config');
  const releases = require('../commerce/releases.json');
  const betas = ['beta-build5-arm64', 'beta-build7-arm64', 'beta-build8-arm64', 'beta-build9-arm64',
    'beta-build10-arm64']
    .map(id => releases[id]);
  for (const beta of betas) {
    assert.equal(validRelease(beta, true), true);
    for (const patch of [{ accepted: false }, { acceptance: undefined }, { channel: 'unknown' },
      { kind: 'unsigned' }, { testingOnly: true }, { pathname: beta.pathname.replace('live/', 'sandbox/') }]) {
      assert.equal(validRelease({ ...beta, ...patch }, true), false);
    }
    assert.equal(validRelease(beta, false), false);
  }
  assert.equal(releases['beta-build7-arm64'].sha256,
    'f244a02c956d2a460d1002caec17d214c78379ba8b09e9b0840b367ab5986fb1');
  assert.equal(releases['beta-build7-arm64'].source, '67a92bb5d8383b542a3962be7868a87f927a871b');
  assert.equal(releases['beta-build8-arm64'].sha256,
    '74a7fc5e2da91901f4a5d3f74969cd03d34549ef6f06d83151825d7727262270');
  assert.equal(releases['beta-build8-arm64'].source, 'f429bf6c234d7b9f925c61f389d6d0513de301fb');
  assert.equal(releases['beta-build9-arm64'].sha256,
    '7aadccacec63b09fe637cd61c506f4730f2de62163687ec56a2cc63ad8306133');
  assert.equal(releases['beta-build9-arm64'].source, '8f1e0225a6babcb1be1be0a876da11edd73732d8');
  assert.equal(releases['beta-build10-arm64'].sha256,
    'f5a1634380c386c3c0c4bfdcab65270cd45c7ffe151b7378d01b9a8be1e6a739');
  assert.equal(releases['beta-build10-arm64'].source, 'c3e398b23d0a0d913bd7567e7d3e512c1d0e0e01');
});
test('beta delivery email includes the remaining checks and both operator alerts without adding tracking', async () => {
  let mail;
  assert.equal(await deliveryMail({ to: 'buyer@example.invalid', live: true, link: 'https://example.invalid/private',
    release: { ...release, channel: 'beta' }, sessionId: 'cs_live_fixture', paymentIntent: 'pi_fixture', amountTotal: 5400 },
  { LAUNCH_FROM_EMAIL: 'sender@example.invalid', SENDGRID_API_KEY: 'fixture' },
  async (url, options) => { mail = JSON.parse(options.body); return { status: 202 }; }), 'accepted');
  assert.match(mail.content[0].value, /signed, notarized beta/);
  assert.match(mail.content[0].value, /testing are ongoing/);
  assert.equal(mail.personalizations.length, 3);
  assert.deepEqual(mail.personalizations.slice(1).map(item => item.to[0].email), PURCHASE_NOTIFY_EMAILS);
  assert.equal(mail.personalizations[0].subject, 'Your Codex Migrate download');
  assert.match(mail.personalizations[0].substitutions['%details%'], /private/);
  for (const alert of mail.personalizations.slice(1)) {
    assert.equal(alert.subject, '[Codex Migrate] New purchase — $54.00 USD');
    assert.match(alert.substitutions['%details%'], /buyer@example\.invalid/);
    assert.match(alert.substitutions['%details%'], /cs_live_fixture/);
    assert.match(alert.substitutions['%closing%'], /dashboard\.stripe\.com\/payments\/pi_fixture/);
    assert.doesNotMatch(alert.substitutions['%details%'] + alert.substitutions['%closing%'], /private/);
  }
  assert.equal(mail.tracking_settings.open_tracking.enable, false);
});
test('valid paid purchase verifies actual product, charge, and email', () => {
  assert.equal(validatePurchase(fixture().s, config).sessionId, 'cs_test_fixture');
});
test('current and legacy live prices retain their exact purchase amounts', () => {
  const live = { ...config, live: true, price: 'price_1UEMgFJfbWpcJIZbPsmXjF2J' };
  assert.equal(purchasePriceCents(live.price, live), 4900);
  assert.equal(purchasePriceCents('price_1UCXtaJfbWpcJIZbp9W60sIv', live), 5000);
  assert.equal(purchasePriceCents('price_unrelated', live), undefined);
  assert.equal(purchasePriceCents('price_1UCXtaJfbWpcJIZbp9W60sIv', config), undefined);
});
test('standard Checkout verifies paid delivery without invalidating older managed purchases', () => {
  const s = fixture().s;
  delete s.managed_payments;
  assert.throws(() => validatePurchase(s, config), /purchase_not_verified/);
  s.metadata.checkout_provider = 'stripe';
  assert.equal(validatePurchase(s, config).sessionId, s.id);
  s.managed_payments = { enabled: false };
  assert.equal(validatePurchase(s, config).sessionId, s.id);
  s.managed_payments.enabled = true;
  assert.throws(() => validatePurchase(s, config), /purchase_not_verified/);
  assert.equal(validatePurchase(fixture().s, { ...config, checkoutProvider: 'stripe' }).sessionId, s.id);
  for (const mutation of [s => s.payment_status = 'unpaid', s => s.line_items.data[0].price.id = 'price_wrong',
    s => s.payment_intent.latest_charge.refunded = true]) {
    const bad = fixture().s; delete bad.managed_payments; bad.metadata.checkout_provider = 'stripe';
    mutation(bad); assert.throws(() => validatePurchase(bad, config));
  }
});
test('expired Checkout recovery requires an opted-in, exact Stripe recovery session', () => {
  assert.equal(validateCheckoutRecovery(recoveryFixture().s, config).link,
    'https://buy.stripe.com/r/test_fixture');
  for (const mutate of [
    s => s.status = 'open',
    s => s.payment_status = 'paid',
    s => s.consent.promotions = 'opt_out',
    s => s.after_expiration.recovery.enabled = false,
    s => s.after_expiration.recovery.url = 'https://evil.example/r/test_fixture',
    s => s.after_expiration.recovery.url = 'https://buy.stripe.com/r/test_fixture?token=leak',
    s => s.metadata.product = 'you-one',
    s => s.line_items.data[0].price.id = 'price_other',
    s => s.customer_details.email = 'buyer@example.invalid\r\nInjected',
  ]) {
    const f = recoveryFixture(); mutate(f.s);
    assert.throws(() => validateCheckoutRecovery(f.s, config), /checkout_recovery_not_verified/);
  }
});
test('concurrent and replayed checkout recovery sends at most one reminder', async () => {
  const f = recoveryFixture();
  await Promise.all(Array.from({ length: 10 }, () => f.api.recover(f.s.id)));
  await f.api.recover(f.s.id);
  assert.equal(f.records.size, 1);
  assert.equal(f.sends(), 1);
});
test('Checkout provider selection is explicit and rejects typos', () => {
  const catalog = { [release.id]: release };
  assert.equal(configuration(env, catalog).checkoutProvider, 'managed');
  assert.equal(configuration({ ...env, COMMERCE_CHECKOUT_PROVIDER: 'stripe' }, catalog).checkoutProvider, 'stripe');
  assert.throws(() => configuration({ ...env, COMMERCE_CHECKOUT_PROVIDER: 'other' }, catalog), /invalid_checkout_provider/);
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
  assert.equal((await f.api.download(token)).expiresInMs, 300000);
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
test('webhook sends recovery only for an opted-in expired Codex Migrate checkout', async () => {
  let recoveries = 0; let loads = 0;
  const handler = webhook(async () => { loads++; return {
    service: { fulfill: async () => { throw Error('wrong path'); } },
    recovery: { recover: async () => recoveries++ },
  }; }, () => config);
  const expired = recoveryFixture().s;
  let event = { id: 'evt_expired_fixture', type: 'checkout.session.expired', livemode: false,
    data: { object: expired } };
  let res = response(); await handler(await eventRequest(event), res);
  assert.equal(res.statusCode, 200); assert.equal(loads, 1); assert.equal(recoveries, 1);
  const optedOut = structuredClone(event); optedOut.data.object.consent.promotions = 'opt_out';
  res = response(); await handler(await eventRequest(optedOut), res);
  assert.equal(res.statusCode, 200); assert.equal(loads, 1); assert.equal(recoveries, 1);
  const unrelated = structuredClone(event); unrelated.data.object.metadata.product = 'you-one';
  res = response(); await handler(await eventRequest(unrelated), res);
  assert.equal(res.statusCode, 200); assert.equal(loads, 1); assert.equal(recoveries, 1);
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
  assert.equal(sent.personalizations.length, 1);
  assert.equal(sent.tracking_settings.click_tracking.enable, false); assert.equal(sent.tracking_settings.open_tracking.enable, false);
  assert.deepEqual(sent.reply_to, { email: 'joshua@segeren.com', name: 'Joshua Segeren' });
  assert.match(sent.personalizations[0].subject, /TEST ONLY/);
  assert.match(sent.personalizations[0].substitutions['%intro%'], /No real purchase or app is delivered/);
  assert.equal(await deliveryMail({ ...value, to: mailEnv.COMMERCE_SANDBOX_EMAIL,
    release: { ...release, kind: 'signed-notarized', testingOnly: true } }, mailEnv, request), 'accepted');
  assert.match(sent.personalizations[0].substitutions['%intro%'], /signed app candidate for operator testing/);
  assert.match(sent.personalizations[0].substitutions['%intro%'], /No real payment was charged/);
  assert.doesNotMatch(sent.personalizations[0].substitutions['%intro%'], /No real purchase or app is delivered/);
  assert.equal(await deliveryMail({ ...value, live: true }, mailEnv, request), 'accepted');
  assert.deepEqual(sent.reply_to, { email: 'joshua@segeren.com', name: 'Joshua Segeren' });
});
test('mail explicit rejection and uncertain network outcomes remain distinct', async () => {
  const value = { to: 'buyer@example.invalid', link: 'https://example.invalid/private', release, live: true };
  const e = { SENDGRID_API_KEY: 'fixture', LAUNCH_FROM_EMAIL: 'sender@example.invalid' };
  assert.equal(await deliveryMail(value, e, async () => ({ status: 429 })), 'rejected');
  assert.equal(await deliveryMail(value, e, async () => ({ status: 500 })), 'uncertain');
  assert.equal(await deliveryMail(value, e, async () => { throw Error('secret'); }), 'uncertain');
});
test('checkout recovery email is one opt-in reminder with tracking disabled', async () => {
  let count = 0; let sent;
  const request = async (url, options) => { count++; sent = JSON.parse(options.body); return { status: 202 }; };
  const mailEnv = { SENDGRID_API_KEY: 'fixture', LAUNCH_FROM_EMAIL: 'sender@example.invalid',
    COMMERCE_SANDBOX_EMAIL: 'buyer@example.invalid' };
  const value = { to: 'other@example.invalid', link: 'https://buy.stripe.com/r/test_fixture', release, live: false };
  assert.equal(await recoveryMail(value, mailEnv, request), 'rejected'); assert.equal(count, 0);
  assert.equal(await recoveryMail({ ...value, to: mailEnv.COMMERCE_SANDBOX_EMAIL }, mailEnv, request), 'accepted');
  assert.equal(sent.personalizations.length, 1);
  assert.match(sent.content[0].value, /one checkout reminder because you opted in/i);
  assert.match(sent.content[0].value, /not being added to a marketing list/i);
  assert.equal(sent.tracking_settings.click_tracking.enable, false);
  assert.equal(sent.tracking_settings.open_tracking.enable, false);
  assert.equal(await recoveryMail({ ...value, live: true }, mailEnv, request), 'accepted');
  assert.equal(sent.personalizations.length, 1);
});
test('operator-buyer address is included once so SendGrid accepts the atomic message', async () => {
  let sent;
  const value = { to: 'joshua@segeren.com', link: 'https://example.invalid/private', release,
    live: true, sessionId: 'cs_live_fixture', paymentIntent: 'pi_fixture', amountTotal: 5000 };
  assert.equal(await deliveryMail(value, { SENDGRID_API_KEY: 'fixture', LAUNCH_FROM_EMAIL: 'sender@example.invalid' },
    async (url, options) => { sent = JSON.parse(options.body); return { status: 202 }; }), 'accepted');
  assert.deepEqual(sent.personalizations.map(item => item.to[0].email),
    ['joshua@segeren.com', 'segerej@gmail.com']);
});
