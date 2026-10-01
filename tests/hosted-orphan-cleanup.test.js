const test = require('node:test');
const assert = require('node:assert/strict');
const { createHash, randomBytes } = require('node:crypto');
const { createOperatorCleanupDeleter, createOperatorCleanupReleaser } =
  require('../hosted/orphan_cleanup');

const accountId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const vaultId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const reservationId = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const objectId = 'd'.repeat(64);
const key = `accounts/${accountId}/vaults/${vaultId}/objects/dd/${objectId.slice(2)}.cvchunk`;
const bytes = Buffer.from('synthetic encrypted orphan');
const sha256 = createHash('sha256').update(bytes).digest('hex');
const secret = randomBytes(32);
const origin = 'https://backup.example.test';
const args = { accountId, vaultId, reservationId, key };

function fixture({ provider = 'present', grantTime = Date.now(),
  absenceAllowed = true } = {}) {
  const calls = [];
  const objects = new Map();
  if (provider !== 'absent') objects.set(key, bytes);
  const bucket = {
    async head(objectKey) {
      calls.push('head');
      const data = objects.get(objectKey);
      return data && { key: objectKey, size: data.length,
        checksums: { sha256: Uint8Array.from(Buffer.from(sha256, 'hex')).buffer } };
    },
    async delete(objectKey) {
      calls.push('delete');
      if (provider !== 'stuck') objects.delete(objectKey);
    },
  };
  const query = async (sql, params) => {
    assert.deepEqual(params.slice(0, 4),
      [accountId, vaultId, reservationId, key]);
    if (sql.includes('issue_cleanup_delete_grant')) {
      calls.push('grant');
      return { rows: [{ object_bytes: String(bytes.length),
        object_sha256: sha256, issued_at: new Date(grantTime) }] };
    }
    assert.match(sql, /record_cleanup_object_absent/);
    assert.deepEqual(params.slice(4), [bytes.length, sha256]);
    calls.push('record');
    return { rows: [{ allowed: absenceAllowed }] };
  };
  const fetchImpl = async (url, options) => {
    calls.push('fetch');
    assert.equal(url, `${origin}/v1/object/${key}`);
    assert.equal(options.method, 'DELETE');
    assert.equal(options.redirect, 'error');
    assert.equal(options.cache, 'no-store');
    const { handleObjectRequest } = await import('../hosted/r2_object_worker.mjs');
    return handleObjectRequest(new Request(url, options), bucket, secret);
  };
  return { calls, objects, query, fetchImpl };
}

test('operator records absence only after a scoped Worker deletion and HEAD', async () => {
  const f = fixture();
  const deleteOrphan = createOperatorCleanupDeleter({ origin, secret,
    query: f.query, fetchImpl: f.fetchImpl });
  assert.deepEqual(await deleteOrphan(args), { objectAbsent: true });
  assert.equal(f.objects.has(key), false);
  assert.deepEqual(f.calls, ['grant', 'fetch', 'head', 'delete', 'head', 'record']);
});

test('already-absent object is idempotent and still requires a HEAD', async () => {
  const f = fixture({ provider: 'absent' });
  const deleteOrphan = createOperatorCleanupDeleter({ origin, secret,
    query: f.query, fetchImpl: f.fetchImpl });
  assert.deepEqual(await deleteOrphan(args), { objectAbsent: true });
  assert.deepEqual(f.calls, ['grant', 'fetch', 'head', 'record']);
});

test('provider conflict or missing absence record never reports success', async () => {
  for (const options of [{ provider: 'stuck' }, { absenceAllowed: false }]) {
    const f = fixture(options);
    const deleteOrphan = createOperatorCleanupDeleter({ origin, secret,
      query: f.query, fetchImpl: f.fetchImpl });
    await assert.rejects(deleteOrphan(args), /hosted_orphan_cleanup_failed/);
    if (options.provider === 'stuck') assert.equal(f.calls.includes('record'), false);
  }
});

test('a lost absence-record response retries safely after deletion', async () => {
  const f = fixture();
  let firstRecord = true;
  const query = async (sql, params) => {
    if (sql.includes('record_cleanup_object_absent') && firstRecord) {
      firstRecord = false;
      throw Error('synthetic response lost after provider delete');
    }
    return f.query(sql, params);
  };
  const deleteOrphan = createOperatorCleanupDeleter({ origin, secret,
    query, fetchImpl: f.fetchImpl });
  await assert.rejects(deleteOrphan(args), /hosted_orphan_cleanup_failed/);
  assert.equal(f.objects.has(key), false);
  assert.equal(f.calls.includes('record'), false);
  assert.deepEqual(await deleteOrphan(args), { objectAbsent: true });
  assert.equal(f.calls.filter(call => call === 'delete').length, 1);
  assert.equal(f.calls.filter(call => call === 'record').length, 1);
});

test('stale grant, wrong scope, and non-TLS origin fail closed', async () => {
  const f = fixture({ grantTime: Date.now() - 20_000 });
  const deleteOrphan = createOperatorCleanupDeleter({ origin, secret,
    query: f.query, fetchImpl: f.fetchImpl });
  await assert.rejects(deleteOrphan(args), /hosted_orphan_cleanup_failed/);
  assert.deepEqual(f.calls, ['grant']);
  await assert.rejects(deleteOrphan({ ...args, accountId: vaultId }),
    /hosted_orphan_cleanup_failed/);
  assert.deepEqual(f.calls, ['grant']);
  assert.throws(() => createOperatorCleanupDeleter({
    origin: 'http://backup.example.test', secret, query: f.query,
    fetchImpl: f.fetchImpl,
  }), /hosted_orphan_cleanup_failed/);
});

test('operator quota release accepts only a positive database completion', async () => {
  const seen = [];
  const release = createOperatorCleanupReleaser({ query: async (sql, params) => {
    seen.push([sql, params]);
    return { rows: [{ allowed: seen.length === 2 }] };
  } });
  const scope = { accountId, vaultId, reservationId };
  await assert.rejects(release(scope), /hosted_orphan_cleanup_failed/);
  assert.deepEqual(await release(scope), { quotaReleased: true });
  assert.equal(seen.length, 2);
  assert.match(seen[0][0], /release_cleaned_upload_reservation/);
  assert.deepEqual(seen[0][1], [accountId, vaultId, reservationId]);
  await assert.rejects(release({ ...scope, vaultId: 'bad' }),
    /hosted_orphan_cleanup_failed/);
  assert.equal(seen.length, 2);
});
