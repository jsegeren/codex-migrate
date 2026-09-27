const test = require('node:test');
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { beginEnrollment, claimEnrollment, resolveFirstDevice } = require('../hosted/enrollment');
const { mintSessionSecret } = require('./hosted-device-fixture');

const purchase = Object.freeze({ sessionId: 'cs_test_fixture', mode: 'sandbox',
  email: 'buyer@example.test' });
  const purchaseToken = 'private-purchase-locator';

test('enrollment emails a fresh code and cannot issue an upload capability', async () => {
  let emailed;
  let savedHash;
  const deviceId = randomUUID();
  const device = mintSessionSecret();
  const verifyPurchase = async token => {
    assert.equal(token, purchaseToken);
    return purchase;
  };
  const query = async (statement, values) => {
    if (statement.includes('issue_enrollment_challenge')) {
      assert.deepEqual(values.slice(0, 2), ['cs_test_fixture', 'sandbox']);
      savedHash = values[2];
      assert.match(savedHash, /^[0-9a-f]{64}$/);
      return { rows: [{ issued: true }] };
    }
    if (statement.includes('record_enrollment_challenge_delivery')) {
      assert.equal(values[0], savedHash);
      assert.equal(values[1], 'sent');
      return { rows: [{ recorded: true }] };
    }
    if (statement.includes('claim_and_pair_first_device')) {
      assert.equal(values[0], savedHash);
      assert.equal(values[1], purchase.sessionId);
      assert.equal(values[2], purchase.mode);
      assert.match(values[4], /^[0-9a-f-]{36}$/);
      assert.match(values[5], /^[0-9a-f-]{36}$/);
      assert.equal(values[5], deviceId);
      assert.equal(values[6], device.tokenHash);
      return { rows: [{ account_id: values[3] }] };
    }
    throw Error('unexpected query');
  };
  const begun = await beginEnrollment({ purchaseToken, verifyPurchase, query,
    sendChallenge: async message => {
      emailed = message;
      return 'accepted';
    } });
  assert.deepEqual(begun, { status: 'sent' });
  assert.equal(Object.isFrozen(begun), true);
  assert.match(emailed.code, /^hve1_[A-Za-z0-9_-]{43}$/);
  assert.equal(emailed.to, purchase.email);
  assert.equal(emailed.live, false);
  assert.equal(savedHash.includes(emailed.code), false);
  assert.equal('code' in begun, false);
  assert.equal('accountId' in begun, false);

  const claim = await claimEnrollment({ purchaseToken, code: emailed.code,
    deviceId, deviceTokenHash: device.tokenHash, verifyPurchase, query });
  assert.match(claim.accountId, /^[0-9a-f-]{36}$/);
  assert.match(claim.vaultId, /^[0-9a-f-]{36}$/);
  assert.equal(claim.deviceId, deviceId);
  assert.equal('deviceToken' in claim, false);
  assert.equal(Object.isFrozen(claim), true);
  assert.equal(savedHash.includes(device.token), false);

  // A lost claim response does not strand the account: the native helper
  // retains the token and can resolve the same account/Vault after restart.
  const recovered = await resolveFirstDevice({ deviceToken: device.token,
    deviceId, verifyPurchase: async (id, mode) => {
      assert.deepEqual([id, mode], [purchase.sessionId, purchase.mode]);
      return purchase;
    }, query: async (sql, values) => {
      assert.match(sql, /revoked_at IS NULL/);
      assert.deepEqual(values, [device.tokenHash, deviceId]);
      return { rows: [{ account_id: claim.accountId, vault_id: claim.vaultId,
        device_id: deviceId, purchase_session_id: purchase.sessionId,
        purchase_mode: purchase.mode }] };
    } });
  assert.deepEqual(recovered, claim);
});

test('rate limits, mail uncertainty, and payment failures cannot claim an account', async () => {
  let sends = 0;
  const verifyPurchase = async () => purchase;
  const sendChallenge = async () => { sends++; return 'accepted'; };
  await assert.rejects(beginEnrollment({ purchaseToken, verifyPurchase,
    query: async () => ({ rows: [{ issued: false }] }), sendChallenge }),
  /hosted_enrollment_unavailable/);
  assert.equal(sends, 0);
  await assert.rejects(beginEnrollment({ purchaseToken, verifyPurchase,
    query: async (statement, values) => ({ rows: [statement.includes('issue_')
      ? { issued: true } : { recorded: values[1] === 'sent' }] }),
    sendChallenge: async () => 'uncertain' }), /hosted_enrollment_unavailable/);
  await assert.rejects(beginEnrollment({ purchaseToken,
    verifyPurchase: async () => { throw Error('Stripe private detail'); },
    query: async () => { throw Error('should not query'); }, sendChallenge }),
  error => error.message === 'hosted_enrollment_unavailable');
  await assert.rejects(claimEnrollment({ purchaseToken, code: 'not-a-code',
    verifyPurchase, query: async () => { throw Error('should not query'); } }),
  /hosted_enrollment_unavailable/);
  await assert.rejects(claimEnrollment({ purchaseToken, code: `hve1_${'a'.repeat(43)}`,
    deviceId: randomUUID(), deviceTokenHash: 'a'.repeat(64),
    verifyPurchase, query: async () => ({ rows: [{ account_id: null }] }) }),
  /hosted_enrollment_unavailable/);
  await assert.rejects(claimEnrollment({ purchaseToken, code: `hve1_${'a'.repeat(43)}`,
    deviceId: randomUUID(), deviceTokenHash: 'not-a-hash', verifyPurchase,
    query: async () => { throw Error('should not query'); } }),
  /hosted_enrollment_unavailable/);
  await assert.rejects(resolveFirstDevice({ deviceToken: mintSessionSecret().token,
    deviceId: randomUUID(), query: async () => ({ rows: [] }),
    verifyPurchase: async () => { throw Error('should not verify'); } }),
  /hosted_enrollment_unavailable/);
  await assert.rejects(resolveFirstDevice({ deviceToken: mintSessionSecret().token,
    deviceId: randomUUID(), query: async () => { throw Error('private DB'); },
    verifyPurchase: async () => purchase }),
  /hosted_enrollment_unavailable/);
  const device = mintSessionSecret();
  const deviceId = randomUUID();
  await assert.rejects(resolveFirstDevice({ deviceToken: device.token,
    deviceId, query: async () => ({ rows: [{ account_id: randomUUID(),
      vault_id: randomUUID(), device_id: deviceId,
      purchase_session_id: purchase.sessionId, purchase_mode: purchase.mode }] }),
    verifyPurchase: async () => { throw Error('refunded purchase'); } }),
  /hosted_enrollment_unavailable/);
  await assert.rejects(resolveFirstDevice({ deviceToken: device.token,
    deviceId, query: async () => ({ rows: [{ account_id: randomUUID(),
      vault_id: randomUUID(), device_id: randomUUID(),
      purchase_session_id: purchase.sessionId, purchase_mode: purchase.mode }] }),
    verifyPurchase: async () => { throw Error('should not verify'); } }),
  /hosted_enrollment_unavailable/);
});
