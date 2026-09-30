const test = require('node:test');
const assert = require('node:assert/strict');
const { randomBytes } = require('node:crypto');
const { makeHandler: uploadHandler } = require('../api/hosted-upload');
const { makeHandler: recoveryHandler } = require('../api/hosted-recovery');
const { makeHandler: publishHandler } = require('../api/hosted-publish');
const { makeHandler: verifyHandler } = require('../api/hosted-verify-step');
const { makeHandler: pageHandler } = require('../api/hosted-receipt-page');
const { makeHandler: checkpointHandler } =
  require('../api/hosted-publish-checkpointed');
const { makeHandler: chunksHandler } =
  require('../api/hosted-published-chunks');
const { businessDeviceTokenHash } = require('../hosted/business_worker');

const accountId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const vaultId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const reservationId = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const snapshotId = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
const token = `hvb1_${'a'.repeat(43)}`;
const secret = randomBytes(32);
const item = { key: `objects/aa/${'a'.repeat(62)}.cvchunk`,
  bytes: 10, sha256: 'b'.repeat(64) };

function response() {
  return { headers: {}, setHeader(key, value) { this.headers[key] = value; },
    end(value) { this.body = JSON.parse(value); } };
}

function fixture() {
  const env = { HOSTED_MODE: 'sandbox', HOSTED_SANDBOX_UPLOAD_OPEN: 'yes',
    HOSTED_SANDBOX_PUBLISH_OPEN: 'yes',
    HOSTED_SANDBOX_VERIFY_OPEN: 'yes',
    HOSTED_SANDBOX_CHECKPOINT_PUBLISH_OPEN: 'yes',
    HOSTED_SANDBOX_RECOVERY_OPEN: 'yes',
    HOSTED_BUSINESS_BACKUP_SANDBOX_OPEN: 'no' };
  let loads = 0;
  let businessReads = 0;
  let purchaseReads = 0;
  let active = true;
  const query = async (sql, values) => {
    if (sql.includes('business_device_sessions')) {
      assert.deepEqual(values, [businessDeviceTokenHash(token), vaultId]);
      businessReads++;
      if (!active) return { rows: [] };
      return { rows: [{ account_id: accountId, vault_id: vaultId,
        allowance_bytes: '1000000000' }] };
    }
    if (sql.includes('purchase_enrollments') ||
        sql.includes('FROM hosted.device_sessions')) {
      purchaseReads++;
      throw Error('business device reached individual authority');
    }
    if (sql.includes('reserve_upload_idempotent_current')) {
      assert.deepEqual(values.slice(0, 4), [accountId, vaultId,
        reservationId, 20]);
      assert.equal(values[5], 1_000_000_000);
      return { rows: [{ allowed: true, base_snapshot_id: null,
        expires_at: values[4] }] };
    }
    if (sql.includes('SELECT 1 AS active FROM hosted.upload_reservations')) {
      return { rows: [{ active: 1 }] };
    }
    if (sql.includes('reserve_object_grant_elastic_current')) {
      assert.equal(values[0], accountId);
      assert.equal(values[1], vaultId);
      assert.equal(values[6], 1_000_000_000);
      return { rows: [{ allowed: true }] };
    }
    if (sql.includes('append_receipt_page_declared_current')) {
      assert.equal(values[0], accountId);
      assert.equal(values[7], 1_000_000_000);
      return { rows: [{ accepted: true }] };
    }
    if (sql.includes('published_chunk_candidates')) {
      assert.deepEqual(values.slice(0, 2), [accountId, vaultId]);
      return { rows: [] };
    }
    if (sql.includes('FROM hosted.accounts WHERE account_id')) {
      throw Error('worker reached company-wide storage totals');
    }
    if (sql.includes('FROM hosted.vaults AS v')) {
      assert.deepEqual(values, [accountId, vaultId]);
      return { rows: [{ last_good_snapshot_id: null }] };
    }
    throw Error('unexpected SQL');
  };
  const load = async (_env, credential) => {
    assert.equal(_env, env);
    if (credential) assert.equal(credential.kind, 'business');
    loads++;
    return { query, live: false, workerOrigin: 'https://r2.fixture.test',
      secret };
  };
  const headers = { authorization: `Bearer ${token}`,
    'content-type': 'application/json' };
  const send = async (handler, body, extraHeaders = {}) => {
    const res = response();
    await handler({ method: 'POST', headers: { ...headers, ...extraHeaders },
      body }, res);
    return res;
  };
  return { env, load, send, loads: () => loads,
    businessReads: () => businessReads, purchaseReads: () => purchaseReads,
    setActive: value => { active = value; } };
}

test('business backup route is closed by default before opening runtime', async () => {
  const f = fixture();
  const upload = uploadHandler(f.load, f.env);
  const denied = await f.send(upload, { action: 'reserve', vaultId,
    reservationId, bytes: 20 });
  assert.equal(denied.statusCode, 403);
  assert.equal(f.loads(), 0);
  f.env.HOSTED_BUSINESS_BACKUP_SANDBOX_OPEN = 'yes';
  f.env.HOSTED_MODE = 'live';
  assert.equal((await f.send(upload, { action: 'reserve', vaultId,
    reservationId, bytes: 20 })).statusCode, 404);
  assert.equal(f.loads(), 0);
});

