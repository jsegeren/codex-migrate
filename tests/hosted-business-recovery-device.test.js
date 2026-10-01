const test = require('node:test');
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { makeHandler } = require('../api/hosted-business-recovery-device');
const { businessRecoveryMail } = require('../hosted/business_recovery_mail');
const { businessDeviceTokenHash } = require('../hosted/business_worker');
const { authorizeBusinessReadScope, authorizeBusinessUploadScope } =
  require('../hosted/access');
const { deviceCredential, authorizeAbandon } =
  require('../hosted/request_access');

function response() {
  return { headers: {}, setHeader(key, value) { this.headers[key] = value; },
    end(value) { this.body = JSON.parse(value); } };
}

function fixture() {
  const accountId = randomUUID();
  const seatId = randomUUID();
  const vaultId = randomUUID();
  const deviceId = randomUUID();
  const deviceToken = `hvb1_${'a'.repeat(43)}`;
  const adminToken = `hva1_${'b'.repeat(43)}`;
  const deviceTokenHash = businessDeviceTokenHash(deviceToken);
  const purpose = 'Original employee Mac is unavailable';
  const env = { HOSTED_MODE: 'sandbox',
    HOSTED_BUSINESS_RECOVERY_SANDBOX_OPEN: 'yes' };
  let loads = 0;
  let emailed;
  let challengeHash;
  let requestId;
  const handler = makeHandler(async received => {
    assert.equal(received, env);
    loads++;
    return { query: async (sql, values) => {
      if (sql.includes('issue_business_recovery_request')) {
        assert.deepEqual(values.slice(1, 4), [accountId, seatId, vaultId]);
        assert.equal(values[5], purpose);
        requestId = values[4];
        challengeHash = values[6];
        return { rows: [{ contact: 'admin@example.test' }] };
      }
      if (sql.includes('record_business_recovery_delivery')) {
        assert.deepEqual(values, [challengeHash, 'sent']);
        return { rows: [{ recorded: true }] };
      }
      assert.match(sql, /claim_business_recovery_device/);
      assert.deepEqual(values, [accountId, seatId, vaultId, requestId,
        challengeHash, deviceId, deviceTokenHash]);
      return { rows: [{ vault_id: vaultId }] };
    }, sendChallenge: async message => { emailed = message; return 'accepted'; } };
  }, env);
  const req = { method: 'POST', headers: {
    'content-type': 'application/json',
    origin: 'https://codexbackup.segeren.com',
    authorization: `Bearer ${adminToken}`,
  }, body: { action: 'begin', accountId, seatId, vaultId, purpose } };
  return { env, req, accountId, seatId, vaultId, deviceId, deviceToken,
    deviceTokenHash, purpose, loads: () => loads, emailed: () => emailed,
    requestId: () => requestId,
    send: async () => { const res = response(); await handler(req, res); return res; } };
}

test('recovery route is default-off and refuses live, cross-origin or anonymous request',
  async () => {
    const f = fixture();
    f.env.HOSTED_BUSINESS_RECOVERY_SANDBOX_OPEN = 'no';
    assert.equal((await f.send()).statusCode, 404);
    f.env.HOSTED_BUSINESS_RECOVERY_SANDBOX_OPEN = 'yes';
    f.env.HOSTED_MODE = 'live';
    assert.equal((await f.send()).statusCode, 404);
    f.env.HOSTED_MODE = 'sandbox';
    f.req.headers.origin = 'https://attacker.example';
    assert.equal((await f.send()).statusCode, 400);
    f.req.headers.origin = 'https://codexbackup.segeren.com';
    delete f.req.headers.authorization;
    assert.equal((await f.send()).statusCode, 403);
    assert.equal(f.loads(), 0);
  });

