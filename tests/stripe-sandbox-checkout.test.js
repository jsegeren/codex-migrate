const test = require('node:test');
const assert = require('node:assert/strict');
const { prepare } = require('../ops/stripe-sandbox-checkout');

const env = {
  CODEX_MIGRATE_STRIPE_TEST_KEY: 'rk_test_fixture',
  CODEX_MIGRATE_STRIPE_TEST_ACCOUNT: 'acct_fixture',
  CODEX_MIGRATE_STRIPE_TEST_PRODUCT: 'prod_fixture',
  CODEX_MIGRATE_STRIPE_TEST_PRICE: 'price_fixture',
};
function fixture() {
  const calls = [];
  const replies = [{ id: 'acct_fixture' }, {
    id: 'price_fixture', active: true, livemode: false, type: 'one_time',
    recurring: null, currency: 'usd', unit_amount: 5000, billing_scheme: 'per_unit',
    product: { id: 'prod_fixture', name: 'Codex Migrate — Founding Edition (TEST ONLY)',
      active: true, livemode: false, tax_code: 'txcd_10202000' },
  }, {
    id: 'cs_test_fixture', livemode: false, status: 'open', mode: 'payment',
    managed_payments: { enabled: true }, url: 'https://checkout.stripe.com/c/pay/cs_test_fixture',
  }];
  const request = async (url, options) => {
    calls.push({ url, ...options });
    return { ok: true, json: async () => replies[calls.length - 1] };
  };
  return { calls, replies, request };
}

test('default only reads the expected sandbox account and catalog', async () => {
  const f = fixture();
  assert.deepEqual(await prepare({ env, request: f.request }),
    { status: 'sandbox_catalog_verified', checkoutCreated: false });
  assert.equal(f.calls.length, 2);
  assert.ok(f.calls.every(call => call.method === 'GET' && call.redirect === 'error'));
});
test('explicit create uses only this price and per-session Managed Payments', async () => {
  const f = fixture();
  const result = await prepare({ env, request: f.request, create: true });
  assert.equal(result.session, 'cs_test_fixture');
  assert.equal(f.calls.length, 3);
  const call = f.calls[2];
  assert.equal(call.url, 'https://api.stripe.com/v1/checkout/sessions');
  const body = new URLSearchParams(call.body);
  assert.equal(body.get('managed_payments[enabled]'), 'true');
  assert.equal(body.get('line_items[0][price]'), 'price_fixture');
  assert.equal(body.get('line_items[0][quantity]'), '1');
  assert.equal(body.get('mode'), 'payment');
  // Stripe rejects custom_text for Managed Payments; disclosure is on the
  // explicitly TEST ONLY product instead.
  assert.ok([...body.keys()].every(key => !key.startsWith('custom_text')));
  assert.ok(call.headers['Idempotency-Key'].startsWith('codex-migrate-sandbox-'));
  assert.equal(body.has('customer_email'), false);
  assert.equal(JSON.stringify(result).includes('https://'), false);
});
test('missing configuration and live credentials fail before any network', async () => {
  for (const config of [{}, { ...env, CODEX_MIGRATE_STRIPE_TEST_KEY: 'sk_live_fixture' },
    { ...env, CODEX_MIGRATE_STRIPE_TEST_PRICE: 'price_fixture/../customers' }]) {
    const f = fixture();
    await assert.rejects(prepare({ env: config, request: f.request, create: true }), /sandbox variables/);
    assert.equal(f.calls.length, 0);
  }
});
test('another Stripe account fails before reading its products', async () => {
  const f = fixture(); f.replies[0].id = 'acct_unrelated';
  await assert.rejects(prepare({ env, request: f.request, create: true }), /account mismatch/);
  assert.equal(f.calls.length, 1);
});
for (const [label, mutate] of [
  ['unrelated price', p => p.id = 'price_unrelated'],
  ['live price', p => p.livemode = true],
  ['archived price', p => p.active = false],
  ['recurring price', p => p.recurring = { interval: 'month' }],
  ['different currency', p => p.currency = 'cad'],
  ['different amount', p => p.unit_amount = 4900],
  ['tiered price', p => p.billing_scheme = 'tiered'],
  ['transformed quantity', p => p.transform_quantity = { divide_by: 2 }],
  ['unrelated product', p => p.product.id = 'prod_youone'],
  ['live product', p => p.product.livemode = true],
  ['archived product', p => p.product.active = false],
  ['non-test product', p => p.product.name = 'Codex Migrate'],
  ['unexpanded product', p => p.product = 'prod_fixture'],
  ['missing tax category', p => p.product.tax_code = null],
]) {
  test(`${label} stops before checkout creation`, async () => {
    const f = fixture(); mutate(f.replies[1]);
    await assert.rejects(prepare({ env, request: f.request, create: true }), /exact active/);
    assert.equal(f.calls.length, 2);
  });
}
test('network failures never leak provider details or retry', async () => {
  let count = 0;
  await assert.rejects(prepare({ env, request: async () => {
    count++; throw new Error('secret provider content');
  } }), error => !error.message.includes('secret') && /not confirmed/.test(error.message));
  assert.equal(count, 1);
});
test('a rejected managed checkout never falls back to ordinary Checkout', async () => {
  const f = fixture();
  const request = async (...args) => {
    const result = await f.request(...args);
    return f.calls.length === 3 ? { ok: false } : result;
  };
  await assert.rejects(prepare({ env, request, create: true }), /declined/);
  assert.equal(f.calls.length, 3);
});
for (const [label, mutate] of [
  ['live session', s => s.livemode = true],
  ['unmanaged session', s => s.managed_payments.enabled = false],
  ['completed session', s => s.status = 'complete'],
  ['untrusted checkout URL', s => s.url = 'https://example.com/pay'],
  ['missing checkout URL', s => s.url = null],
]) {
  test(`${label} is not reported as a verified checkout`, async () => {
    const f = fixture(); mutate(f.replies[2]);
    await assert.rejects(prepare({ env, request: f.request, create: true }), /could not be verified/);
    assert.equal(f.calls.length, 3);
  });
}
