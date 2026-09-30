const test = require('node:test');
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { makeHandler, businessWorkerRuntime } =
  require('../api/hosted-business-device');
const { businessDeviceTokenHash } = require('../hosted/business_worker');

function response() {
  return { headers: {}, setHeader(key, value) { this.headers[key] = value; },
    end(value) { this.body = JSON.parse(value); } };
}

function fixture() {
  const accountId = randomUUID();
  const seatId = randomUUID();
  const vaultId = randomUUID();
  const deviceId = randomUUID();
  const token = `hvb1_${'a'.repeat(43)}`;
  const adminToken = `hva1_${'b'.repeat(43)}`;
  const hash = businessDeviceTokenHash(token);
  const env = { HOSTED_MODE: 'sandbox',
    HOSTED_BUSINESS_WORKER_SANDBOX_OPEN: 'yes' };
  let loads = 0;
  let emailed;
  let codeHash;
  const handler = makeHandler(async received => {
    assert.equal(received, env);
    loads++;
    return { query: async (sql, values) => {
      if (sql.includes('issue_business_worker_challenge')) {
        assert.match(values[0], /^[0-9a-f]{64}$/);
        assert.deepEqual(values.slice(1, 3), [accountId, seatId]);
        codeHash = values[3];
        return { rows: [{ contact: 'worker@example.test' }] };
      }
      if (sql.includes('record_business_worker_challenge_delivery')) {
        assert.deepEqual(values, [codeHash, 'sent']);
        return { rows: [{ recorded: true }] };
      }
      if (sql.includes('claim_business_first_device')) {
        assert.deepEqual(values, [accountId, seatId, codeHash,
          vaultId, deviceId, hash]);
        return { rows: [{ vault_id: vaultId }] };
      }
      assert.match(sql, /business_device_sessions/);
      assert.deepEqual(values, [hash, deviceId]);
      return { rows: [{ account_id: accountId, seat_id: seatId,
        vault_id: vaultId, device_id: deviceId }] };
    }, sendChallenge: async message => { emailed = message; return 'accepted'; } };
  }, env);
  const req = { method: 'POST', headers: {
    'content-type': 'application/json',
    origin: 'https://codexbackup.segeren.com',
    authorization: `Bearer ${adminToken}`,
  }, body: { action: 'begin', accountId, seatId } };
  return { env, req, token, hash, accountId, seatId, vaultId, deviceId,
    loads: () => loads, emailed: () => emailed,
    send: async () => { const res = response(); await handler(req, res); return res; } };
}

test('closed, live, cross-origin, and missing-bearer calls do no work', async () => {
  const f = fixture();
  f.env.HOSTED_BUSINESS_WORKER_SANDBOX_OPEN = 'no';
  assert.equal((await f.send()).statusCode, 404);
  f.env.HOSTED_BUSINESS_WORKER_SANDBOX_OPEN = 'yes';
  f.env.HOSTED_MODE = 'live';
  assert.equal((await f.send()).statusCode, 404);
  f.env.HOSTED_MODE = 'sandbox';
  f.req.headers.origin = 'https://attacker.example';
  assert.equal((await f.send()).statusCode, 400);
  f.req.headers.origin = 'https://codexbackup.segeren.com';
  delete f.req.headers.authorization;
  assert.equal((await f.send()).statusCode, 403);
  f.req.body = { action: 'resolve', deviceId: f.deviceId };
  assert.equal((await f.send()).statusCode, 403);
  assert.equal(f.loads(), 0);
});

test('worker email code pairs one metadata-only device', async () => {
  const f = fixture();
  const begun = await f.send();
  assert.equal(begun.statusCode, 200);
  assert.deepEqual(begun.body, { status: 'sent' });
  assert.equal(begun.headers['Cache-Control'], 'no-store');
  assert.equal(f.emailed().to, 'worker@example.test');
  assert.equal(JSON.stringify(begun.body).includes(f.emailed().code), false);

  f.req.body = { action: 'claim', accountId: f.accountId, seatId: f.seatId,
    code: f.emailed().code, vaultId: f.vaultId, deviceId: f.deviceId,
    deviceTokenHash: f.hash };
  const claimed = await f.send();
  assert.equal(claimed.statusCode, 200);
  assert.deepEqual(claimed.body, { accountId: f.accountId, seatId: f.seatId,
    vaultId: f.vaultId, deviceId: f.deviceId });
  f.req.body = { action: 'resolve', deviceId: f.deviceId };
  f.req.headers.authorization = `Bearer ${f.token}`;
  const resolved = await f.send();
  assert.equal(resolved.statusCode, 200);
  assert.deepEqual(resolved.body, claimed.body);
});

test('runtime refuses missing sandbox database configuration', async () => {
  await assert.rejects(businessWorkerRuntime({
    HOSTED_MODE: 'sandbox', HOSTED_BUSINESS_WORKER_SANDBOX_OPEN: 'yes',
  }));
});
