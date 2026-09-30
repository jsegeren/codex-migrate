const test = require('node:test');
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { makeHandler } = require('../api/hosted-business-health');
const { listBusinessHealth } = require('../hosted/business_health');
const { businessDeviceTokenHash } = require('../hosted/business_worker');
const { sessionHash } = require('../hosted/business_admin');

function response() {
  return { headers: {}, setHeader(key, value) { this.headers[key] = value; },
    end(value) { this.body = JSON.parse(value); } };
}

function fixture() {
  const accountId = randomUUID();
  const seatId = randomUUID();
  const vaultId = randomUUID();
  const deviceId = randomUUID();
  const snapshotId = randomUUID();
  const worker = `hvb1_${'a'.repeat(43)}`;
  const admin = `hva1_${'b'.repeat(43)}`;
  const env = { HOSTED_MODE: 'sandbox',
    HOSTED_BUSINESS_HEALTH_SANDBOX_OPEN: 'yes' };
  let calls = 0;
  const handler = makeHandler(async received => {
    assert.equal(received, env);
    calls++;
    return { query: async (sql, values) => {
      if (sql.includes('record_business_backup_check')) {
        assert.deepEqual(values, [businessDeviceTokenHash(worker), deviceId,
          'unchanged', snapshotId]);
        return { rows: [{ account_id: accountId, seat_id: seatId,
          vault_id: vaultId, checked_at: '2026-09-30T18:00:00Z' }] };
      }
      assert.match(sql, /business_admin_sessions/);
      assert.deepEqual(values, [sessionHash(admin)]);
      return { rows: [{ seat_id: seatId, vault_id: vaultId,
        revoked_at: null,
        reported_state: 'unchanged', reported_snapshot_id: snapshotId,
        checked_at: '2026-09-01T18:00:00Z',
        last_good_snapshot_id: snapshotId,
        published_at: '2026-09-30T17:00:00Z',
        source_coverage: 'complete' }] };
    } };
  }, env);
  const req = { method: 'POST', headers: {
    'content-type': 'application/json',
    origin: 'https://codexbackup.segeren.com',
    authorization: `Bearer ${worker}`,
  }, body: { action: 'report', deviceId,
    reportedState: 'unchanged', snapshotId } };
  return { env, req, worker, admin, accountId, seatId, vaultId,
    snapshotId, deviceId, calls: () => calls,
    send: async () => { const res = response(); await handler(req, res);
      return res; } };
}

test('health route is dark and rejects wrong authority before database load', async () => {
  const f = fixture();
  f.env.HOSTED_BUSINESS_HEALTH_SANDBOX_OPEN = 'no';
  assert.equal((await f.send()).statusCode, 404);
  f.env.HOSTED_BUSINESS_HEALTH_SANDBOX_OPEN = 'yes';
  f.env.HOSTED_MODE = 'live';
  assert.equal((await f.send()).statusCode, 404);
  f.env.HOSTED_MODE = 'sandbox';
  f.req.headers.origin = 'https://attacker.example';
  assert.equal((await f.send()).statusCode, 400);
  f.req.headers.origin = 'https://codexbackup.segeren.com';
  f.req.headers.authorization = `Bearer ${f.admin}`;
  assert.equal((await f.send()).statusCode, 403);
  f.req.body = { action: 'list' };
  f.req.headers.authorization = `Bearer ${f.worker}`;
  assert.equal((await f.send()).statusCode, 403);
  assert.equal(f.calls(), 0);
});

test('worker check-in records server time but not a recovery claim', async () => {
  const f = fixture();
  const res = await f.send();
  assert.equal(res.statusCode, 200);
  assert.deepEqual(res.body, { accountId: f.accountId,
    seatId: f.seatId, vaultId: f.vaultId,
    checkedAt: '2026-09-30T18:00:00Z' });
  assert.equal(res.headers['Cache-Control'], 'no-store');
  assert.equal(JSON.stringify(res.body).includes(f.worker), false);
});

test('administrator sees metadata only; missing checks need attention', async () => {
  const f = fixture();
  f.req.body = { action: 'list' };
  f.req.headers.authorization = `Bearer ${f.admin}`;
  const res = await f.send();
  assert.equal(res.statusCode, 200);
  assert.equal(res.body.seats.length, 1);
  assert.equal(res.body.seats[0].seatId, f.seatId);
  assert.equal(res.body.seats[0].needsAttention, true);
  assert.equal(res.body.seats[0].companyRecoveryVerified, false);
  assert.equal(JSON.stringify(res.body).includes('worker@example.test'), false);
});

test('recent check is distinct from recovery proof and source completeness', async () => {
  const f = fixture();
  const row = { seat_id: f.seatId, vault_id: f.vaultId,
    revoked_at: null,
    reported_state: 'verified', reported_snapshot_id: f.snapshotId,
    checked_at: '2026-09-30T18:00:00Z',
    last_good_snapshot_id: f.snapshotId,
    published_at: '2026-09-30T17:00:00Z',
    source_coverage: 'complete' };
  const query = async () => ({ rows: [row] });
  const now = new Date('2026-09-30T18:30:00Z');
  const healthy = await listBusinessHealth({ adminToken: f.admin,
    query, now });
  assert.equal(healthy.seats[0].needsAttention, false);
  assert.equal(healthy.seats[0].companyRecoveryVerified, false);
  row.source_coverage = 'needs_attention';
  const partial = await listBusinessHealth({ adminToken: f.admin,
    query, now });
  assert.equal(partial.seats[0].needsAttention, true);
  row.source_coverage = 'complete';
  row.reported_snapshot_id = randomUUID();
  const mismatch = await listBusinessHealth({ adminToken: f.admin,
    query, now });
  assert.equal(mismatch.seats[0].needsAttention, true);
  await assert.rejects(listBusinessHealth({ adminToken: f.admin,
    query: async () => ({ rows: [] }), now }));
});
