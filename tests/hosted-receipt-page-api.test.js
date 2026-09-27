const test = require('node:test');
const assert = require('node:assert/strict');
const { makeHandler } = require('../api/hosted-receipt-page');
const { mintSessionSecret } = require('./hosted-device-fixture');
const { accountId, vaultId } = require('./hosted-subscriber-fixture');

const reservationId = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const snapshotId = '11111111-1111-4111-8111-111111111111';
const object = { key: `metadata/${snapshotId}.json`, bytes: 20,
  sha256: 'a'.repeat(64) };

function response() {
  return { headers: {}, setHeader(key, value) { this.headers[key] = value; },
    end(value) { this.body = JSON.parse(value); } };
}

function fixture() {
  const session = mintSessionSecret();
  const env = { HOSTED_MODE: 'sandbox', HOSTED_SANDBOX_UPLOAD_OPEN: 'yes' };
  const priceCatalog = new Map([['price_fixture', { priceCents: 1000,
    allowanceBytes: 100_000_000 }]]);
  let loads = 0;
  let pageWrites = 0;
  let status = 'active';
  const handler = makeHandler(async () => {
    loads++;
    return { live: false, priceCatalog,
      query: async (sql, values) => {
        if (sql.includes('FROM hosted.device_sessions AS sessions')) {
          assert.deepEqual(values, [session.tokenHash, vaultId]);
          return { rows: [{ account_id: accountId, vault_id: vaultId,
            purchase_session_id: 'cs_test_fixture', purchase_mode: 'sandbox' }] };
        }
        assert.match(sql, /append_receipt_page_current/);
        assert.deepEqual(values.slice(0, 4), [accountId, vaultId,
          reservationId, snapshotId]);
        assert.deepEqual(JSON.parse(values[4]), [{ ...object,
          key: `accounts/${accountId}/vaults/${vaultId}/${object.key}` }]);
        pageWrites++;
        return { rows: [{ accepted: true }] };
      },
      verifyPurchase: async () => ({ sessionId: 'cs_test_fixture',
        mode: 'sandbox' }),
      getEntitlement: async () => ({
        enrollment: { accountId, subscriptionId: 'sub_fixture',
          customerId: 'cus_fixture', priceId: 'price_fixture' },
        subscription: { id: 'sub_fixture', customer: 'cus_fixture',
          livemode: false, status, collection_method: 'charge_automatically',
          pause_collection: null, items: { data: [{ quantity: 1,
            price: { id: 'price_fixture', livemode: false,
              type: 'recurring', currency: 'usd', unit_amount: 1000,
              billing_scheme: 'per_unit', recurring: { interval: 'month',
                interval_count: 1 } } }] } },
      }),
    };
  }, env);
  const req = { method: 'POST', headers: { authorization: `Bearer ${session.token}`,
    'content-type': 'application/json' }, body: { action: 'page', vaultId,
      reservationId, snapshotId, objects: [object] } };
  return { env, req, loads: () => loads, pageWrites: () => pageWrites,
    lapse: () => { status = 'past_due'; },
    send: async () => { const res = response(); await handler(req, res); return res; } };
}

test('closed, oversized, malformed and unauthenticated pages touch no runtime', async () => {
  const f = fixture();
  f.env.HOSTED_SANDBOX_UPLOAD_OPEN = 'no';
  assert.equal((await f.send()).statusCode, 404);
  f.env.HOSTED_SANDBOX_UPLOAD_OPEN = 'yes';
  f.req.body.extra = true;
  assert.equal((await f.send()).statusCode, 400);
  delete f.req.body.extra;
  f.req.headers['content-length'] = String(256 * 1024 + 1);
  assert.equal((await f.send()).statusCode, 400);
  delete f.req.headers['content-length'];
  f.req.headers.authorization = 'Bearer forged';
  assert.equal((await f.send()).statusCode, 403);
  assert.equal(f.loads(), 0);
});

test('paid sandbox device admits a bounded page but never publishes', async () => {
  const f = fixture();
  const result = await f.send();
  assert.equal(result.statusCode, 200);
  assert.deepEqual(result.body, { acceptedObjects: 1 });
  assert.equal(result.headers['Cache-Control'], 'no-store');
  assert.equal(f.pageWrites(), 1);
  f.req.body.objects = [object, object];
  assert.equal((await f.send()).statusCode, 503);
  assert.equal(f.pageWrites(), 1);
});

test('lapsed subscription cannot admit a page', async () => {
  const f = fixture();
  f.lapse();
  assert.equal((await f.send()).statusCode, 403);
  assert.equal(f.pageWrites(), 0);
});
