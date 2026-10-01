const test = require('node:test');
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { makeHandler } = require('../api/hosted-enrollment');
const { mintSessionSecret } = require('./hosted-device-fixture');

const purchaseToken = 'cs_test_recovery.' + 'a'.repeat(64);
const purchase = Object.freeze({ sessionId: 'cs_test_recovery',
  mode: 'sandbox', email: 'fixture@example.test' });

function response() {
  return { headers: {}, setHeader(key, value) { this.headers[key] = value; },
    end(value) { this.body = JSON.parse(value); } };
}

test('lost-Mac challenge pairs a new bearer to one selected existing Vault', async () => {
  const env = { HOSTED_MODE: 'sandbox', HOSTED_SANDBOX_ENROLLMENT_OPEN: 'yes' };
  const accountId = randomUUID();
  const vaultIds = [randomUUID(), randomUUID()];
  const deviceId = randomUUID();
  const session = mintSessionSecret();
  let code;
  const calls = [];
  const handler = makeHandler(async () => ({
    verifyPurchaseToken: async value => {
      assert.equal(value, purchaseToken);
      return purchase;
    },
    verifyPurchaseSession: async (id, mode) => {
      assert.deepEqual([id, mode], [purchase.sessionId, purchase.mode]);
      return purchase;
    },
    sendChallenge: async value => {
      assert.deepEqual({ to: value.to, live: value.live,
        purpose: value.purpose },
      { to: purchase.email, live: false, purpose: 'recovery' });
      code = value.code;
      return 'accepted';
    },
    query: async (sql, args) => {
      calls.push(sql);
      if (sql.includes('issue_recovery_challenge')) {
        assert.deepEqual(args.slice(0, 2), [purchase.sessionId, purchase.mode]);
        return { rows: [{ issued: true }] };
      }
      if (sql.includes('record_recovery_challenge_delivery')) {
        assert.equal(args[1], 'sent');
        return { rows: [{ recorded: true }] };
      }
      if (sql.includes('list_recovery_vaults')) {
        return { rows: [{ vault_id: vaultIds[0], published_at: null },
          { vault_id: vaultIds[1],
            published_at: new Date('2026-09-27T12:00:00.000Z') }] };
      }
      if (sql.includes('claim_recovery_vault_device')) {
        assert.deepEqual(args.slice(3), [vaultIds[1], deviceId,
          session.tokenHash]);
        return { rows: [{ account_id: accountId }] };
      }
      assert.match(sql, /FROM hosted\.device_sessions/);
      assert.deepEqual(args, [session.tokenHash, deviceId]);
      return { rows: [{ account_id: accountId, vault_id: vaultIds[1],
        device_id: deviceId, purchase_session_id: purchase.sessionId,
        purchase_mode: purchase.mode }] };
    },
  }), env);
  const req = { method: 'POST', headers: { 'content-type': 'application/json' },
    body: { action: 'begin_recovery', purchaseToken } };
  async function send() { const res = response(); await handler(req, res); return res; }

  assert.deepEqual((await send()).body, { status: 'sent' });
  assert.match(code, /^hve1_[A-Za-z0-9_-]{43}$/);
  req.body = { action: 'list_recovery_vaults', purchaseToken, code };
  const listed = await send();
  assert.equal(listed.statusCode, 200);
  assert.deepEqual(listed.body, { vaults: [
    { vaultId: vaultIds[0], lastGoodAt: null },
    { vaultId: vaultIds[1], lastGoodAt: '2026-09-27T12:00:00.000Z' },
  ] });
  req.body = { action: 'claim_recovery', purchaseToken, code,
    vaultId: vaultIds[1], deviceId, deviceTokenHash: session.tokenHash };
  const paired = await send();
  assert.equal(paired.statusCode, 200);
  assert.deepEqual(paired.body, { accountId, vaultId: vaultIds[1], deviceId });
  assert.equal(JSON.stringify(paired.body).includes(code), false);
  assert.equal(JSON.stringify(paired.body).includes(session.token), false);
  req.body = { action: 'resolve', deviceId };
  req.headers.authorization = `Bearer ${session.token}`;
  assert.deepEqual((await send()).body, paired.body);
  assert.equal(calls.length, 5);
});

test('recovery route stays dark and rejects malformed or unproved requests', async () => {
  const env = { HOSTED_MODE: 'sandbox', HOSTED_SANDBOX_ENROLLMENT_OPEN: 'no' };
  let loads = 0;
  const handler = makeHandler(async () => { loads++; throw Error('never load'); }, env);
  const req = { method: 'POST', headers: { 'content-type': 'application/json' },
    body: { action: 'begin_recovery', purchaseToken } };
  const send = async () => { const res = response(); await handler(req, res); return res; };
  assert.equal((await send()).statusCode, 404);
  env.HOSTED_SANDBOX_ENROLLMENT_OPEN = 'yes';
  env.HOSTED_MODE = 'live';
  assert.equal((await send()).statusCode, 404);
  env.HOSTED_MODE = 'sandbox';
  req.body = { action: 'claim_recovery', purchaseToken, code: 'bad',
    vaultId: randomUUID(), deviceId: randomUUID(), deviceTokenHash: 'f'.repeat(64),
    extra: 'bad' };
  assert.equal((await send()).statusCode, 400);
  assert.equal(loads, 0);
});
