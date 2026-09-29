const test = require('node:test');
const assert = require('node:assert/strict');
const { randomBytes } = require('node:crypto');
const { makeHandler } = require('../api/hosted-upload');
const { verifyObjectCapability } = require('../hosted/object_capability');
const { mintUploadLease } = require('../hosted/upload_lease');
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
  const granted = new Set();
  let entitlement = 'active';
  let purchaseChecks = 0;
  let subscriptionChecks = 0;
  let reservationState = 'cleanup_pending';
  let leaseActive = true;
  let deviceActive = true;
  let denyGrantKey = null;
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
        return { rows: deviceActive ?
          [{ account_id: accountId, vault_id: vaultId }] : [] };
      }
      if (sql.includes('SELECT 1 AS active FROM hosted.upload_reservations')) {
        assert.deepEqual(values, [accountId, vaultId, reservationId]);
        return { rows: leaseActive ? [{ active: 1 }] : [] };
      }
      if (sql.includes('FROM hosted.upload_reservations')) {
        assert.deepEqual(values, [accountId, vaultId, reservationId]);
        reads++;
        return { rows: [{ state: reservationState,
          snapshot_id: reservationState === 'published' ?
            'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee' : null,
          verified_object_count: reservationState === 'published' ? 3 : null }] };
      }
      writes++;
      if (sql.includes('abandon_upload_reservation')) {
        assert.deepEqual(values, [accountId, vaultId, reservationId]);
        return { rows: [{ allowed: true }] };
      }
      if (sql.includes('reserve_upload_idempotent_current')) {
        assert.equal(values[3], 20);
        return { rows: [{ allowed: true, base_snapshot_id: null,
          expires_at: values[4] }] };
      }
      if (sql.includes('renew_upload_reservation_current')) {
        assert.equal(values[2], reservationId);
        return { rows: [{ allowed: true }] };
      }
      if (sql.includes('classify_upload_object_current')) {
        assert.ok(values[3].startsWith(`accounts/${accountId}/vaults/${vaultId}/`));
        return { rows: [{ decision: granted.has(values[3]) ? 'head' : 'put' }] };
      }
      if (sql.includes('reserve_object_grant_elastic_current')) {
        if (values[3] === denyGrantKey) return { rows: [{ allowed: false }] };
        granted.add(values[3]);
        return { rows: [{ allowed: true }] };
      }
      throw Error('unexpected SQL');
    }, workerOrigin: 'https://r2.fixture.test', secret,
    verifyPurchase: async () => {
      purchaseChecks++;
      return { sessionId: 'cs_test_fixture', mode: 'sandbox' };
    },
    getEntitlement: async id => {
      subscriptionChecks++;
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
  return { env, req, session, loads: () => loads, writes: () => writes,
    reads: () => reads, purchaseChecks: () => purchaseChecks,
    subscriptionChecks: () => subscriptionChecks,
    setEntitlement: value => { entitlement = value; },
    setLeaseActive: value => { leaseActive = value; },
    setDeviceActive: value => { deviceActive = value; },
    denyGrantFor: value => { denyGrantKey = value; },
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
  f.req.body = { action: 'lease', vaultId, reservationId };
  const lease = await f.send();
  assert.equal(lease.statusCode, 200);
  assert.deepEqual(Object.keys(lease.body), ['lease']);
  f.req.headers['x-hosted-upload-lease'] = lease.body.lease;
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
  assert.equal(f.purchaseChecks(), 3);
  assert.equal(f.subscriptionChecks(), 3);
});

test('pre-recorded reservation ID survives a repeated request', async () => {
  const f = fixture();
  f.req.body.reservationId = reservationId;
  const first = await f.send();
  const second = await f.send();
  assert.equal(first.statusCode, 200);
  assert.equal(second.statusCode, 200);
  assert.equal(first.body.reservationId, reservationId);
  assert.equal(second.body.reservationId, reservationId);
  f.req.body.reservationId = 'bad';
  assert.equal((await f.send()).statusCode, 400);
});

