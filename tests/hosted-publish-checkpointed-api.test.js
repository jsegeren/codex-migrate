const test = require('node:test');
const assert = require('node:assert/strict');
const { makeHandler } = require('../api/hosted-publish-checkpointed');
const { HostedPublicationStaleError } = require('../hosted/publication_conflict');
const { mintSessionSecret } = require('./hosted-device-fixture');
const { accountId, vaultId } = require('./hosted-subscriber-fixture');

const reservationId = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const snapshotId = '11111111-1111-4111-8111-111111111111';

function response() {
  return { headers: {}, setHeader(key, value) { this.headers[key] = value; },
    end(value) { this.body = JSON.parse(value); } };
}

function fixture(publishError = null) {
  const session = mintSessionSecret();
  const env = { HOSTED_MODE: 'sandbox', HOSTED_SANDBOX_UPLOAD_OPEN: 'yes',
    HOSTED_SANDBOX_CHECKPOINT_PUBLISH_OPEN: 'yes' };
  let loads = 0;
  let publishes = 0;
  let status = 'active';
  const handler = makeHandler(async () => {
    loads++;
    return { live: false, priceCatalog: new Map([['price_fixture', {
      priceCents: 1000, allowanceBytes: 100_000_000 }]]),
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
  }, env, async ({ scope, reservationId: reservation,
    snapshotId: snapshot }) => {
    publishes++;
    if (publishError) throw publishError;
    assert.equal(scope.accountId, accountId);
    assert.equal(reservation, reservationId);
    assert.equal(snapshot, snapshotId);
    return { snapshotId, verifiedObjectCount: 4 };
  });
  const req = { method: 'POST', headers: {
    authorization: `Bearer ${session.token}`,
    'content-type': 'application/json',
  }, body: { action: 'publish_checkpointed', vaultId, reservationId,
    snapshotId } };
  return { env, req, loads: () => loads, publishes: () => publishes,
    lapse: () => { status = 'past_due'; },
    send: async () => { const res = response(); await handler(req, res); return res; } };
}

test('checkpointed publication is dark and rejects malformed or unauthorized calls', async () => {
  const f = fixture();
  f.env.HOSTED_SANDBOX_CHECKPOINT_PUBLISH_OPEN = 'no';
  assert.equal((await f.send()).statusCode, 404);
  f.env.HOSTED_SANDBOX_CHECKPOINT_PUBLISH_OPEN = 'yes';
  f.req.body.receipt = { trusted: true };
  assert.equal((await f.send()).statusCode, 400);
  delete f.req.body.receipt;
  f.req.headers.authorization = 'Bearer forged';
  assert.equal((await f.send()).statusCode, 403);
  assert.equal(f.loads(), 0);
});

test('only a fresh paid device can request last-good publication', async () => {
  const f = fixture();
  const result = await f.send();
  assert.equal(result.statusCode, 200);
  assert.deepEqual(result.body, { snapshotId, verifiedObjectCount: 4 });
  assert.equal(result.headers['Cache-Control'], 'no-store');
  assert.equal(f.publishes(), 1);
  f.lapse();
  assert.equal((await f.send()).statusCode, 403);
  assert.equal(f.publishes(), 1);
});

test('an authenticated stale reservation gets a bounded conflict, not an outage', async () => {
  const f = fixture(new HostedPublicationStaleError());
  const result = await f.send();
  assert.equal(result.statusCode, 409);
  assert.deepEqual(result.body, { error: 'stale_snapshot' });
  assert.equal(result.headers['Cache-Control'], 'no-store');
});
