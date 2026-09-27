const test = require('node:test');
const assert = require('node:assert/strict');
const { randomBytes } = require('node:crypto');
const { authorizeUploadScope, isAuthorizedScope } = require('../hosted/access');
const { verifyObjectCapability } = require('../hosted/object_capability');
const { issuePutCapability } = require('../hosted/upload_grant');
const { mintSessionSecret } = require('./hosted-device-fixture');

const accountId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const vaultId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const reservationId = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const key = `accounts/${accountId}/vaults/${vaultId}/metadata/11111111-1111-4111-8111-111111111111.json`;
const item = Object.freeze({ key, bytes: 20, sha256: 'a'.repeat(64) });
const secret = randomBytes(32);

async function scope() {
  const session = mintSessionSecret();
  return authorizeUploadScope({
    sessionToken: session.token, vaultId,
    query: async () => ({ rows: [{ account_id: accountId, vault_id: vaultId,
      purchase_session_id: 'cs_test_fixture', purchase_mode: 'sandbox' }] }),
    verifyPurchase: async () => ({ sessionId: 'cs_test_fixture', mode: 'sandbox' }),
    getEntitlement: async () => ({
      enrollment: { accountId, subscriptionId: 'sub_fixture',
        customerId: 'cus_fixture', priceId: 'price_fixture' },
      subscription: { id: 'sub_fixture', customer: 'cus_fixture',
        livemode: false, status: 'active', collection_method: 'charge_automatically',
        pause_collection: null, items: { data: [{ quantity: 1, price: {
          id: 'price_fixture', livemode: false, type: 'recurring', currency: 'usd',
          unit_amount: 1000, billing_scheme: 'per_unit',
          recurring: { interval: 'month', interval_count: 1 },
        } }] } },
    }),
    live: false,
    priceCatalog: new Map([['price_fixture', { priceCents: 1000,
      allowanceBytes: 100_000_000 }]]),
  });
}

test('only a fresh owned scope and durable reservation can sign one exact PUT', async () => {
  const authorized = await scope();
  let queries = 0;
  const token = await issuePutCapability({ scope: authorized, reservationId,
    item, secret, query: async (sql, values) => {
      queries++;
      assert.match(sql, /reserve_object_grant_current/);
      assert.deepEqual(values, [accountId, vaultId, reservationId,
        key, 20, item.sha256, 100_000_000]);
      return { rows: [{ allowed: true }] };
    } });
  assert.equal(queries, 1);
  assert.deepEqual(await verifyObjectCapability(token, 'PUT', key, secret), item);
  await assert.rejects(verifyObjectCapability(token, 'PUT', key, secret,
    Date.now() + 30_000), /hosted_object_access_denied/);
  assert.equal(isAuthorizedScope(authorized), false);
  await assert.rejects(issuePutCapability({ scope: authorized, reservationId,
    item, secret, query: async () => { queries++; } }), /hosted_upload_grant_denied/);
  assert.equal(queries, 1);
});

test('foreign and client-shaped scopes fail before database or signing', async () => {
  let queries = 0;
  const query = async () => { queries++; return { rows: [{ allowed: true }] }; };
  const foreign = { ...item, key: key.replace(vaultId,
    'dddddddd-dddd-4ddd-8ddd-dddddddddddd') };
  await assert.rejects(issuePutCapability({ scope: await scope(), reservationId,
    item: foreign, secret, query }), /hosted_upload_grant_denied/);
  await assert.rejects(issuePutCapability({ scope: { accountId, vaultId,
    allowanceBytes: 100_000_000 }, reservationId, item, secret, query }),
  /hosted_upload_grant_denied/);
  assert.equal(queries, 0);
});

test('quota, reservation, and signing failures disclose no internals', async () => {
  for (const [query, signingSecret] of [
    [async () => ({ rows: [{ allowed: false }] }), secret],
    [async () => { throw Error('private database detail'); }, secret],
    [async () => ({ rows: [{ allowed: true }] }), Buffer.from('wrong key')],
  ]) {
    await assert.rejects(issuePutCapability({ scope: await scope(),
      reservationId, item, secret: signingSecret, query }), error =>
      error.message === 'hosted_upload_grant_denied');
  }
});
