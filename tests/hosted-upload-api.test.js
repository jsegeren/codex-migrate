const test = require('node:test');
const assert = require('node:assert/strict');
const { randomBytes } = require('node:crypto');
const { makeHandler } = require('../api/hosted-upload');
const { verifyObjectCapability } = require('../hosted/object_capability');
const { mintSessionSecret } = require('./hosted-device-fixture');
const { accountId, vaultId } = require('./hosted-subscriber-fixture');

const reservationId = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
const item = { key: 'objects/aa/' + 'a'.repeat(62) + '.cvchunk', bytes: 10,
  sha256: 'b'.repeat(64) };
const secret = randomBytes(32);

function response() {
  return { headers: {}, setHeader(key, value) { this.headers[key] = value; },
    end(value) { this.body = JSON.parse(value); } };
}

function fixture() {
  const session = mintSessionSecret();
  const env = { HOSTED_MODE: 'sandbox', HOSTED_SANDBOX_UPLOAD_OPEN: 'yes' };
  const catalog = new Map([['price_fixture', { priceCents: 1000,
    allowanceBytes: 100_000_000 }]]);
  let loads = 0;
  let writes = 0;
  let reads = 0;
  let decision = 'put';
  let entitlement = 'active';
  let reservationState = 'cleanup_pending';
  const handler = makeHandler(async received => {
    assert.equal(received, env);
    loads++;
    return { query: async (sql, values) => {
      if (sql.includes('FROM hosted.device_sessions AS sessions')) {
        assert.deepEqual(values, [session.tokenHash, vaultId]);
        return { rows: [{ account_id: accountId, vault_id: vaultId,
          purchase_session_id: 'cs_test_fixture', purchase_mode: 'sandbox' }] };
      }
      if (sql.includes('FROM hosted.device_sessions\n')) {
        assert.deepEqual(values, [session.tokenHash, vaultId]);
        return { rows: [{ account_id: accountId, vault_id: vaultId }] };
      }
      if (sql.includes('FROM hosted.upload_reservations')) {
        assert.deepEqual(values, [accountId, vaultId, reservationId]);
        reads++;
        return { rows: [{ state: reservationState }] };
      }
      writes++;
      if (sql.includes('abandon_upload_reservation')) {
        assert.deepEqual(values, [accountId, vaultId, reservationId]);
        return { rows: [{ allowed: true }] };
      }
      if (sql.includes('reserve_upload_with_base_current')) {
        assert.equal(values[3], 20);
        return { rows: [{ allowed: true, base_snapshot_id: null }] };
      }
      if (sql.includes('renew_upload_reservation_current')) {
        assert.equal(values[2], reservationId);
        return { rows: [{ allowed: true }] };
      }
      if (sql.includes('classify_upload_object_current')) {
        assert.equal(values[3], `accounts/${accountId}/vaults/${vaultId}/${item.key}`);
        return { rows: [{ decision }] };
      }
      if (sql.includes('reserve_object_grant_elastic_current')) {
        decision = 'head';
        return { rows: [{ allowed: true }] };
      }
      throw Error('unexpected SQL');
    }, workerOrigin: 'https://r2.fixture.test', secret,
    verifyPurchase: async () => ({ sessionId: 'cs_test_fixture', mode: 'sandbox' }),
    getEntitlement: async id => {
      assert.equal(id, accountId);
      return { enrollment: { accountId, subscriptionId: 'sub_fixture',
        customerId: 'cus_fixture', priceId: 'price_fixture' },
      subscription: { id: 'sub_fixture', customer: 'cus_fixture',
        livemode: false, status: entitlement,
        collection_method: 'charge_automatically', pause_collection: null,
        items: { data: [{ quantity: 1, price: { id: 'price_fixture',
          livemode: false, type: 'recurring', currency: 'usd',
          unit_amount: 1000, billing_scheme: 'per_unit',
          recurring: { interval: 'month', interval_count: 1 } } }] } } };
    }, live: false, priceCatalog: catalog };
  }, env);
  const req = { method: 'POST', headers: {
    authorization: `Bearer ${session.token}`, 'content-type': 'application/json',
  }, body: { action: 'reserve', vaultId, bytes: 20 } };
  return { env, req, loads: () => loads, writes: () => writes,
    reads: () => reads,
    setEntitlement: value => { entitlement = value; },
    setReservationState: value => { reservationState = value; },
    send: async () => { const res = response(); await handler(req, res); return res; } };
}