test('object lease refuses missing, tampered, cross-reservation and wrong-device use', async () => {
  const f = fixture();
  f.req.body = { action: 'lease', vaultId, reservationId };
  const issued = await f.send();
  assert.equal(issued.statusCode, 200);
  const lease = issued.body.lease;
  f.req.body = { action: 'decide', vaultId, reservationId, item };
  assert.equal((await f.send()).statusCode, 403);
  assert.equal(f.loads(), 1);
  f.req.headers['x-hosted-upload-lease'] = lease;
  f.req.body.reservationId = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee';
  assert.equal((await f.send()).statusCode, 403);
  f.req.body.reservationId = reservationId;
  f.req.headers['x-hosted-upload-lease'] = lease.slice(0, -1) +
    (lease.endsWith('A') ? 'B' : 'A');
  assert.equal((await f.send()).statusCode, 403);
  f.req.headers['x-hosted-upload-lease'] = lease;
  f.req.headers.authorization = 'Bearer hv1_' + 'a'.repeat(43);
  assert.equal((await f.send()).statusCode, 403);
  assert.equal(f.writes(), 0);
  assert.equal(f.purchaseChecks(), 1);
  assert.equal(f.subscriptionChecks(), 1);
});

test('lease cannot be issued for an inactive reservation', async () => {
  const f = fixture();
  f.setLeaseActive(false);
  f.req.body = { action: 'lease', vaultId, reservationId };
  assert.deepEqual((await f.send()).body, { error: 'access_denied' });
  assert.equal(f.writes(), 0);
});

test('expired lease and revoked device cannot authorize an object', async () => {
  const f = fixture();
  f.req.body = { action: 'decide', vaultId, reservationId, item };
  f.req.headers['x-hosted-upload-lease'] = mintUploadLease({
    accountId, vaultId, reservationId, deviceHash: f.session.tokenHash,
    allowanceBytes: 100_000_000, secret, now: Date.now() - 60_001,
  });
  assert.equal((await f.send()).statusCode, 403);
  f.req.body = { action: 'lease', vaultId, reservationId };
  const issued = await f.send();
  assert.equal(issued.statusCode, 200);
  f.setDeviceActive(false);
  f.req.body = { action: 'decide', vaultId, reservationId, item };
  f.req.headers['x-hosted-upload-lease'] = issued.body.lease;
  assert.equal((await f.send()).statusCode, 403);
  assert.equal(f.writes(), 0);
});

test('a bounded batch issues exact PUT and HEAD grants with one service call', async () => {
  const f = fixture();
  f.req.body = { action: 'lease', vaultId, reservationId };
  const lease = await f.send();
  assert.equal(lease.statusCode, 200);
  f.req.headers['x-hosted-upload-lease'] = lease.body.lease;
  const another = { ...item, key: 'objects/bb/' + 'b'.repeat(62) + '.cvchunk' };
  f.req.body = { action: 'batch', vaultId, reservationId,
    items: [item, another] };
  const prepared = await f.send();
  assert.equal(prepared.statusCode, 200);
  assert.equal(prepared.body.workerOrigin, 'https://r2.fixture.test');
  assert.equal(prepared.body.objects.length, 2);
  for (const [index, source] of [item, another].entries()) {
    const row = prepared.body.objects[index];
    assert.deepEqual(Object.keys(row).sort(),
      ['action', 'headGrant', 'putGrant']);
    assert.equal(row.action, 'put_required');
    const key = `accounts/${accountId}/vaults/${vaultId}/${source.key}`;
    assert.deepEqual(await verifyObjectCapability(row.putGrant,
      'PUT', key, secret), { key, bytes: source.bytes, sha256: source.sha256 });
    assert.deepEqual(await verifyObjectCapability(row.headGrant,
      'HEAD', key, secret), { key, bytes: source.bytes, sha256: source.sha256 });
  }
  assert.equal(f.purchaseChecks(), 1);
  assert.equal(f.subscriptionChecks(), 1);
  assert.equal(f.writes(), 4);
  f.req.body.items = [item, item];
  assert.equal((await f.send()).statusCode, 400);
  f.req.body.items = Array.from({ length: 5 }, (_, index) => ({ ...item,
    key: `objects/${String(index).padStart(2, '0')}/` + 'a'.repeat(62) + '.cvchunk' }));
  assert.equal((await f.send()).statusCode, 400);
  f.req.body.items = [item];
  delete f.req.headers['x-hosted-upload-lease'];
  assert.equal((await f.send()).statusCode, 403);
});