test('an entitled business device can reserve and receive a bound object grant', async () => {
  const f = fixture();
  f.env.HOSTED_BUSINESS_BACKUP_SANDBOX_OPEN = 'yes';
  const upload = uploadHandler(f.load, f.env);
  const reserved = await f.send(upload, { action: 'reserve', vaultId,
    reservationId, bytes: 20 });
  assert.equal(reserved.statusCode, 200);
  assert.equal(reserved.body.reservationId, reservationId);
  const leased = await f.send(upload, { action: 'lease', vaultId,
    reservationId });
  assert.equal(leased.statusCode, 200);
  const granted = await f.send(upload, { action: 'put', vaultId,
    reservationId, item }, { 'x-hosted-upload-lease': leased.body.lease });
  assert.equal(granted.statusCode, 200);
  assert.equal(typeof granted.body.grant, 'string');
  assert.equal(granted.body.workerOrigin, 'https://r2.fixture.test');
  assert.equal(f.purchaseReads(), 0);
  assert.ok(f.businessReads() >= 3);
  f.setActive(false);
  const revoked = await f.send(upload, { action: 'put', vaultId,
    reservationId, item }, { 'x-hosted-upload-lease': leased.body.lease });
  assert.equal(revoked.statusCode, 403);
});

test('business self-read and publication still require the scoped device', async () => {
  const f = fixture();
  f.env.HOSTED_BUSINESS_BACKUP_SANDBOX_OPEN = 'yes';
  const recovery = recoveryHandler(f.load, f.env);
  const deniedUsage = await f.send(recovery, { action: 'usage', vaultId });
  assert.equal(deniedUsage.statusCode, 403);
  const latest = await f.send(recovery, { action: 'latest', vaultId });
  assert.equal(latest.statusCode, 200);
  assert.deepEqual(latest.body, { accountId,
    workerOrigin: 'https://r2.fixture.test', latest: null });
  const publish = publishHandler(f.load, f.env,
    () => async () => true,
    async ({ scope }) => {
      assert.equal(scope.accountId, accountId);
      assert.equal(scope.vaultId, vaultId);
      return { snapshotId, verifiedObjectCount: 3 };
    });
  const published = await f.send(publish, { action: 'publish', vaultId,
    reservationId, snapshotId });
  assert.equal(published.statusCode, 200);
  f.setActive(false);
  assert.equal((await f.send(recovery, { action: 'latest', vaultId })).statusCode,
    403);
  assert.equal((await f.send(publish, { action: 'publish', vaultId,
    reservationId, snapshotId })).statusCode, 403);
  assert.equal(f.purchaseReads(), 0);
});

test('every staged publication route uses the separate business entitlement', async () => {
  const f = fixture();
  f.env.HOSTED_BUSINESS_BACKUP_SANDBOX_OPEN = 'yes';
  const chunks = chunksHandler(f.load, f.env);
  const reused = await f.send(chunks, { vaultId, ids: ['a'.repeat(64)] });
  assert.equal(reused.statusCode, 200);
  assert.deepEqual(reused.body, { objects: [] });

  const page = pageHandler(f.load, f.env);
  const admitted = await f.send(page, { action: 'page', vaultId,
    reservationId, snapshotId, objects: [item], expectedCount: 3,
    expectedBytes: 30 });
  assert.equal(admitted.statusCode, 200);
  assert.deepEqual(admitted.body, { acceptedObjects: 1 });

  const verify = verifyHandler(f.load, f.env,
    () => async () => true,
    async ({ scope }) => {
      assert.equal(scope.accountId, accountId);
      return { verifiedObjects: 1 };
    });
  const checked = await f.send(verify, { action: 'verify_next', vaultId,
    reservationId, snapshotId });
  assert.equal(checked.statusCode, 200);
  assert.deepEqual(checked.body, { verifiedObjects: 1 });

  const checkpoint = checkpointHandler(f.load, f.env,
    async ({ scope }) => {
      assert.equal(scope.accountId, accountId);
      return { snapshotId, verifiedObjectCount: 3 };
    });
  const published = await f.send(checkpoint,
    { action: 'publish_checkpointed', vaultId, reservationId,
      snapshotId, sourceCoverage: 'complete' });
  assert.equal(published.statusCode, 200);
  assert.equal(f.purchaseReads(), 0);
  f.setActive(false);
  assert.equal((await f.send(chunks,
    { vaultId, ids: ['a'.repeat(64)] })).statusCode, 403);
  assert.equal((await f.send(page, { action: 'page', vaultId,
    reservationId, snapshotId, objects: [item], expectedCount: 3,
    expectedBytes: 30 })).statusCode, 403);
});