test('closed, malformed, and unauthenticated requests open no runtime', async () => {
  const f = fixture();
  f.env.HOSTED_SANDBOX_UPLOAD_OPEN = 'no';
  assert.equal((await f.send()).statusCode, 404);
  f.env.HOSTED_SANDBOX_UPLOAD_OPEN = 'yes';
  f.env.HOSTED_MODE = 'live';
  assert.equal((await f.send()).statusCode, 404);
  f.env.HOSTED_MODE = 'sandbox';
  f.req.body.extra = true;
  assert.equal((await f.send()).statusCode, 400);
  delete f.req.body.extra;
  f.req.headers.origin = 'https://attacker.example';
  assert.equal((await f.send()).statusCode, 400);
  delete f.req.headers.origin;
  f.req.headers.authorization = 'Bearer forged';
  assert.equal((await f.send()).statusCode, 403);
  assert.equal(f.loads(), 0);
});

test('paid sandbox device can reserve, renew, decide and get exact PUT/HEAD grants', async () => {
  const f = fixture();
  const reserve = await f.send();
  assert.equal(reserve.statusCode, 200);
  assert.equal(reserve.body.reservationId.length, 36);
  assert.equal(reserve.body.baseSnapshotId, null);
  assert.equal(reserve.headers['Cache-Control'], 'no-store');
  f.req.body = { action: 'renew', vaultId, reservationId };
  assert.equal((await f.send()).statusCode, 200);
  f.req.body = { action: 'decide', vaultId, reservationId, item };
  assert.deepEqual((await f.send()).body, { action: 'put_required' });
  f.req.body = { action: 'put', vaultId, reservationId, item };
  const put = await f.send();
  assert.equal(put.statusCode, 200);
  assert.equal(put.body.workerOrigin, 'https://r2.fixture.test');
  const key = `accounts/${accountId}/vaults/${vaultId}/${item.key}`;
  assert.deepEqual(await verifyObjectCapability(put.body.grant,
    'PUT', key, secret), { key, bytes: item.bytes, sha256: item.sha256 });
  f.req.body = { action: 'decide', vaultId, reservationId, item };
  const head = await f.send();
  assert.equal(head.body.action, 'head');
  assert.deepEqual(await verifyObjectCapability(head.body.grant,
    'HEAD', key, secret), { key, bytes: item.bytes, sha256: item.sha256 });
  assert.equal(JSON.stringify(head.body).includes('hv1_'), false);
  assert.equal(f.writes(), 5);
});

test('lapsed subscription cannot reserve or grant any object', async () => {
  const f = fixture();
  f.setEntitlement('past_due');
  assert.equal((await f.send()).statusCode, 403);
  f.req.body = { action: 'put', vaultId, reservationId, item };
  assert.equal((await f.send()).statusCode, 403);
  assert.equal(f.writes(), 0);
});

test('owned device can quarantine pending upload even after subscription lapses', async () => {
  const f = fixture();
  f.setEntitlement('past_due');
  f.req.body = { action: 'abandon', vaultId, reservationId };
  const result = await f.send();
  assert.equal(result.statusCode, 200);
  assert.deepEqual(result.body, { cleanupPending: true });
  assert.equal(f.writes(), 1);
  f.req.body = { action: 'status', vaultId, reservationId };
  assert.deepEqual((await f.send()).body, { state: 'cleanup_pending' });
  f.setReservationState('released');
  assert.deepEqual((await f.send()).body, { state: 'released' });
  assert.equal(f.reads(), 2);
  assert.equal(f.writes(), 1);
  f.req.body.vaultId = 'ffffffff-ffff-4fff-8fff-ffffffffffff';
  assert.equal((await f.send()).statusCode, 403);
  assert.equal(f.writes(), 1);
});

test('invalid item, foreign Vault, or unavailable runtime reveal no internals', async () => {
  const f = fixture();
  f.req.body = { action: 'put', vaultId, reservationId,
    item: { ...item, key: '../escape' } };
  assert.equal((await f.send()).statusCode, 400);
  f.req.body = { action: 'put', vaultId:
    'ffffffff-ffff-4fff-8fff-ffffffffffff', reservationId, item };
  assert.equal((await f.send()).statusCode, 403);
  const broken = makeHandler(async () => {
    throw Error('private Stripe and database details');
  }, f.env);
  const res = response();
  await broken(f.req, res);
  assert.equal(res.statusCode, 503);
  assert.deepEqual(res.body, { error: 'temporarily_unavailable' });
});
