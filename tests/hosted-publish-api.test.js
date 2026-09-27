const test = require('node:test');
const assert = require('node:assert/strict');
const { makeHandler } = require('../api/hosted-publish');
const { mintSessionSecret } = require('./hosted-device-fixture');
const { accountId, vaultId } = require('./hosted-subscriber-fixture');

const reservationId = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const snapshotId = '11111111-1111-4111-8111-111111111111';
const prefix = `accounts/${accountId}/vaults/${vaultId}/`;

function response() {
  return { headers: {}, setHeader(key, value) { this.headers[key] = value; },
    end(value) { this.body = JSON.parse(value); } };
}

function fixture() {
  const session = mintSessionSecret();
  const env = { HOSTED_MODE: 'sandbox', HOSTED_SANDBOX_UPLOAD_OPEN: 'yes',
    HOSTED_SANDBOX_PUBLISH_OPEN: 'yes' };
  const priceCatalog = new Map([['price_fixture', { priceCents: 1000,
    allowanceBytes: 100_000_000 }]]);
  const object = (key, bytes, hash) => ({ staged_snapshot_id: snapshotId,
    staged_count: 3, staged_bytes: '30', object_key: prefix + key,
    object_bytes: String(bytes), sha256: hash.repeat(64) });
  const stagedRows = [object(`refs/${snapshotId}.json`, 10, 'c'),
    object(`metadata/${snapshotId}.json`, 10, 'a'),
    object(`manifests/${snapshotId}.cvmanifest`, 10, 'b')];
  let loads = 0;
  let verifies = 0;
  let publications = 0;
  let status = 'active';
  let match = true;
  const handler = makeHandler(async () => {
    loads++;
    return { live: false, priceCatalog, workerOrigin: 'https://r2.example.test',
      secret: 'server-only-secret',
      query: async (sql, values) => {
        if (sql.includes('FROM hosted.device_sessions AS sessions')) {
          assert.deepEqual(values, [session.tokenHash, vaultId]);
          return { rows: [{ account_id: accountId, vault_id: vaultId,
            purchase_session_id: 'cs_test_fixture', purchase_mode: 'sandbox' }] };
        }
        if (sql.includes('FROM hosted.upload_reservations')) {
          assert.deepEqual(values, [accountId, vaultId, reservationId, snapshotId]);
          return { rows: stagedRows };
        }
        assert.match(sql, /publish_verified_staged_current/);
        assert.equal(verifies, publications + 1);
        assert.deepEqual(values.slice(0, 4), [accountId, vaultId,
          reservationId, snapshotId]);
        assert.deepEqual(JSON.parse(values[4]).map(item => item.key), [
          prefix + `metadata/${snapshotId}.json`,
          prefix + `manifests/${snapshotId}.cvmanifest`,
          prefix + `refs/${snapshotId}.json`,
        ]);
        publications++;
        return { rows: [{ published: true }] };
      },
      verifyPurchase: async () => ({ sessionId: 'cs_test_fixture',
        mode: 'sandbox' }),
      getEntitlement: async () => ({
        enrollment: { accountId, subscriptionId: 'sub_fixture',
          customerId: 'cus_fixture', priceId: 'price_fixture' },
        subscription: { id: 'sub_fixture', customer: 'cus_fixture',
          livemode: false, status, collection_method: 'charge_automatically',
          pause_collection: null, items: { data: [{ quantity: 1,
            price: { id: 'price_fixture', livemode: false, type: 'recurring',
              currency: 'usd', unit_amount: 1000, billing_scheme: 'per_unit',
              recurring: { interval: 'month', interval_count: 1 } } }] } },
      }),
    };
  }, env, ({ origin, secret }) => {
    assert.equal(origin, 'https://r2.example.test');
    assert.equal(secret, 'server-only-secret');
    return async batch => {
      verifies++;
      assert.equal(batch.length, 3);
      assert.ok(batch.every(item => item.key.startsWith(prefix)));
      return match;
    };
  });
  const req = { method: 'POST', headers: {
    authorization: `Bearer ${session.token}`,
    'content-type': 'application/json',
  }, body: { action: 'publish', vaultId, reservationId, snapshotId } };
  return { env, req, loads: () => loads, verifies: () => verifies,
    publications: () => publications, lapse: () => { status = 'past_due'; },
    mismatch: () => { match = false; },
    send: async () => { const res = response(); await handler(req, res); return res; } };
}

test('publication is dark by default; malformed and unauthenticated calls touch no runtime', async () => {
  const f = fixture();
  f.env.HOSTED_SANDBOX_PUBLISH_OPEN = 'no';
  assert.equal((await f.send()).statusCode, 404);
  f.env.HOSTED_SANDBOX_PUBLISH_OPEN = 'yes';
  f.req.body.receipt = { verified: true };
  assert.equal((await f.send()).statusCode, 400);
  delete f.req.body.receipt;
  f.req.headers['content-length'] = '301';
  assert.equal((await f.send()).statusCode, 400);
  delete f.req.headers['content-length'];
  f.req.headers.authorization = 'Bearer forged';
  assert.equal((await f.send()).statusCode, 403);
  assert.equal(f.loads(), 0);
});

test('paid device publication verifies service-stored objects before advancing last-good', async () => {
  const f = fixture();
  const result = await f.send();
  assert.equal(result.statusCode, 200);
  assert.deepEqual(result.body, { snapshotId, verifiedObjectCount: 3 });
  assert.equal(result.headers['Cache-Control'], 'no-store');
  assert.equal(f.verifies(), 1);
  assert.equal(f.publications(), 1);
  // A lost HTTP response can be retried for this same authorized set.
  assert.equal((await f.send()).statusCode, 200);
  assert.equal(f.publications(), 2);
});

test('lapsed subscription or failed provider check cannot publish', async () => {
  const lapsed = fixture();
  lapsed.lapse();
  assert.equal((await lapsed.send()).statusCode, 403);
  assert.equal(lapsed.verifies(), 0);
  assert.equal(lapsed.publications(), 0);
  const mismatch = fixture();
  mismatch.mismatch();
  assert.equal((await mismatch.send()).statusCode, 503);
  assert.equal(mismatch.verifies(), 1);
  assert.equal(mismatch.publications(), 0);
});
