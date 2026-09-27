const test = require('node:test');
const assert = require('node:assert/strict');
const { authorizeReadScope } = require('../hosted/access');
const { getLastGoodSnapshot, listPublishedObjects } = require('../hosted/read_inventory');
const { mintSessionSecret } = require('./hosted-device-fixture');

const accountId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const vaultId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const snapshotId = '11111111-1111-4111-8111-111111111111';
const prefix = `accounts/${accountId}/vaults/${vaultId}/`;

async function scope() {
  const session = mintSessionSecret();
  return authorizeReadScope({ sessionToken: session.token, vaultId,
    query: async () => ({ rows: [{ account_id: accountId, vault_id: vaultId }] }) });
}

function row(index, count = 300) {
  const digest = index.toString(16).padStart(64, '0');
  return { verified_object_count: count, staged_bytes: count * 10,
    object_key: `${prefix}objects/${digest.slice(0, 2)}/${digest.slice(2)}.cvchunk`,
    bytes: '10', sha256: digest };
}

test('last-good discovery comes only from the owned Vault pointer', async () => {
  const latest = await getLastGoodSnapshot({ scope: await scope(),
    query: async (sql, values) => {
      assert.match(sql, /v\.last_good_snapshot_id/);
      assert.deepEqual(values, [accountId, vaultId]);
      return { rows: [{ last_good_snapshot_id: snapshotId,
        verified_object_count: 300, staged_bytes: '3000' }] };
    } });
  assert.deepEqual(latest, { snapshotId, totalObjects: 300, totalBytes: 3000 });
  await assert.rejects(getLastGoodSnapshot({ scope: { accountId, vaultId },
    query: async () => ({ rows: [] }) }), /hosted_inventory_denied/);
  await assert.rejects(getLastGoodSnapshot({ scope: await scope(),
    query: async () => ({ rows: [] }) }), /hosted_inventory_denied/);
  assert.equal(await getLastGoodSnapshot({ scope: await scope(),
    query: async () => ({ rows: [{ last_good_snapshot_id: null,
      verified_object_count: null, staged_bytes: null }] }) }), null);
});

test('published inventory pages stay bounded, ordered, and scope-owned', async () => {
  const first = await listPublishedObjects({ scope: await scope(), snapshotId,
    query: async (sql, values) => {
      assert.match(sql, /hosted\.snapshots/);
      assert.match(sql, /LIMIT 257/);
      assert.deepEqual(values, [accountId, vaultId, snapshotId, '']);
      return { rows: Array.from({ length: 257 }, (_, index) => row(index)) };
    } });
  assert.equal(first.objects.length, 256);
  assert.equal(first.totalObjects, 300);
  assert.equal(first.totalBytes, 3000);
  assert.equal(first.nextCursor, row(255).object_key);
  const second = await listPublishedObjects({ scope: await scope(), snapshotId,
    afterKey: first.nextCursor, query: async (_sql, values) => {
      assert.equal(values[3], first.nextCursor);
      return { rows: Array.from({ length: 44 }, (_, index) => row(index + 256)) };
    } });
  assert.equal(second.objects.length, 44);
  assert.equal(second.nextCursor, null);
});

test('unpublished, foreign, malformed, or fabricated inventory is denied', async () => {
  let calls = 0;
  const missing = async () => { calls++; return { rows: [] }; };
  await assert.rejects(listPublishedObjects({ scope: await scope(), snapshotId,
    query: missing }), /hosted_inventory_denied/);
  await assert.rejects(listPublishedObjects({ scope: await scope(), snapshotId,
    afterKey: `accounts/${accountId}/vaults/cccccccc-cccc-4ccc-8ccc-cccccccccccc/` +
      'objects/aa/' + 'a'.repeat(62) + '.cvchunk', query: missing }),
  /hosted_inventory_denied/);
  assert.equal(calls, 1);
  for (const rows of [
    [row(1), row(0)],
    [{ ...row(0), sha256: 'invalid' }],
    [{ ...row(0), staged_bytes: '0' }],
    Array.from({ length: 258 }, (_, index) => row(index)),
  ]) {
    await assert.rejects(listPublishedObjects({ scope: await scope(), snapshotId,
      query: async () => ({ rows }) }), /hosted_inventory_denied/);
  }
});
