const test = require('node:test');
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { beginBusinessWorkerPairing, claimBusinessFirstDevice,
  resolveBusinessFirstDevice, businessDeviceTokenHash } =
  require('../hosted/business_worker');
const { businessWorkerMail } = require('../hosted/business_worker_mail');
const { tokenHash: personalDeviceTokenHash } = require('../hosted/access');

test('exact worker email proof pairs one separately hashed device', async () => {
  const accountId = randomUUID();
  const seatId = randomUUID();
  const vaultId = randomUUID();
  const deviceId = randomUUID();
  const deviceToken = `hvb1_${'a'.repeat(43)}`;
  const adminSessionToken = `hva1_${'b'.repeat(43)}`;
  const deviceTokenHash = businessDeviceTokenHash(deviceToken);
  assert.throws(() => personalDeviceTokenHash(deviceToken),
    /hosted_access_denied/);
  let mailed;
  let codeHash;
  const query = async (sql, values) => {
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
        vaultId, deviceId, deviceTokenHash]);
      return { rows: [{ vault_id: vaultId }] };
    }
    assert.match(sql, /business_device_sessions/);
    assert.match(sql, /s\.revoked_at IS NULL/);
    assert.deepEqual(values, [deviceTokenHash, deviceId]);
    return { rows: [{ account_id: accountId, seat_id: seatId,
      vault_id: vaultId, device_id: deviceId }] };
  };
  assert.deepEqual(await beginBusinessWorkerPairing({ adminSessionToken,
    accountId, seatId,
    query, sendChallenge: async message => { mailed = message; return 'accepted'; } }),
  { status: 'sent' });
  assert.equal(mailed.to, 'worker@example.test');
  assert.equal(mailed.purpose, 'business-worker-sandbox');
  assert.match(mailed.code, /^hvwe1_[A-Za-z0-9_-]{43}$/);
  assert.equal(codeHash.includes(mailed.code), false);
  assert.deepEqual(await claimBusinessFirstDevice({ accountId, seatId,
    code: mailed.code, vaultId, deviceId, deviceTokenHash, query }),
  { accountId, seatId, vaultId, deviceId });
  assert.deepEqual(await resolveBusinessFirstDevice({ deviceToken, deviceId,
    query }), { accountId, seatId, vaultId, deviceId });
});

test('unknown seat, uncertain mail, wrong code, and revoked device fail closed', async () => {
  const accountId = randomUUID();
  const seatId = randomUUID();
  const adminSessionToken = `hva1_${'b'.repeat(43)}`;
  let sends = 0;
  await assert.rejects(beginBusinessWorkerPairing({ adminSessionToken,
    accountId, seatId,
    query: async () => ({ rows: [{ contact: null }] }),
    sendChallenge: async () => { sends++; return 'accepted'; } }),
  /business_worker_unavailable/);
  assert.equal(sends, 0);
  await assert.rejects(beginBusinessWorkerPairing({ adminSessionToken,
    accountId, seatId,
    query: async (sql, values) => ({ rows: [sql.includes('issue_') ?
      { contact: 'worker@example.test' } :
      { recorded: values[1] === 'uncertain' }] }),
    sendChallenge: async () => 'uncertain' }),
  /business_worker_unavailable/);
  await assert.rejects(claimBusinessFirstDevice({ accountId, seatId,
    code: 'wrong', vaultId: randomUUID(), deviceId: randomUUID(),
    deviceTokenHash: 'a'.repeat(64),
    query: async () => { throw Error('no query'); } }),
  /business_worker_unavailable/);
  await assert.rejects(resolveBusinessFirstDevice({
    deviceToken: `hvb1_${'a'.repeat(43)}`, deviceId: randomUUID(),
    query: async () => ({ rows: [] }) }),
  /business_worker_unavailable/);
  assert.throws(() => businessDeviceTokenHash(`hv1_${'a'.repeat(43)}`),
    /business_worker_unavailable/);
});

test('worker pairing email is restricted to the sandbox sink', async () => {
  const env = { LAUNCH_FROM_EMAIL: 'from@example.test',
    COMMERCE_SANDBOX_EMAIL: 'worker@example.test', SENDGRID_API_KEY: 'fixture' };
  const message = { to: 'worker@example.test',
    code: `hvwe1_${'a'.repeat(43)}`, purpose: 'business-worker-sandbox' };
  let sends = 0;
  const request = async (url, options) => {
    sends++;
    assert.equal(url, 'https://api.sendgrid.com/v3/mail/send');
    const body = JSON.parse(options.body);
    assert.equal(body.personalizations[0].to[0].email, message.to);
    assert.equal(body.tracking_settings.open_tracking.enable, false);
    assert.match(body.content[0].value, /does not start or authorize a backup/);
    return { status: 202 };
  };
  assert.equal(await businessWorkerMail(message, env, request), 'accepted');
  assert.equal(await businessWorkerMail({ ...message,
    to: 'other@example.test' }, env, request), 'rejected');
  assert.equal(await businessWorkerMail({ ...message,
    purpose: 'business-worker-live' }, env, request), 'rejected');
  assert.equal(sends, 1);
});
