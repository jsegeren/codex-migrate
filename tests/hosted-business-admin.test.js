const test = require('node:test');
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { beginBusinessAdminAccess, claimBusinessAdminAccess,
  resolveBusinessAdmin } = require('../hosted/business_admin');
const { businessAdminMail } = require('../hosted/business_admin_mail');

test('exact approved contact gets one code and a separate metadata session', async () => {
  const accountId = randomUUID();
  let emailed;
  let challengeDigest;
  let sessionDigest;
  const query = async (statement, values) => {
    if (statement.includes('issue_business_admin_challenge')) {
      assert.equal(values[0], accountId);
      challengeDigest = values[1];
      assert.match(challengeDigest, /^[0-9a-f]{64}$/);
      return { rows: [{ contact: 'admin@company.example' }] };
    }
    if (statement.includes('record_business_admin_challenge_delivery')) {
      assert.deepEqual(values, [challengeDigest, 'sent']);
      return { rows: [{ recorded: true }] };
    }
    if (statement.includes('claim_business_admin_session')) {
      assert.deepEqual(values.slice(0, 2), [accountId, challengeDigest]);
      sessionDigest = values[2];
      assert.match(sessionDigest, /^[0-9a-f]{64}$/);
      assert.notEqual(sessionDigest, challengeDigest);
      return { rows: [{ account_id: accountId }] };
    }
    if (statement.includes('business_admin_sessions')) {
      assert.match(statement, /revoked_at IS NULL/);
      assert.deepEqual(values, [sessionDigest]);
      return { rows: [{ account_id: accountId }] };
    }
    throw Error('unexpected SQL');
  };
  const begun = await beginBusinessAdminAccess({ accountId, query,
    sendChallenge: async message => { emailed = message; return 'accepted'; } });
  assert.deepEqual(begun, { status: 'sent' });
  assert.equal(emailed.to, 'admin@company.example');
  assert.equal(emailed.purpose, 'business-admin-sandbox');
  assert.match(emailed.code, /^hvae1_[A-Za-z0-9_-]{43}$/);
  assert.equal(challengeDigest.includes(emailed.code), false);
  assert.equal('code' in begun, false);
  assert.equal('contact' in begun, false);
  const claimed = await claimBusinessAdminAccess({ accountId,
    code: emailed.code, query });
  assert.match(claimed.sessionToken, /^hva1_[A-Za-z0-9_-]{43}$/);
  assert.equal(claimed.accountId, accountId);
  assert.equal(Object.isFrozen(claimed), true);
  assert.deepEqual(await resolveBusinessAdmin({
    sessionToken: claimed.sessionToken, query }), { accountId });
});

test('unknown, uncertain, malformed, and replayed proof fail closed', async () => {
  const accountId = randomUUID();
  let sends = 0;
  await assert.rejects(beginBusinessAdminAccess({ accountId,
    query: async () => ({ rows: [{ contact: null }] }),
    sendChallenge: async () => { sends++; return 'accepted'; } }),
  /business_admin_unavailable/);
  assert.equal(sends, 0);
  await assert.rejects(beginBusinessAdminAccess({ accountId,
    query: async (statement, values) => ({ rows: [
      statement.includes('issue_') ? { contact: 'admin@example.test' } :
        { recorded: values[1] === 'sent' }] }),
    sendChallenge: async () => 'uncertain' }),
  /business_admin_unavailable/);
  await assert.rejects(claimBusinessAdminAccess({ accountId,
    code: 'bad-code', query: async () => { throw Error('must not query'); } }),
  /business_admin_unavailable/);
  await assert.rejects(claimBusinessAdminAccess({ accountId,
    code: `hvae1_${'a'.repeat(43)}`,
    query: async () => ({ rows: [{ account_id: null }] }) }),
  /business_admin_unavailable/);
  await assert.rejects(resolveBusinessAdmin({ sessionToken: 'bad-token',
    query: async () => { throw Error('must not query'); } }),
  /business_admin_unavailable/);
});

test('business admin mail is sandbox-only and does not track', async () => {
  const env = { LAUNCH_FROM_EMAIL: 'from@example.test',
    COMMERCE_SANDBOX_EMAIL: 'admin@example.test', SENDGRID_API_KEY: 'fixture' };
  const message = { to: 'admin@example.test',
    code: `hvae1_${'a'.repeat(43)}`, purpose: 'business-admin-sandbox' };
  let sends = 0;
  const request = async (url, options) => {
    sends++;
    assert.equal(url, 'https://api.sendgrid.com/v3/mail/send');
    const body = JSON.parse(options.body);
    assert.equal(body.personalizations[0].to[0].email, message.to);
    assert.equal(body.tracking_settings.open_tracking.enable, false);
    assert.equal(body.tracking_settings.click_tracking.enable, false);
    assert.match(body.content[0].value, /cannot enroll devices/);
    return { status: 202 };
  };
  assert.equal(await businessAdminMail(message, env, request), 'accepted');
  assert.equal(await businessAdminMail({ ...message,
    to: 'someone-else@example.test' }, env, request), 'rejected');
  assert.equal(await businessAdminMail({ ...message,
    purpose: 'business-admin-live' }, env, request), 'rejected');
  assert.equal(sends, 1);
});
