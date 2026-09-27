const test = require('node:test');
const assert = require('node:assert/strict');
const { makeHandler } = require('../api/hosted-verify-step');
const { mintSessionSecret } = require('./hosted-device-fixture');
const { accountId, vaultId } = require('./hosted-subscriber-fixture');

const reservationId = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const snapshotId = '11111111-1111-4111-8111-111111111111';

function response() {
  return { headers: {}, setHeader(key, value) { this.headers[key] = value; },
    end(value) { this.body = JSON.parse(value); } };
}

function fixture() {
  const session = mintSessionSecret();
  const env = { HOSTED_MODE: 'sandbox', HOSTED_SANDBOX_UPLOAD_OPEN: 'yes',
    HOSTED_SANDBOX_VERIFY_OPEN: 'yes' };
  let loads = 0;
  let checks = 0;
  let status = 'active';
  const handler = makeHandler(async () => {
    loads++;
    return { live: false, priceCatalog: new Map([['price_fixture', {
      priceCents: 1000, allowanceBytes: 100_000_000 }]]),
    workerOrigin: 'https://r2.example.test', secret: 'server-only-secret',
    query: async (sql, values) => {
      assert.match(sql, /FROM hosted.device_sessions AS sessions/);
      assert.deepEqual(values, [session.tokenHash, vaultId]);
      return { rows: [{ account_id: accountId, vault_id: vaultId,
        purchase_session_id: 'cs_test_fixture', purchase_mode: 'sandbox' }] };
    }, verifyPurchase: async () => ({ sessionId: 'cs_test_fixture',
      mode: 'sandbox' }), getEntitlement: async () => ({
      enrollment: { accountId, subscriptionId: 'sub_fixture',
        customerId: 'cus_fixture', priceId: 'price_fixture' },
      subscription: { id: 'sub_fixture', customer: 'cus_fixture',
        livemode: false, status, collection_method: 'charge_automatically',
        pause_collection: null, items: { data: [{ quantity: 1,
          price: { id: 'price_fixture', livemode: false, type: 'recurring',
            currency: 'usd', unit_amount: 1000, billing_scheme: 'per_unit',
            recurring: { interval: 'month', interval_count: 1 } } }] } },
    }) };
  }, env, ({ origin, secret }) => {
    assert.equal(origin, 'https://r2.example.test');
    assert.equal(secret, 'server-only-secret');
    return async () => true;
  }, async ({ scope, reservationId: reservation, snapshotId: snapshot }) => {
    checks++;
    assert.equal(scope.accountId, accountId);
    assert.equal(reservation, reservationId);
    assert.equal(snapshot, snapshotId);
    return { verifiedObjects: 128, ready: false };
  });
  const req = { method: 'POST', headers: {
    authorization: `Bearer ${session.token}`,
    'content-type': 'application/json',
  }, body: { action: 'verify_next', vaultId, reservationId, snapshotId } };
  return { env, req, loads: () => loads, checks: () => checks,
    lapse: () => { status = 'past_due'; },
    send: async () => { const res = response(); await handler(req, res); return res; } };
}

test('verification endpoint is dark and rejects malformed or unauthorized calls', async () => {
  const f = fixture();
  f.env.HOSTED_SANDBOX_VERIFY_OPEN = 'no';
  assert.equal((await f.send()).statusCode, 404);
  f.env.HOSTED_SANDBOX_VERIFY_OPEN = 'yes';
  f.req.body.proof = true;
  assert.equal((await f.send()).statusCode, 400);
  delete f.req.body.proof;
  f.req.headers.authorization = 'Bearer forged';
  assert.equal((await f.send()).statusCode, 403);
  assert.equal(f.loads(), 0);
});

test('fresh paid device receives bounded progress, never protected status', async () => {
  const f = fixture();
  const result = await f.send();
  assert.equal(result.statusCode, 200);
  assert.deepEqual(result.body, { verifiedObjects: 128, ready: false });
  assert.equal(result.headers['Cache-Control'], 'no-store');
  assert.equal(f.checks(), 1);
  f.lapse();
  assert.equal((await f.send()).statusCode, 403);
  assert.equal(f.checks(), 1);
});
