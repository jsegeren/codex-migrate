const test = require('node:test');
const assert = require('node:assert/strict');
const { commerceSite, configuration, SITE } = require('../commerce/config');
const { body } = require('../commerce/http');
const { makeHandler: purchase } = require('../api/purchase');
const { makeHandler: checkout } = require('../api/checkout');

const host = 'codex-migrate-abc123-joshuas-projects-d3a5c48d.vercel.app';
const origin = `https://${host}`;
const env = { COMMERCE_MODE: 'sandbox', VERCEL_ENV: 'preview', VERCEL_URL: host };
const requestId = '12345678-1234-4234-8234-123456789abc';
function response() {
  return { headers: {}, setHeader(k, v) { this.headers[k] = v; }, end(v) { this.body = JSON.parse(v); } };
}
function request(value, from = origin) {
  return { method: 'POST', headers: { origin: from, 'content-type': 'application/json' }, body: value };
}
test('sandbox preview uses only the exact project deployment origin', () => {
  assert.equal(commerceSite(env), origin);
  assert.equal(commerceSite({ ...env, COMMERCE_MODE: 'live' }), SITE);
  assert.equal(commerceSite({ ...env, VERCEL_ENV: 'production' }), SITE);
  assert.equal(commerceSite({ COMMERCE_MODE: 'sandbox' }), SITE);
  for (const bad of [undefined, 'evil.example', `${host}.evil.example`, `${host}/`,
    `${host}:443`, `https://${host}`, `user@${host}`, 'other-app-abc.vercel.app']) {
    assert.throws(() => commerceSite({ ...env, VERCEL_URL: bad }), /sandbox_origin_unavailable/);
  }
});
test('reviewed sandbox configuration binds delivery links to its preview', () => {
  const release = { id: 'test', kind: 'sandbox-fixture', sha256: 'a'.repeat(64), source: 'b'.repeat(40),
    filename: 'fixture.zip', size: 10, pathname: `sandbox/${'a'.repeat(64)}/fixture.zip` };
  const config = configuration({ ...env, COMMERCE_STRIPE_KEY: 'rk_test_fixture',
    COMMERCE_LINK_SECRET: 'c'.repeat(64), COMMERCE_STRIPE_ACCOUNT: 'acct_fixture',
    COMMERCE_PRODUCT: 'prod_fixture', COMMERCE_PRICE: 'price_fixture', COMMERCE_RELEASE: 'test',
    COMMERCE_BLOB_STORE_ID: 'fixturestore', COMMERCE_WEBHOOK_SECRET: 'whsec_fixture' }, { test: release });
  assert.equal(config.site, origin);
});
test('origin matching is exact and does not accept forwarded host headers', () => {
  assert.deepEqual(body(request({}), origin), {});
  for (const from of [SITE, undefined, 'null', `${origin}/`, 'https://evil.example']) {
    const req = request({}, from); req.headers.origin = from;
    req.headers.host = host; req.headers['x-forwarded-host'] = host;
    assert.throws(() => body(req, origin), /invalid_origin/);
  }
});
test('preview checkout still requires operator authentication before runtime access', async () => {
  let calls = 0;
  const res = response();
  await checkout(() => { calls++; }, { ...env, COMMERCE_CHECKOUT_OPEN: 'yes' },
    () => ({ live: false })) (request({ requestId }), res);
  assert.equal(res.statusCode, 403);
  assert.equal(res.body.error, 'sandbox_operator_required');
  assert.equal(calls, 0);
});
test('authorized preview checkout sends return URLs to that preview, never production', async () => {
  const configured = { live: false, mode: 'sandbox', site: origin, account: 'acct_fixture',
    product: 'prod_fixture', price: 'price_fixture', release: { id: 'fixture' } };
  let created;
  const stripe = { accounts: { retrieve: async () => ({ id: configured.account }) },
    prices: { retrieve: async () => ({ livemode: false, active: true, unit_amount: 5000,
      currency: 'usd', type: 'one_time', billing_scheme: 'per_unit',
      product: { id: configured.product, livemode: false, active: true } }) },
    checkout: { sessions: { create: async value => { created = value;
      return { livemode: false, managed_payments: { enabled: true }, url: 'https://checkout.stripe.com/fixture' };
    } } } };
  const req = request({ requestId }); req.headers.authorization = `Bearer ${'c'.repeat(64)}`;
  const res = response();
  await checkout(async () => ({ stripe }), { ...env, COMMERCE_CHECKOUT_OPEN: 'yes',
    COMMERCE_SANDBOX_OPERATOR_TOKEN: 'c'.repeat(64) }, () => configured)(req, res);
  assert.equal(res.statusCode, 200);
  assert.equal(created.success_url, `${origin}/purchase#session={CHECKOUT_SESSION_ID}`);
  assert.equal(created.cancel_url, `${origin}/#founding-edition`);
});
test('preview purchase accepts its origin and uses the same server environment', async () => {
  let calls = 0;
  const handler = purchase(async actual => {
    assert.equal(actual, env); calls++;
    return { service: { status: async () => ({ paid: false }) } };
  }, actual => { assert.equal(actual, env); return { live: false }; }, env);
  let res = response();
  await handler(request({ action: 'status', credential: 'cs_test_fixture' }), res);
  assert.equal(res.statusCode, 200); assert.equal(calls, 1);
  res = response();
  await handler(request({ action: 'status', credential: 'cs_test_fixture' }, SITE), res);
  assert.equal(res.statusCode, 403); assert.equal(calls, 1);
});
