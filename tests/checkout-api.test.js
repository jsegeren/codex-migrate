const test = require('node:test');
const assert = require('node:assert/strict');
const { makeHandler } = require('../api/checkout');
const { SITE } = require('../commerce/config');

const requestId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const operator = 'a'.repeat(64); // Synthetic test token, not a credential.
function fixture(live = false) {
  const config = { live, mode: live ? 'live' : 'sandbox', account: 'acct_fixture',
    product: 'prod_fixture', price: 'price_fixture', release: { id: 'release-1' }, site: SITE };
  const env = { COMMERCE_CHECKOUT_OPEN: 'yes', COMMERCE_SANDBOX_OPERATOR_TOKEN: operator };
  const price = { livemode: live, active: true, unit_amount: 5000, currency: 'usd',
    type: 'one_time', billing_scheme: 'per_unit', recurring: null, transform_quantity: null,
    product: { id: config.product, active: true, livemode: live } };
  const session = { livemode: live, managed_payments: { enabled: true }, url: 'https://checkout.stripe.com/c/pay/fixture' };
  const calls = []; let account = config.account;
  const stripe = { accounts: { retrieve: async () => { calls.push('account'); return { id: account }; } },
    prices: { retrieve: async () => { calls.push('price'); return price; } },
    checkout: { sessions: { create: async (data, options) => { calls.push({ data, options }); return session; } } } };
  const handler = makeHandler(async received => { assert.equal(received, env); calls.push('runtime'); return { stripe }; }, env, () => config);
  const request = { method: 'POST', headers: { origin: SITE, 'content-type': 'application/json',
    authorization: `Bearer ${operator}` }, body: { requestId } };
  const send = async () => {
    const res = { headers: {}, setHeader(k, v) { this.headers[k] = v; }, end(text) { this.body = JSON.parse(text); } };
    await handler(request, res); return res;
  };
  return { config, env, price, session, calls, request, send, setAccount: value => account = value };
}
for (const authorization of [undefined, '', `Bearer ${'b'.repeat(64)}`, `Bearer ${'é'.repeat(64)}`, ['Bearer fixture']]) {
  test('invalid sandbox authorization is rejected before runtime/database/provider access', async () => {
    const f = fixture(); f.request.headers.authorization = authorization;
    const res = await f.send(); assert.equal(res.statusCode, 403);
    assert.equal(res.body.error, 'sandbox_operator_required'); assert.deepEqual(f.calls, []);
  });
}
for (const id of [null, [requestId], {}, 123, 'invalid']) test('request ID must be a UUID string', async () => {
  const f = fixture(); f.request.body.requestId = id;
  assert.equal((await f.send()).statusCode, 400); assert.deepEqual(f.calls, []);
});
test('authorized sandbox creates one $50 Managed Payments session with retry identity', async () => {
  const f = fixture(); const first = await f.send(); const second = await f.send();
  assert.equal(first.statusCode, 200); assert.equal(second.statusCode, 200);
  const creates = f.calls.filter(c => typeof c === 'object'); assert.equal(creates.length, 2);
  assert.deepEqual(creates[0], creates[1]);
  assert.deepEqual(creates[0].data.line_items, [{ price: 'price_fixture', quantity: 1 }]);
  assert.equal(creates[0].data.managed_payments.enabled, true);
  assert.equal(creates[0].data.mode, 'payment');
  assert.equal(creates[0].options.idempotencyKey, `codex-migrate-sandbox-release-1-${requestId}`);
  assert.equal(creates[0].data.success_url, `${SITE}/purchase#session={CHECKOUT_SESSION_ID}`);
  assert.equal(first.headers['Cache-Control'], 'no-store');
});
test('configured live buyer does not need the sandbox operator token', async () => {
  const f = fixture(true); delete f.request.headers.authorization;
  assert.equal((await f.send()).statusCode, 200);
  assert.match(f.calls.find(c => typeof c === 'object').options.idempotencyKey, /-live-/);
});
test('wrong account stops before looking up or creating a purchase', async () => {
  const f = fixture(); f.setAccount('acct_other');
  assert.equal((await f.send()).body.error, 'account_mismatch');
  assert.deepEqual(f.calls, ['runtime', 'account']);
});
for (const mutate of [p => p.unit_amount = 4900, p => p.currency = 'cad', p => p.active = false,
  p => p.product.id = 'prod_other', p => p.product.active = false, p => p.livemode = true,
  p => p.recurring = { interval: 'month' }, p => p.transform_quantity = { divide_by: 2 }]) {
  test('unexpected catalog cannot create a checkout session', async () => {
    const f = fixture(); mutate(f.price);
    assert.equal((await f.send()).body.error, 'catalog_mismatch');
    assert.deepEqual(f.calls, ['runtime', 'account', 'price']);
  });
}
for (const mutate of [s => s.livemode = true, s => s.managed_payments.enabled = false,
  s => s.url = 'https://evil.example/checkout', s => s.url = 'https://user:pass@checkout.stripe.com/']) {
  test('unverified provider session never redirects the buyer', async () => {
    const f = fixture(); mutate(f.session); const res = await f.send();
    assert.equal(res.statusCode, 503); assert.equal(res.body.url, undefined);
  });
}
