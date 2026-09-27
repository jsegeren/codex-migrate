const test = require('node:test');
const assert = require('node:assert/strict');
const { appendStagedPage } = require('../hosted/receipt_pages');
const { accountId, vaultId, freshScope } = require('./hosted-subscriber-fixture');

const reservationId = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const snapshotId = '11111111-1111-4111-8111-111111111111';
const metadata = { key: `metadata/${snapshotId}.json`, bytes: 20,
  sha256: 'a'.repeat(64) };
const chunk = index => {
  const id = index.toString(16).padStart(64, '0');
  return { key: `objects/${id.slice(0, 2)}/${id.slice(2)}.cvchunk`,
    bytes: 40, sha256: 'b'.repeat(64) };
};

test('one bounded page becomes an account-scoped immutable claim', async () => {
  let calls = 0;
  const result = await appendStagedPage({ scope: await freshScope(),
    reservationId, snapshotId, objects: [metadata, chunk(1)],
    query: async (sql, values) => {
      calls++;
      assert.match(sql, /append_receipt_page_current/);
      assert.deepEqual(values.slice(0, 4), [accountId, vaultId,
        reservationId, snapshotId]);
      assert.equal(values[5], 100_000_000);
      assert.deepEqual(JSON.parse(values[4]), [metadata, chunk(1)].map(item => ({
        ...item, key: `accounts/${accountId}/vaults/${vaultId}/${item.key}`,
      })));
      return { rows: [{ accepted: true }] };
    } });
  assert.deepEqual(result, { acceptedObjects: 2 });
  assert.equal(calls, 1);
});

test('malformed, oversized, or cross-snapshot pages fail before SQL', async () => {
  let calls = 0;
  const query = async () => { calls++; return { rows: [{ accepted: true }] }; };
  for (const objects of [[], [metadata, metadata], [metadata, { ...chunk(1), bytes: 0 }],
    [{ ...metadata, key: `metadata/22222222-2222-4222-8222-222222222222.json` }],
    [{ ...chunk(1), key: '../escape' }], Array.from({ length: 513 }, (_, i) => chunk(i))]) {
    await assert.rejects(appendStagedPage({ scope: await freshScope(),
      reservationId, snapshotId, objects, query }), /hosted_receipt_page_denied/);
  }
  assert.equal(calls, 0);
});

test('plain client scope, rejected quota, and database faults cannot acknowledge a page', async () => {
  await assert.rejects(appendStagedPage({ scope: { accountId, vaultId,
    allowanceBytes: 100_000_000 }, reservationId, snapshotId,
    objects: [metadata], query: async () => { throw Error('must not call'); } }),
  /hosted_receipt_page_denied/);
  for (const query of [
    async () => ({ rows: [{ accepted: false }] }),
    async () => { throw Error('private tenant detail'); },
  ]) {
    await assert.rejects(appendStagedPage({ scope: await freshScope(),
      reservationId, snapshotId, objects: [metadata], query }), error =>
      error.message === 'hosted_receipt_page_denied');
  }
});
