const test = require('node:test');
const assert = require('node:assert/strict');
const { randomBytes } = require('node:crypto');
const { makeHandler } = require('../api/hosted-recovery');
const { recoveryConfiguration } = require('../hosted/recovery_runtime');
const { verifyObjectCapability } = require('../hosted/object_capability');
const { mintSessionSecret } = require('./hosted-device-fixture');

const accountId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const vaultId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const snapshotId = '11111111-1111-4111-8111-111111111111';
const relativeKey = `metadata/${snapshotId}.json`;
const scopedKey = `accounts/${accountId}/vaults/${vaultId}/${relativeKey}`;
const secret = randomBytes(32);

function fixture(query) {
  const session = mintSessionSecret();
  const env = { HOSTED_MODE: 'sandbox', HOSTED_SANDBOX_RECOVERY_OPEN: 'yes' };
  let loads = 0;
  const handler = makeHandler(async received => {
    assert.equal(received, env);
    loads++;
    return { query: async (sql, values) => {
      if (sql.includes('FROM hosted.device_sessions')) {
        assert.deepEqual(values, [session.tokenHash, vaultId]);
        return { rows: [{ account_id: accountId, vault_id: vaultId }] };
      }
      return query(sql, values);
    }, workerOrigin: 'https://fixture.example', secret };
  }, env);
  const req = { method: 'POST', headers: {
    authorization: `Bearer ${session.token}`,
    'content-type': 'application/json',
  }, body: { action: 'latest', vaultId } };
  const send = async () => {
    const res = { headers: {}, setHeader(k, v) { this.headers[k] = v; },
      end(value) { this.body = JSON.parse(value); } };
    await handler(req, res);
    return res;
  };
  return { req, send, env, loads: () => loads };
}

test('closed and malformed requests never open the database', async () => {
  const f = fixture(async () => { throw Error('unexpected query'); });
  f.env.HOSTED_SANDBOX_RECOVERY_OPEN = 'no';
  assert.equal((await f.send()).statusCode, 404);
  assert.equal(f.loads(), 0);
  f.env.HOSTED_SANDBOX_RECOVERY_OPEN = 'yes';
  f.req.headers.authorization = 'Bearer forged';
  assert.equal((await f.send()).statusCode, 403);
  f.req.headers.authorization = `Bearer ${mintSessionSecret().token}`;
  f.req.body = { action: 'latest', vaultId, unexpected: true };
  assert.equal((await f.send()).statusCode, 400);
  f.req.body = { action: 'latest', vaultId };
  f.req.headers.origin = 'https://attacker.example';
  assert.equal((await f.send()).statusCode, 400);
  assert.equal(f.loads(), 0);
});

test('a revoked or unknown device cannot reach snapshot queries', async () => {
  const session = mintSessionSecret();
  let queries = 0;
  const handler = makeHandler(async () => ({ query: async () => {
    queries++;
    return { rows: [] };
  }, workerOrigin: 'https://fixture.example', secret }),
  { HOSTED_MODE: 'sandbox', HOSTED_SANDBOX_RECOVERY_OPEN: 'yes' });
  const req = { method: 'POST', headers: { authorization: `Bearer ${session.token}`,
    'content-type': 'application/json' }, body: { action: 'latest', vaultId } };
  const res = { setHeader() {}, end(value) { this.body = JSON.parse(value); } };
  await handler(req, res);
  assert.equal(res.statusCode, 403);
  assert.equal(queries, 1);
});

test('owned last-good and inventory responses contain no secret', async () => {
  const f = fixture(async (sql, values) => {
    if (sql.includes('FROM hosted.vaults AS v')) {
      assert.deepEqual(values, [accountId, vaultId]);
      return { rows: [{ last_good_snapshot_id: snapshotId,
        verified_object_count: 3, staged_bytes: '30' }] };
    }
    assert.match(sql, /hosted\.snapshot_objects/);
    assert.deepEqual(values, [accountId, vaultId, snapshotId, '']);
    return { rows: [relativeKey,
      `manifests/${snapshotId}.cvmanifest`,
      `refs/${snapshotId}.json`].sort().map(key => ({
      verified_object_count: 3, staged_bytes: '30',
      object_key: `accounts/${accountId}/vaults/${vaultId}/${key}`,
      bytes: '10', sha256: 'a'.repeat(64),
    })) };
  });
  const latest = await f.send();
  assert.equal(latest.statusCode, 200);
  assert.equal(latest.body.accountId, accountId);
  assert.equal(latest.body.workerOrigin, 'https://fixture.example');
  assert.deepEqual(latest.body.latest,
    { snapshotId, totalObjects: 3, totalBytes: 30 });
  f.req.body = { action: 'objects', vaultId, snapshotId };
  const page = await f.send();
  assert.equal(page.statusCode, 200);
  assert.equal(page.body.objects.length, 3);
  assert.equal(page.body.nextCursor, null);
  assert.equal(JSON.stringify(page.body).includes('hv1_'), false);
  assert.equal(page.headers['Cache-Control'], 'no-store');
});

test('GET grant is for only the published object, not a staged or foreign key', async () => {
  const f = fixture(async (sql, values) => {
    assert.match(sql, /hosted\.snapshot_objects/);
    assert.deepEqual(values, [accountId, vaultId, snapshotId, scopedKey]);
    return { rows: [{ bytes: '10', sha256: 'a'.repeat(64) }] };
  });
  f.req.body = { action: 'get', vaultId, snapshotId, relativeKey };
  const answer = await f.send();
  assert.equal(answer.statusCode, 200);
  assert.equal(answer.body.workerOrigin, 'https://fixture.example');
  assert.deepEqual(await verifyObjectCapability(answer.body.grant,
    'GET', scopedKey, secret),
  { key: scopedKey, bytes: 10, sha256: 'a'.repeat(64) });
  f.req.body.relativeKey = '../escape';
  assert.equal((await f.send()).statusCode, 503);
});

test('sandbox runtime refuses live and unexpected database or Worker origins', () => {
  const env = { HOSTED_MODE: 'sandbox', HOSTED_SANDBOX_RECOVERY_OPEN: 'yes',
    COMMERCE_DATABASE_URL: 'postgresql://fixture:fixture@ep-square-queen-av5us6bx.c-11.us-east-1.aws.neon.tech/neondb?sslmode=require',
    HOSTED_R2_ORIGIN: 'https://r2.example',
    HOSTED_CAPABILITY_SIGNING_KEY: secret.toString('base64url') };
  assert.equal(recoveryConfiguration(env).workerOrigin, 'https://r2.example');
  assert.equal(recoveryConfiguration({ ...env,
    COMMERCE_DATABASE_URL: env.COMMERCE_DATABASE_URL.replace(
      'ep-square-queen-av5us6bx.', 'ep-square-queen-av5us6bx-pooler.'),
  }).workerOrigin, 'https://r2.example');
  for (const changes of [
    { HOSTED_MODE: 'live' },
    { COMMERCE_DATABASE_URL: env.COMMERCE_DATABASE_URL.replace('ep-square-queen', 'ep-other') },
    { HOSTED_R2_ORIGIN: 'http://r2.example' },
    { HOSTED_R2_ORIGIN: 'https://user:pass@r2.example' },
    { HOSTED_CAPABILITY_SIGNING_KEY: 'invalid' },
  ]) {
    assert.throws(() => recoveryConfiguration({ ...env, ...changes }),
      /hosted_recovery_unavailable/);
  }
});
