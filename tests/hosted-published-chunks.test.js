const test = require('node:test');
const assert = require('node:assert/strict');
const { lookupPublishedChunks } = require('../hosted/published_chunks');
const { makeHandler } = require('../api/hosted-published-chunks');
const { mintSessionSecret } = require('./hosted-device-fixture');
const { accountId, vaultId, freshScope } = require('./hosted-subscriber-fixture');

const raw = 'a'.repeat(64);
const compressed = 'b'.repeat(64);
const missing = 'c'.repeat(64);
const digest = 'd'.repeat(64);

test('lookup returns only exact published objects of the scoped Vault', async () => {
  const objects = await lookupPublishedChunks({ scope: await freshScope(),
    ids: [raw, compressed, missing], query: async (sql, values) => {
      assert.match(sql, /hosted\.snapshot_objects/);
      assert.match(sql, /so\.account_id = o\.account_id/);
      assert.match(sql, /so\.vault_id = o\.vault_id/);
      assert.deepEqual(values, [accountId, vaultId, [raw, compressed, missing]]);
      return { rows: [{ id: raw, bytes: '101', sha256: digest },
        { id: compressed, bytes: '51', sha256: digest }] };
    } });
  assert.deepEqual(objects, [{ id: raw, bytes: 101, sha256: digest },
    { id: compressed, bytes: 51, sha256: digest }]);
  assert.equal(Object.isFrozen(objects), true);
});

test('invalid candidates, forged scope, and malformed database output fail closed', async () => {
  let queries = 0;
  const query = async () => { queries++; return { rows: [] }; };
  await assert.rejects(lookupPublishedChunks({ scope: { accountId, vaultId },
    ids: [raw], query }), /hosted_chunk_lookup_denied/);
  await assert.rejects(lookupPublishedChunks({ scope: await freshScope(),
    ids: [raw, raw], query }), /hosted_chunk_lookup_denied/);
  await assert.rejects(lookupPublishedChunks({ scope: await freshScope(),
    ids: [raw.toUpperCase()], query }), /hosted_chunk_lookup_denied/);
  assert.equal(queries, 0);
  for (const rows of [null, [{ id: missing, bytes: 1, sha256: digest }],
    [{ id: raw, bytes: 1, sha256: digest },
      { id: raw, bytes: 1, sha256: digest }],
    [{ id: raw, bytes: 0, sha256: digest }],
    [{ id: raw, bytes: 1, sha256: 'bad' }]]) {
    await assert.rejects(lookupPublishedChunks({ scope: await freshScope(),
      ids: [raw], query: async () => ({ rows }) }),
    /hosted_chunk_lookup_denied/);
  }
  const scope = await freshScope();
  await lookupPublishedChunks({ scope, ids: [raw], query });
  await assert.rejects(lookupPublishedChunks({ scope, ids: [raw], query }),
    /hosted_chunk_lookup_denied/);
});

function response() {
  return { headers: {}, setHeader(key, value) { this.headers[key] = value; },
    end(value) { this.body = JSON.parse(value); } };
}

function fixture() {
  const session = mintSessionSecret();
  const env = { HOSTED_MODE: 'sandbox', HOSTED_SANDBOX_UPLOAD_OPEN: 'yes' };
  let loads = 0;
  let lookups = 0;
  let entitlement = 'active';
  const handler = makeHandler(async received => {
    assert.equal(received, env);
    loads++;
    return { query: async (sql, values) => {
      if (sql.includes('FROM hosted.device_sessions AS sessions')) {
        assert.deepEqual(values, [session.tokenHash, vaultId]);
        return { rows: [{ account_id: accountId, vault_id: vaultId,
          purchase_session_id: 'cs_test_fixture', purchase_mode: 'sandbox' }] };
      }
      lookups++;
      assert.deepEqual(values, [accountId, vaultId, [raw, compressed]]);
      return { rows: [{ id: raw, bytes: '101', sha256: digest }] };
    }, verifyPurchase: async () => ({ sessionId: 'cs_test_fixture',
      mode: 'sandbox' }), getEntitlement: async id => ({
      enrollment: { accountId: id, subscriptionId: 'sub_fixture',
        customerId: 'cus_fixture', priceId: 'price_fixture' },
      subscription: { id: 'sub_fixture', customer: 'cus_fixture',
        livemode: false, status: entitlement,
        collection_method: 'charge_automatically', pause_collection: null,
        items: { data: [{ quantity: 1, price: { id: 'price_fixture',
          livemode: false, type: 'recurring', currency: 'usd',
          unit_amount: 1000, billing_scheme: 'per_unit',
          recurring: { interval: 'month', interval_count: 1 } } }] } },
    }), live: false, priceCatalog: new Map([['price_fixture', {
      priceCents: 1000, allowanceBytes: 100_000_000 }]]) };
  }, env);
  const req = { method: 'POST', headers: {
    authorization: `Bearer ${session.token}`,
    'content-type': 'application/json',
  }, body: { vaultId, ids: [raw, compressed] } };
  return { env, req, loads: () => loads, lookups: () => lookups,
    setEntitlement: value => { entitlement = value; },
    send: async () => { const res = response(); await handler(req, res); return res; } };
}

test('dark lookup opens only for a currently paid, purchased device', async () => {
  const f = fixture();
  f.env.HOSTED_SANDBOX_UPLOAD_OPEN = 'no';
  assert.equal((await f.send()).statusCode, 404);
  f.env.HOSTED_SANDBOX_UPLOAD_OPEN = 'yes';
  f.req.body.ids = [raw, raw];
  assert.equal((await f.send()).statusCode, 400);
  f.req.body.ids = [raw, compressed];
  f.req.headers.origin = 'https://attacker.example';
  assert.equal((await f.send()).statusCode, 400);
  delete f.req.headers.origin;
  f.req.headers.authorization = 'Bearer forged';
  assert.equal((await f.send()).statusCode, 403);
  assert.equal(f.loads(), 0);
  f.req.headers.authorization = `Bearer ${mintSessionSecret().token}`;
  assert.equal((await f.send()).statusCode, 403);
  assert.equal(f.lookups(), 0);
});

test('lookup includes no bytes or grants and denies a lapsed subscription', async () => {
  const f = fixture();
  const result = await f.send();
  assert.equal(result.statusCode, 200);
  assert.deepEqual(result.body, { objects: [{ id: raw, bytes: 101,
    sha256: digest }] });
  assert.equal(result.headers['Cache-Control'], 'no-store');
  f.setEntitlement('past_due');
  assert.equal((await f.send()).statusCode, 403);
  assert.equal(f.lookups(), 1);
});
