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
test('exact release proof refuses missing reviewed configuration before network access', async () => {
  let called = false;
  await assert.rejects(preflight({ ...env, COMMERCE_PROVE_RELEASE: 'yes' }, () => { called = true; return factory(); }));
  assert.equal(called, false);
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
test('standard Checkout proof expires its session before continuing other checks', async () => {
  const deps = factory(); let created = 0, expired = 0;
  deps.account = async () => ({ id: EXPECTED.account, charges_enabled: true });
  deps.createSession = async () => { created++; return { id: 'cs_live_proof', status: 'open',
    livemode: true, mode: 'payment', amount_subtotal: 5000, currency: 'usd' }; };
  deps.expireSession = async id => { expired++; assert.equal(id, 'cs_live_proof');
    return { id, status: 'expired', payment_status: 'unpaid' }; };
  const proof = { ...env, COMMERCE_CHECKOUT_PROVIDER: 'stripe', COMMERCE_PROVE_STANDARD_CHECKOUT: 'yes',
    COMMERCE_CHECKOUT_PROOF_ID: 'b'.repeat(32) };
  // Fixture transport is deliberately unavailable: session has already expired.
  await assert.rejects(preflight(proof, () => deps));
  assert.equal(created, 1); assert.equal(expired, 1);
  for (const changed of [{ COMMERCE_CHECKOUT_PROVIDER: 'managed' }, { COMMERCE_CHECKOUT_PROOF_ID: '' }]) {
    await assert.rejects(preflight({ ...proof, ...changed }, () => deps));
  }
  assert.equal(created, 1);
  await assert.rejects(preflight(env, () => deps));
  assert.equal(created, 1);
});
test('failed standard session creation is never retried and provider text is withheld', async () => {
  const deps = factory(); let calls = 0;
  deps.account = async () => ({ id: EXPECTED.account, charges_enabled: true });
  deps.createSession = async () => { calls++; throw Error('rk_live_PRIVATE'); };
  const output = [];
  const code = await main({ ...env, COMMERCE_CHECKOUT_PROVIDER: 'stripe', COMMERCE_PROVE_STANDARD_CHECKOUT: 'yes',
    COMMERCE_CHECKOUT_PROOF_ID: 'c'.repeat(32) }, () => deps, value => output.push(value));
  assert.equal(code, 1); assert.equal(calls, 1);
  assert.equal(JSON.parse(output[0]).stage, 'standard-checkout-create');
  assert(!output[0].includes('PRIVATE'));
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