test('a failed batch returns no partial grants and an exact retry succeeds', async () => {
  const f = fixture();
  f.req.body = { action: 'lease', vaultId, reservationId };
  const lease = await f.send();
  f.req.headers['x-hosted-upload-lease'] = lease.body.lease;
  const another = { ...item, key: 'objects/bb/' + 'b'.repeat(62) + '.cvchunk' };
  f.req.body = { action: 'batch', vaultId, reservationId,
    items: [item, another] };
  f.denyGrantFor(`accounts/${accountId}/vaults/${vaultId}/${another.key}`);
  const denied = await f.send();
  assert.equal(denied.statusCode, 503);
  assert.deepEqual(denied.body, { error: 'temporarily_unavailable' });
  assert.equal(JSON.stringify(denied.body).includes('grant'), false);
  f.denyGrantFor(null);
  const retry = await f.send();
  assert.equal(retry.statusCode, 200);
  assert.deepEqual(retry.body.objects.map(row => row.action),
    ['head', 'put_required']);
});

test('batch object grants cannot outlive the entitlement lease', async () => {
  const f = fixture();
  f.req.headers['x-hosted-upload-lease'] = mintUploadLease({
    accountId, vaultId, reservationId, deviceHash: f.session.tokenHash,
    allowanceBytes: 100_000_000, secret, now: Date.now() - 50_000,
  });
  f.req.body = { action: 'batch', vaultId, reservationId, items: [item] };
  const result = await f.send();
  assert.equal(result.statusCode, 200);
  const key = `accounts/${accountId}/vaults/${vaultId}/${item.key}`;
  const grant = result.body.objects[0].putGrant;
  assert.deepEqual(await verifyObjectCapability(grant, 'PUT', key, secret,
    Date.now() + 5_000), { key, bytes: item.bytes, sha256: item.sha256 });
  await assert.rejects(verifyObjectCapability(grant, 'PUT', key, secret,
    Date.now() + 11_000), /hosted_object_access_denied/);
});

test('single-object PUT and HEAD grants also expire with the lease', async () => {
  const f = fixture();
  f.req.headers['x-hosted-upload-lease'] = mintUploadLease({
    accountId, vaultId, reservationId, deviceHash: f.session.tokenHash,
    allowanceBytes: 100_000_000, secret, now: Date.now() - 50_000,
  });
  f.req.body = { action: 'put', vaultId, reservationId, item };
  const put = await f.send();
  assert.equal(put.statusCode, 200);
  f.req.body.action = 'decide';
  const head = await f.send();
  assert.equal(head.statusCode, 200);
  assert.equal(head.body.action, 'head');
  const key = `accounts/${accountId}/vaults/${vaultId}/${item.key}`;
  for (const [method, grant] of [['PUT', put.body.grant],
    ['HEAD', head.body.grant]]) {
    await assert.rejects(verifyObjectCapability(grant, method, key, secret,
      Date.now() + 11_000), /hosted_object_access_denied/);
  }
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
  f.setReservationState('published');
  assert.deepEqual((await f.send()).body, { state: 'published',
    snapshotId: 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
    verifiedObjectCount: 3 });
  assert.equal(f.reads(), 3);
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
  f.req.headers['x-hosted-upload-lease'] = 'synthetic.valid';
  const broken = makeHandler(async () => {
    throw Error('private Stripe and database details');
  }, f.env);
  const res = response();
  await broken(f.req, res);
  assert.equal(res.statusCode, 503);
  assert.deepEqual(res.body, { error: 'temporarily_unavailable' });
});
