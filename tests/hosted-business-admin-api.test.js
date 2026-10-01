const test = require('node:test');
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { makeHandler, businessAdminRuntime } = require('../api/hosted-business-admin');

function response() {
  return { headers: {}, setHeader(key, value) { this.headers[key] = value; },
    end(value) { this.body = JSON.parse(value); } };
}

function fixture() {
  const accountId = randomUUID();
  const env = { HOSTED_MODE: 'sandbox',
    HOSTED_BUSINESS_ADMIN_SANDBOX_OPEN: 'yes' };
  let loads = 0;
  let mailed;
  let codeHash;
  let tokenHash;
  const handler = makeHandler(async received => {
    assert.equal(received, env);
    loads++;
    return { query: async (sql, values) => {
      if (sql.includes('issue_business_admin_challenge')) {
        assert.equal(values[0], accountId);
        codeHash = values[1];
        return { rows: [{ contact: 'admin@example.test' }] };
      }
      if (sql.includes('record_business_admin_challenge_delivery')) {
        assert.deepEqual(values, [codeHash, 'sent']);
        return { rows: [{ recorded: true }] };
      }
      if (sql.includes('claim_business_admin_session')) {
        assert.deepEqual(values.slice(0, 2), [accountId, codeHash]);
        tokenHash = values[2];
        return { rows: [{ account_id: accountId }] };
      }
      if (sql.includes('approve_business_seat')) {
        assert.equal(values[0], tokenHash);
        assert.equal(values[2], 'worker@example.test');
        return { rows: [{ seat_id: values[1] }] };
      }
      assert.match(sql, /business_admin_sessions/);
      assert.deepEqual(values, [tokenHash]);
      return { rows: [{ account_id: accountId }] };
    }, sendChallenge: async value => { mailed = value; return 'accepted'; } };
  }, env);
  const req = { method: 'POST', headers: {
    'content-type': 'application/json',
    origin: 'https://codexbackup.segeren.com',
  }, body: { action: 'begin', accountId } };
  return { env, req, accountId, loads: () => loads, mailed: () => mailed,
    send: async () => { const res = response(); await handler(req, res); return res; } };
}

test('closed, live, malformed, and unauthenticated requests do no work', async () => {
  const f = fixture();
  f.env.HOSTED_BUSINESS_ADMIN_SANDBOX_OPEN = 'no';
  assert.equal((await f.send()).statusCode, 404);
  f.env.HOSTED_BUSINESS_ADMIN_SANDBOX_OPEN = 'yes';
  f.env.HOSTED_MODE = 'live';
  assert.equal((await f.send()).statusCode, 404);
  f.env.HOSTED_MODE = 'sandbox';
  f.req.headers.origin = 'https://attacker.example';
  assert.equal((await f.send()).statusCode, 400);
  f.req.headers.origin = 'https://codexbackup.segeren.com';
  f.req.body.extra = 'untrusted';
  assert.equal((await f.send()).statusCode, 400);
  delete f.req.body.extra;
  f.req.body = { action: 'resolve' };
  assert.equal((await f.send()).statusCode, 403);
  assert.equal(f.loads(), 0);
});

test('sandbox admin proof returns only a short-lived bearer after code claim', async () => {
  const f = fixture();
  const begin = await f.send();
  assert.equal(begin.statusCode, 200);
  assert.deepEqual(begin.body, { status: 'sent' });
  assert.equal(begin.headers['Cache-Control'], 'no-store');
  assert.equal(f.mailed().to, 'admin@example.test');
  assert.equal(f.mailed().purpose, 'business-admin-sandbox');
  assert.equal(JSON.stringify(begin.body).includes(f.mailed().code), false);

  f.req.body = { action: 'claim', accountId: f.accountId,
    code: f.mailed().code };
  const claim = await f.send();
  assert.equal(claim.statusCode, 200);
  assert.equal(claim.body.accountId, f.accountId);
  assert.match(claim.body.sessionToken, /^hva1_[A-Za-z0-9_-]{43}$/);
  assert.equal(claim.headers['Cache-Control'], 'no-store');

  f.req.body = { action: 'resolve' };
  f.req.headers.authorization = `Bearer ${claim.body.sessionToken}`;
  const resolved = await f.send();
  assert.equal(resolved.statusCode, 200);
  assert.deepEqual(resolved.body, { accountId: f.accountId });

  const seatId = randomUUID();
  f.req.body = { action: 'approve-seat', seatId,
    approvalReference: randomUUID(), workerEmail: 'worker@example.test' };
  const approved = await f.send();
  assert.equal(approved.statusCode, 200);
  assert.deepEqual(approved.body, { seatId });
  f.req.headers.authorization = 'Bearer invalid';
  assert.equal((await f.send()).statusCode, 403);
});

test('database or email failure does not expose internal details', async () => {
  const f = fixture();
  const handler = makeHandler(async () => { throw Error('private SQL'); }, f.env);
  const res = response();
  await handler(f.req, res);
  assert.equal(res.statusCode, 503);
  assert.deepEqual(res.body, { error: 'temporarily_unavailable' });
  assert.equal(JSON.stringify(res.body).includes('private SQL'), false);
});

test('runtime refuses a non-sandbox database configuration', async () => {
  await assert.rejects(businessAdminRuntime({
    HOSTED_MODE: 'sandbox', HOSTED_BUSINESS_ADMIN_SANDBOX_OPEN: 'yes',
  }));
});
