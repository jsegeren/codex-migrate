const test = require('node:test');
const assert = require('node:assert/strict');
const { randomBytes } = require('node:crypto');
const { authorizeReadScope } = require('../hosted/access');
const { issuePublishedGet, issueLastGoodManifest } = require('../hosted/read_grant');
const { verifyObjectCapability } = require('../hosted/object_capability');
const { mintSessionSecret } = require('./hosted-device-fixture');

const accountId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const vaultId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const snapshotId = '11111111-1111-4111-8111-111111111111';
const relativeKey = `metadata/${snapshotId}.json`;
const scopedKey = `accounts/${accountId}/vaults/${vaultId}/${relativeKey}`;
const secret = randomBytes(32);

async function readScope() {
  const session = mintSessionSecret();
  return authorizeReadScope({ sessionToken: session.token, vaultId,
    query: async (sql, values) => {
      assert.match(sql, /sessions/);
      assert.match(sql, /revoked_at IS NULL/);
      assert.deepEqual(values, [session.tokenHash, vaultId]);
      return { rows: [{ account_id: accountId, vault_id: vaultId }] };
    } });
}

test('retained published data can be read with device auth after subscription lapse', async () => {
  const token = await issuePublishedGet({ scope: await readScope(), snapshotId,
    relativeKey, secret, query: async (sql, values) => {
      assert.match(sql, /hosted\.snapshot_objects/);
      assert.deepEqual(values, [accountId, vaultId, snapshotId, scopedKey]);
      return { rows: [{ bytes: '20', sha256: 'a'.repeat(64) }] };
    } });
  assert.deepEqual(await verifyObjectCapability(token, 'GET', scopedKey, secret),
    { key: scopedKey, bytes: 20, sha256: 'a'.repeat(64) });
  await assert.rejects(verifyObjectCapability(token, 'PUT', scopedKey, secret),
    /hosted_object_access_denied/);
  await assert.rejects(verifyObjectCapability(token, 'GET', scopedKey, secret,
    Date.now() + 31_000), /hosted_object_access_denied/);
});

test('staged, foreign, malformed, or absent objects never get read grants', async () => {
  let queries = 0;
  const query = async () => { queries++; return { rows: [] }; };
  for (const key of ['../escape', 'x'.repeat(300),
    `accounts/${accountId}/vaults/${vaultId}/${relativeKey}`]) {
    await assert.rejects(issuePublishedGet({ scope: await readScope(), snapshotId,
      relativeKey: key, secret, query }), /hosted_read_grant_denied/);
  }
  assert.equal(queries, 0);
  await assert.rejects(issuePublishedGet({ scope: await readScope(), snapshotId,
    relativeKey, secret, query }), /hosted_read_grant_denied/);
  assert.equal(queries, 1);
  await assert.rejects(issuePublishedGet({ scope: { accountId, vaultId },
    snapshotId, relativeKey, secret, query }), /hosted_read_grant_denied/);
  assert.equal(queries, 1);
});

test('revoked or foreign device sessions cannot create a read scope', async () => {
  const session = mintSessionSecret();
  await assert.rejects(authorizeReadScope({ sessionToken: session.token, vaultId,
    query: async () => ({ rows: [] }) }), /hosted_access_denied/);
  await assert.rejects(authorizeReadScope({ sessionToken: session.token, vaultId,
    query: async () => ({ rows: [{ account_id: accountId,
      vault_id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd' }] }) }),
  /hosted_access_denied/);
});

test('read scope is single-use, even if its object lookup fails', async () => {
  const scope = await readScope();
  let queries = 0;
  const query = async () => { queries++; return { rows: [] }; };
  await assert.rejects(issuePublishedGet({ scope, snapshotId,
    relativeKey, secret, query }), /hosted_read_grant_denied/);
  await assert.rejects(issuePublishedGet({ scope, snapshotId,
    relativeKey, secret, query }), /hosted_read_grant_denied/);
  assert.equal(queries, 1);
});

test('last-good manifest grant is limited to the current published pointer', async () => {
  const manifestKey = `accounts/${accountId}/vaults/${vaultId}/` +
    `manifests/${snapshotId}.cvmanifest`;
  const answer = await issueLastGoodManifest({ scope: await readScope(),
    snapshotId, secret, query: async (sql, values) => {
      assert.match(sql, /v\.last_good_snapshot_id = \$3::uuid/);
      assert.match(sql, /hosted\.snapshot_objects/);
      assert.deepEqual(values, [accountId, vaultId, snapshotId, manifestKey]);
      return { rows: [{ bytes: '2048', sha256: 'b'.repeat(64) }] };
    } });
  assert.equal(answer.bytes, 2048);
  assert.equal(answer.sha256, 'b'.repeat(64));
  assert.deepEqual(await verifyObjectCapability(answer.grant, 'GET', manifestKey,
    secret), { key: manifestKey, bytes: 2048, sha256: 'b'.repeat(64) });
  await assert.rejects(verifyObjectCapability(answer.grant, 'GET', scopedKey,
    secret), /hosted_object_access_denied/);
});

test('last-good manifest refuses missing, conflicting, or untrusted rows and scope', async () => {
  const cases = [[], [{ bytes: '0', sha256: 'b'.repeat(64) }],
    [{ bytes: '12', sha256: 'bad' }],
    [{ bytes: '12', sha256: 'b'.repeat(64) },
      { bytes: '12', sha256: 'b'.repeat(64) }]];
  for (const rows of cases) {
    await assert.rejects(issueLastGoodManifest({ scope: await readScope(),
      snapshotId, secret, query: async () => ({ rows }) }),
    /hosted_read_grant_denied/);
  }
  let queries = 0;
  const query = async () => { queries++; return { rows: [] }; };
  await assert.rejects(issueLastGoodManifest({ scope: { accountId, vaultId },
    snapshotId, secret, query }), /hosted_read_grant_denied/);
  await assert.rejects(issueLastGoodManifest({ scope: await readScope(),
    snapshotId: 'invalid', secret, query }), /hosted_read_grant_denied/);
  assert.equal(queries, 0);
});
