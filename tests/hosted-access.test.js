const test = require('node:test');
const assert = require('node:assert/strict');
const { mintSessionSecret, authorizeUploadScope, isAuthorizedScope } =
  require('../hosted/access');
const { publishStagedReceipt } = require('../hosted/publication');

const accountId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const vaultId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const otherVaultId = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const catalog = new Map([['price_fixture', { priceCents: 1000,
  allowanceBytes: 100_000_000_000 }]]);
const enrollment = { accountId, subscriptionId: 'sub_fixture',
  customerId: 'cus_fixture', priceId: 'price_fixture' };
const subscription = { id: 'sub_fixture', customer: 'cus_fixture',
  livemode: false, status: 'active', collection_method: 'charge_automatically',
  pause_collection: null, items: { data: [{ quantity: 1, price: {
    id: 'price_fixture', livemode: false, type: 'recurring', currency: 'usd',
    unit_amount: 1000, billing_scheme: 'per_unit',
    recurring: { interval: 'month', interval_count: 1 },
  } }] } };

function request(overrides = {}) {
  const session = mintSessionSecret();
  return { sessionToken: session.token, vaultId,
    query: async (_sql, values) => {
      assert.match(_sql, /revoked_at IS NULL/);
      assert.match(_sql, /expires_at > clock_timestamp\(\)/);
      assert.equal(values[0], session.tokenHash);
      assert.equal(values[1], vaultId);
      return { rows: [{ account_id: accountId, vault_id: vaultId }] };
    },
    getEntitlement: async id => {
      assert.equal(id, accountId);
      return { subscription, enrollment };
    },
    live: false, priceCatalog: catalog, ...overrides };
}

test('mints unpredictable token but persists only a digest and grants an owned Vault', async () => {
  const first = mintSessionSecret();
  const second = mintSessionSecret();
  assert.match(first.token, /^hv1_[A-Za-z0-9_-]{43}$/);
  assert.match(first.tokenHash, /^[0-9a-f]{64}$/);
  assert.notEqual(first.token, second.token);
  assert.notEqual(first.tokenHash, second.tokenHash);
  assert.equal(first.tokenHash.includes(first.token), false);
  const scope = await authorizeUploadScope(request());
  assert.deepEqual(scope, { accountId, vaultId });
  assert.equal(Object.isFrozen(scope), true);
  assert.equal(isAuthorizedScope(scope), true);
  assert.equal(isAuthorizedScope({ accountId, vaultId }), false);
});

test('missing, foreign, revoked, and expired sessions cannot mint an upload scope', async () => {
  for (const row of [undefined, { account_id: accountId, vault_id: otherVaultId },
    { account_id: 'foreign', vault_id: vaultId }]) {
    await assert.rejects(authorizeUploadScope(request({
      query: async () => ({ rows: row ? [row] : [] }),
    })), /hosted_access_denied/);
  }
  for (const invalid of ['', 'download-link', 'hv1_../other']) {
    await assert.rejects(authorizeUploadScope(request({ sessionToken: invalid })),
      /hosted_access_denied/);
  }
  // The SQL predicate excludes revoked and expired rows even when the caller
  // still possesses an otherwise well-formed secret.
  await assert.rejects(authorizeUploadScope(request({
    query: async () => ({ rows: [] }),
  })), /hosted_access_denied/);
});

test('subscription, enrollment, and lookup failures reveal no private details', async () => {
  const cases = [
    { getEntitlement: async () => ({ subscription: { ...subscription, status: 'past_due' }, enrollment }) },
    { getEntitlement: async () => ({ subscription, enrollment: { ...enrollment, accountId: otherVaultId } }) },
    { getEntitlement: async () => { throw Error('Stripe secret'); } },
    { query: async () => { throw Error('database secret'); } },
    { live: true },
  ];
  for (const changes of cases) {
    await assert.rejects(authorizeUploadScope(request(changes)), error =>
      error.message === 'hosted_access_denied');
  }
});

test('plain client-shaped scope cannot publish before provider or database access', async () => {
  let calls = 0;
  await assert.rejects(publishStagedReceipt({
    scope: { accountId, vaultId }, reservationId: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
    receipt: {}, maxReceiptBytes: 1000,
    verifyBatch: async () => { calls++; return true; },
    query: async () => { calls++; return { rows: [{ published: true }] }; },
  }), /hosted_publication_failed/);
  assert.equal(calls, 0);
});
