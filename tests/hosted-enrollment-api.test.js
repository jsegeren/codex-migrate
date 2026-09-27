const test = require('node:test');
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { makeHandler, enrollmentRuntime } = require('../api/hosted-enrollment');
const { sandboxDatabaseUrl } = require('../hosted/recovery_runtime');
const { mintSessionSecret } = require('./hosted-device-fixture');

const purchaseToken = 'cs_test_fixture.' + 'a'.repeat(64);
const purchase = Object.freeze({ sessionId: 'cs_test_fixture',
  mode: 'sandbox', email: 'fixture@example.test' });

function response() {
  return { headers: {}, setHeader(key, value) { this.headers[key] = value; },
    end(value) { this.body = JSON.parse(value); } };
}

function fixture() {
  const env = { HOSTED_MODE: 'sandbox', HOSTED_SANDBOX_ENROLLMENT_OPEN: 'yes' };
  const session = mintSessionSecret();
  const deviceId = randomUUID();
  let accountId;
  let vaultId;
  let code;
  let loads = 0;
  let queries = 0;
  const handler = makeHandler(async received => {
    assert.equal(received, env);
    loads++;
    return {
      query: async (sql, values) => {
        queries++;
        if (sql.includes('issue_enrollment_challenge')) {
          assert.deepEqual(values.slice(0, 2), [purchase.sessionId, purchase.mode]);
          return { rows: [{ issued: true }] };
        }
        if (sql.includes('record_enrollment_challenge_delivery')) {
          assert.equal(values[1], 'sent');
          return { rows: [{ recorded: true }] };
        }
        if (sql.includes('claim_and_pair_first_device')) {
          assert.deepEqual(values.slice(1, 3), [purchase.sessionId, purchase.mode]);
          assert.deepEqual(values.slice(5), [deviceId, session.tokenHash]);
          accountId = values[3];
          vaultId = values[4];
          return { rows: [{ account_id: accountId }] };
        }
        assert.match(sql, /FROM hosted\.device_sessions/);
        assert.deepEqual(values, [session.tokenHash, deviceId]);
        return { rows: [{ account_id: accountId, vault_id: vaultId,
          device_id: deviceId, purchase_session_id: purchase.sessionId,
          purchase_mode: purchase.mode }] };
      },
      verifyPurchaseToken: async token => {
        assert.equal(token, purchaseToken);
        return purchase;
      },
      verifyPurchaseSession: async (id, mode) => {
        assert.deepEqual([id, mode], [purchase.sessionId, purchase.mode]);
        return purchase;
      },
      sendChallenge: async delivery => {
        assert.equal(delivery.to, purchase.email);
        assert.equal(delivery.live, false);
        code = delivery.code;
        return 'accepted';
      },
    };
  }, env);
  const req = { method: 'POST', headers: { 'content-type': 'application/json' },
    body: { action: 'begin', purchaseToken } };
  return { env, req, session, deviceId,
    code: () => code, loads: () => loads, queries: () => queries,
    send: async () => { const res = response(); await handler(req, res); return res; } };
}

test('closed, live, and malformed requests never open the enrollment runtime', async () => {
  const f = fixture();
  f.env.HOSTED_SANDBOX_ENROLLMENT_OPEN = 'no';
  assert.equal((await f.send()).statusCode, 404);
  f.env.HOSTED_SANDBOX_ENROLLMENT_OPEN = 'yes';
  f.env.HOSTED_MODE = 'live';
  assert.equal((await f.send()).statusCode, 404);
  f.env.HOSTED_MODE = 'sandbox';
  f.req.body.extra = 'untrusted';
  assert.equal((await f.send()).statusCode, 400);
  delete f.req.body.extra;
  f.req.headers.origin = 'https://attacker.example';
  assert.equal((await f.send()).statusCode, 400);
  delete f.req.headers.origin;
  f.req.body = { action: 'resolve', deviceId: f.deviceId };
  assert.equal((await f.send()).statusCode, 403);
  assert.equal(f.loads(), 0);
  assert.equal(f.queries(), 0);
});

test('sandbox enrollment rechecks purchase, proves email, then pairs one device', async () => {
  const f = fixture();
  const begun = await f.send();
  assert.equal(begun.statusCode, 200);
  assert.deepEqual(begun.body, { status: 'sent' });
  assert.equal(begun.headers['Cache-Control'], 'no-store');
  assert.match(f.code(), /^hve1_[A-Za-z0-9_-]{43}$/);

  f.req.body = { action: 'claim', purchaseToken, code: f.code(),
    deviceId: f.deviceId, deviceTokenHash: f.session.tokenHash };
  const paired = await f.send();
  assert.equal(paired.statusCode, 200);
  assert.equal(paired.body.vaultId.length, 36);
  assert.equal(paired.body.deviceId, f.deviceId);
  assert.deepEqual(Object.keys(paired.body).sort(), ['accountId', 'deviceId', 'vaultId']);
  assert.equal(JSON.stringify(paired.body).includes(f.session.token), false);
  assert.equal(JSON.stringify(paired.body).includes(f.code()), false);

  f.req.body = { action: 'resolve', deviceId: f.deviceId };
  f.req.headers.authorization = `Bearer ${f.session.token}`;
  const resolved = await f.send();
  assert.equal(resolved.statusCode, 200);
  assert.equal(resolved.body.accountId, paired.body.accountId);
  assert.equal(resolved.body.vaultId, paired.body.vaultId);
  assert.equal(resolved.body.deviceId, f.deviceId);
  assert.equal(f.loads(), 3);
});

test('provider and database failures return only a generic error', async () => {
  const env = { HOSTED_MODE: 'sandbox', HOSTED_SANDBOX_ENROLLMENT_OPEN: 'yes' };
  const handler = makeHandler(async () => {
    throw Error('private Stripe customer and database location');
  }, env);
  const req = { method: 'POST', headers: { 'content-type': 'application/json' },
    body: { action: 'begin', purchaseToken } };
  const res = response();
  await handler(req, res);
  assert.equal(res.statusCode, 503);
  assert.deepEqual(res.body, { error: 'temporarily_unavailable' });
});

test('enrollment database is pinned to the sandbox without opening recovery', () => {
  const env = { HOSTED_MODE: 'sandbox', HOSTED_SANDBOX_ENROLLMENT_OPEN: 'yes',
    COMMERCE_DATABASE_URL: 'postgresql://fixture:fixture@ep-square-queen-av5us6bx.c-11.us-east-1.aws.neon.tech/neondb?sslmode=require' };
  assert.equal(sandboxDatabaseUrl(env), env.COMMERCE_DATABASE_URL);
  for (const change of [
    { HOSTED_MODE: 'live' },
    { COMMERCE_DATABASE_URL: env.COMMERCE_DATABASE_URL.replace(
      'ep-square-queen', 'ep-other') },
  ]) {
    assert.throws(() => sandboxDatabaseUrl({ ...env, ...change }),
      /hosted_recovery_unavailable/);
  }
  return assert.rejects(enrollmentRuntime({ ...env, COMMERCE_MODE: 'live' }),
    /hosted_enrollment_unavailable/);
});
