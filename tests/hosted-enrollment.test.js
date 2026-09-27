const test = require('node:test');
const assert = require('node:assert/strict');
const { beginEnrollment, claimEnrollment } = require('../hosted/enrollment');

const purchase = Object.freeze({ sessionId: 'cs_test_fixture', mode: 'sandbox',
  email: 'buyer@example.test' });
const purchaseToken = 'private-purchase-locator';

test('enrollment emails a fresh code and cannot issue an upload capability', async () => {
  let emailed;
  let savedHash;
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
      assert.match(values[6], /^[0-9a-f]{64}$/);
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
    verifyPurchase, query });
  assert.match(claim.accountId, /^[0-9a-f-]{36}$/);
  assert.match(claim.vaultId, /^[0-9a-f-]{36}$/);
  assert.match(claim.deviceId, /^[0-9a-f-]{36}$/);
  assert.match(claim.deviceToken, /^hv1_[A-Za-z0-9_-]{43}$/);
  assert.equal(Object.isFrozen(claim), true);
  assert.equal(savedHash.includes(claim.deviceToken), false);
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
    verifyPurchase, query: async () => ({ rows: [{ account_id: null }] }) }),
  /hosted_enrollment_unavailable/);
});