test('fresh administrator request pairs only the exact short-lived recovery device',
  async () => {
    const f = fixture();
    const begun = await f.send();
    assert.equal(begun.statusCode, 200);
    assert.deepEqual(begun.body, { requestId: f.requestId(), status: 'sent' });
    assert.equal(f.emailed().to, 'admin@example.test');
    assert.equal(f.emailed().purpose, 'business-recovery-sandbox');
    assert.equal(f.emailed().requestId, f.requestId());
    assert.match(f.emailed().code, /^hvcr1_[A-Za-z0-9_-]{43}$/);
    f.req.body = { action: 'claim', accountId: f.accountId, seatId: f.seatId,
      vaultId: f.vaultId, requestId: f.requestId(), code: f.emailed().code,
      deviceId: f.deviceId, deviceTokenHash: f.deviceTokenHash };
    delete f.req.headers.authorization;
    const claimed = await f.send();
    assert.equal(claimed.statusCode, 200);
    assert.deepEqual(claimed.body, { accountId: f.accountId,
      seatId: f.seatId, vaultId: f.vaultId, deviceId: f.deviceId });
    assert.equal(f.loads(), 2);
    assert.equal(JSON.stringify(f.req.body).includes(f.deviceToken), false);
  });

test('recovery request rejects malformed or untrusted purpose before sending',
  async () => {
    const f = fixture();
    f.req.body.purpose = ' read all employees ';
    assert.equal((await f.send()).statusCode, 503);
    f.req.body.purpose = 'Original Mac lost\nRead all employees';
    assert.equal((await f.send()).statusCode, 503);
    assert.equal(f.emailed(), undefined);
  });

test('recovery session can read its exact Vault but upload SQL excludes it',
  async () => {
    const f = fixture();
    const query = async (sql, values) => {
      assert.deepEqual(values, [f.deviceTokenHash, f.vaultId]);
      if (sql.includes('business_backup_entitlements')) {
        assert.match(sql, /d\.access_purpose = 'worker'/);
        return { rows: [] };
      }
      return { rows: [{ account_id: f.accountId, vault_id: f.vaultId }] };
    };
    const read = await authorizeBusinessReadScope({
      sessionToken: f.deviceToken, vaultId: f.vaultId, query });
    assert.equal(read.accountId, f.accountId);
    await assert.rejects(authorizeBusinessUploadScope({
      sessionToken: f.deviceToken, vaultId: f.vaultId, query }),
    /hosted_access_denied/);
    const credential = deviceCredential(`Bearer ${f.deviceToken}`, {
      HOSTED_MODE: 'sandbox', HOSTED_BUSINESS_BACKUP_SANDBOX_OPEN: 'yes' });
    await assert.rejects(authorizeAbandon({ credential, vaultId: f.vaultId,
      query: async sql => {
        assert.match(sql, /d\.access_purpose = 'worker'/);
        return { rows: [] };
      } }), /hosted_access_denied/);
    const workerAbandon = await authorizeAbandon({ credential,
      vaultId: f.vaultId, query: async sql => {
        assert.match(sql, /d\.access_purpose = 'worker'/);
        return { rows: [{ account_id: f.accountId,
          vault_id: f.vaultId }] };
      } });
    assert.equal(workerAbandon.accountId, f.accountId);
  });

test('recovery email only goes to the configured sandbox sink', async () => {
  const f = fixture();
  const env = { COMMERCE_SANDBOX_EMAIL: 'admin@example.test',
    LAUNCH_FROM_EMAIL: 'backup@example.test', SENDGRID_API_KEY: 'synthetic' };
  let calls = 0;
  const send = async (_url, options) => {
    calls++;
    const message = JSON.parse(options.body);
    assert.equal(message.personalizations[0].to[0].email,
      'admin@example.test');
    assert.equal(message.tracking_settings.open_tracking.enable, false);
    return { status: 202 };
  };
  const input = { to: 'admin@example.test', code: `hvcr1_${'a'.repeat(43)}`,
    purpose: 'business-recovery-sandbox', requestId: randomUUID() };
  assert.equal(await businessRecoveryMail(input, env, send), 'accepted');
  assert.equal(await businessRecoveryMail({ ...input, to: 'other@example.test' },
    env, send), 'rejected');
  assert.equal(calls, 1);
});
