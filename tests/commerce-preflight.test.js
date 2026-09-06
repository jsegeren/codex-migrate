const test = require('node:test');
const assert = require('node:assert/strict');
const { preflight, main, verifyFixture, EXPECTED } = require('../ops/commerce-preflight');
const env = { COMMERCE_PREFLIGHT: 'yes', VERCEL_ENV: 'production', COMMERCE_MODE: 'live',
  COMMERCE_CHECKOUT_OPEN: 'no', COMMERCE_STRIPE_ACCOUNT: EXPECTED.account,
  COMMERCE_PRODUCT: EXPECTED.product, COMMERCE_PRICE: EXPECTED.price,
  COMMERCE_BLOB_STORE_ID: EXPECTED.store, COMMERCE_STRIPE_KEY: 'rk_live_fixture',
  COMMERCE_LINK_SECRET: 'a'.repeat(64), COMMERCE_WEBHOOK_SECRET: 'whsec_fixture',
  COMMERCE_DATABASE_URL: `postgresql://fixture:fixture@${EXPECTED.database}/neondb?sslmode=require` };
function factory() {
  return { account: async () => ({ id: EXPECTED.account }),
    product: async () => ({ id: EXPECTED.product, active: true, livemode: true }),
    price: async () => ({ id: EXPECTED.price, product: EXPECTED.product, active: true,
      livemode: true, unit_amount: 5000, currency: 'usd', type: 'one_time', recurring: null }),
    database: async () => [{ name: 'codex-migrate-commerce', mode: 'live' }],
    signFixture: async () => { throw Error('fixture transport not supplied'); } };
}
test('ordinary builds are offline and do not need commerce secrets', async () => {
  assert.deepEqual(await preflight({}, () => { throw Error('must not load'); }), { skipped: true });
});
for (const [name, value] of Object.entries({ VERCEL_ENV: 'preview', COMMERCE_MODE: 'sandbox',
  COMMERCE_CHECKOUT_OPEN: 'yes', COMMERCE_STRIPE_ACCOUNT: 'acct_other', COMMERCE_PRODUCT: 'prod_other',
  COMMERCE_PRICE: 'price_other', COMMERCE_BLOB_STORE_ID: 'other', COMMERCE_STRIPE_KEY: 'rk_test_fixture',
  COMMERCE_LINK_SECRET: 'bad', COMMERCE_WEBHOOK_SECRET: '',
  COMMERCE_DATABASE_URL: 'postgresql://fixture:fixture@other.neon.tech/neondb?sslmode=require' })) {
  test(`wrong ${name} stops before any provider call`, async () => {
    let calls = 0;
    await assert.rejects(preflight({ ...env, [name]: value }, () => { calls++; return factory(); }));
    assert.equal(calls, 0);
  });
}
for (const [stage, result] of [['account', { id: 'acct_other' }],
  ['product', { id: EXPECTED.product, active: false, livemode: true }],
  ['price', { id: EXPECTED.price, product: EXPECTED.product, active: true, livemode: true,
    unit_amount: 4900, currency: 'usd', type: 'one_time' }],
  ['database', [{ name: 'codex-migrate-commerce', mode: 'sandbox' }]]]) {
  test(`${stage} mismatch never signs a fixture`, async () => {
    let signed = 0; const deps = factory(); deps[stage] = async () => result;
    deps.signFixture = async () => { signed++; throw Error(); };
    await assert.rejects(preflight(env, () => deps)); assert.equal(signed, 0);
  });
}
test('provider failure details and credentials never enter the report', async () => {
  const output = []; const deps = factory();
  deps.account = async () => { throw Error('rk_live_PRIVATE https://private.example/?secret=value'); };
  assert.equal(await main(env, () => deps, x => output.push(x)), 1);
  assert.deepEqual(output.map(JSON.parse), [{ configured: false, code: 'commerce_preflight_failed', stage: 'stripe-account' }]);
});
test('oversized fixture response fails without accepting a download', async () => {
  const deps = factory(); deps.signFixture = async () => ({ url: 'https://fixture.invalid/private?secret=value' });
  deps.request = async () => new Response(Buffer.alloc(452));
  await assert.rejects(preflight(env, () => deps));
});
test('fixture transport verifies bytes and checks anonymous denial', async () => {
  const bytes = Buffer.from('harmless fixture');
  const artifact = { size: bytes.length, sha256: require('node:crypto').createHash('sha256').update(bytes).digest('hex') };
  const requests = [];
  const deps = { signFixture: async () => ({ url: 'https://fixture.invalid/file.zip?private=yes' }),
    request: async url => { requests.push(url); return url.includes('?') ? new Response(bytes) : new Response(null, { status: 403 }); } };
  assert.equal(await verifyFixture(deps, artifact), bytes.length);
  assert.deepEqual(requests, ['https://fixture.invalid/file.zip?private=yes', 'https://fixture.invalid/file.zip']);
  await assert.rejects(verifyFixture(deps, { ...artifact, sha256: '0'.repeat(64) }));
  deps.request = async () => new Response(bytes);
  await assert.rejects(verifyFixture(deps, artifact));
});
