const test = require('node:test');
const assert = require('node:assert/strict');
const { randomBytes } = require('node:crypto');
const { uploadConfiguration, uploadRuntime } = require('../hosted/upload_runtime');
const { accountId } = require('./hosted-subscriber-fixture');

const env = { HOSTED_MODE: 'sandbox', HOSTED_SANDBOX_UPLOAD_OPEN: 'yes',
  COMMERCE_MODE: 'sandbox',
  COMMERCE_DATABASE_URL: 'postgresql://fixture:fixture@ep-square-queen-av5us6bx.c-11.us-east-1.aws.neon.tech/neondb?sslmode=require',
  HOSTED_R2_ORIGIN: 'https://r2.fixture.test',
  HOSTED_CAPABILITY_SIGNING_KEY: randomBytes(32).toString('base64url'),
  HOSTED_SANDBOX_PRICE_ID: 'price_fixture',
  HOSTED_SANDBOX_PRICE_CENTS: '1000',
  HOSTED_SANDBOX_ALLOWANCE_BYTES: '100000000' };

test('sandbox upload configuration is pinned and has a bounded server-only catalog', () => {
  const config = uploadConfiguration(env);
  assert.equal(config.workerOrigin, 'https://r2.fixture.test');
  assert.deepEqual(config.priceCatalog.get('price_fixture'), {
    priceCents: 1000, allowanceBytes: 100_000_000 });
  for (const change of [
    { HOSTED_MODE: 'live' }, { COMMERCE_MODE: 'live' },
    { HOSTED_SANDBOX_UPLOAD_OPEN: 'no' },
    { HOSTED_SANDBOX_PRICE_CENTS: '999' },
    { HOSTED_SANDBOX_ALLOWANCE_BYTES: '1000000000001' },
    { COMMERCE_DATABASE_URL: env.COMMERCE_DATABASE_URL.replace(
      'ep-square-queen', 'ep-other') },
    { HOSTED_R2_ORIGIN: 'http://r2.fixture.test' },
    { HOSTED_CAPABILITY_SIGNING_KEY: 'not-a-key' },
  ]) {
    assert.throws(() => uploadConfiguration({ ...env, ...change }),
      /hosted_upload_unavailable/);
  }
});

test('enrollment is database-bound and Stripe subscription is read fresh', async () => {
  let reads = 0;
  const subscription = { id: 'sub_fixture', status: 'active' };
  const runtime = await uploadRuntime(env, {
    openDatabase: async received => {
      assert.equal(received, env);
      return async (sql, params) => {
        assert.match(sql, /FROM hosted\.subscription_enrollments/);
        assert.deepEqual(params, [accountId]);
        reads++;
        return { rows: [{ account_id: accountId, mode: 'sandbox',
          subscription_id: 'sub_fixture', customer_id: 'cus_fixture',
          price_id: 'price_fixture' }] };
      };
    },
    openCommerce: async received => {
      assert.equal(received, env);
      return { config: { mode: 'sandbox', live: false },
        stripe: { subscriptions: { retrieve: async (id, options) => {
          assert.equal(id, 'sub_fixture');
          assert.deepEqual(options, { expand: ['items.data.price'] });
          return subscription;
        } } },
        service: { verifyForHostedAuthorization: async () => true } };
    },
  });
  assert.equal(runtime.live, false);
  assert.equal(runtime.priceCatalog.get('price_fixture').allowanceBytes, 100_000_000);
  const evidence = await runtime.getEntitlement(accountId);
  assert.equal(evidence.subscription, subscription);
  assert.deepEqual(evidence.enrollment, { accountId,
    subscriptionId: 'sub_fixture', customerId: 'cus_fixture',
    priceId: 'price_fixture' });
  assert.equal(reads, 1);
  await assert.rejects(runtime.getEntitlement('not-an-id'),
    /hosted_upload_unavailable/);
  assert.equal(reads, 1);
});

test('absent or cross-environment enrollment cannot become entitlement', async () => {
  const runtime = await uploadRuntime(env, {
    openDatabase: async () => async () => ({ rows: [] }),
    openCommerce: async () => ({ config: { mode: 'sandbox', live: false },
      stripe: { subscriptions: { retrieve: async () => {
        throw Error('must not call Stripe');
      } } }, service: { verifyForHostedAuthorization: async () => true } }),
  });
  await assert.rejects(runtime.getEntitlement(accountId),
    /hosted_upload_unavailable/);
  await assert.rejects(uploadRuntime(env, {
    openDatabase: async () => async () => ({ rows: [] }),
    openCommerce: async () => ({ config: { mode: 'live', live: true } }),
  }), /hosted_upload_unavailable/);
  let providerReads = 0;
  const malformed = await uploadRuntime(env, {
    openDatabase: async () => async () => ({ rows: [{ account_id: accountId,
      mode: 'sandbox', subscription_id: 'sub_fixture',
      customer_id: 'cus_fixture', price_id: 'price_other' }] }),
    openCommerce: async () => ({ config: { mode: 'sandbox', live: false },
      stripe: { subscriptions: { retrieve: async () => { providerReads++; } } },
      service: { verifyForHostedAuthorization: async () => true } }),
  });
  await assert.rejects(malformed.getEntitlement(accountId),
    /hosted_upload_unavailable/);
  assert.equal(providerReads, 0);
});
