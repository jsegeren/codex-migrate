const test = require('node:test');
const assert = require('node:assert/strict');
const { publishStagedReceipt } = require('../hosted/publication');

const snapshotId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const reservationId = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
const scope = { accountId: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
  vaultId: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc' };
const prefix = `accounts/${scope.accountId}/vaults/${scope.vaultId}/`;
const keys = [`metadata/${snapshotId}.json`,
  `objects/ab/${'c'.repeat(62)}.cvchunk`,
  `manifests/${snapshotId}.cvmanifest`, `refs/${snapshotId}.json`];
const objects = keys.map(key => ({ key, bytes: 10, sha256: 'a'.repeat(64) }));
const receipt = () => ({ version: 1, snapshot_id: snapshotId,
  remote_bytes_checked: 40, objects: objects.map(item => ({ ...item })) });

test('publishes only the provider-verified frozen object list', async () => {
  const claim = receipt();
  const checked = [];
  const calls = [];
  const published = await publishStagedReceipt({ receipt: claim, maxReceiptBytes: 1000,
    scope, reservationId,
    verifyObject: async item => {
      checked.push(item.key);
      if (checked.length === 1) claim.objects[1].sha256 = 'b'.repeat(64);
      return true;
    },
    query: async (...args) => {
      calls.push(args);
      return { rows: [{ published: true }] };
    } });
  assert.deepEqual(checked, keys.map(key => prefix + key));
  assert.equal(calls.length, 1);
  assert.match(calls[0][0], /publish_verified_snapshot/);
  assert.deepEqual(calls[0][1].slice(0, 4), [scope.accountId, scope.vaultId,
    reservationId, snapshotId]);
  assert.deepEqual(JSON.parse(calls[0][1][4]), objects.map(item =>
    ({ ...item, key: prefix + item.key })));
  assert.deepEqual(published, { snapshotId, verifiedObjectCount: 4 });
});

test('a failed provider check never calls the database', async () => {
  let writes = 0;
  await assert.rejects(publishStagedReceipt({ receipt: receipt(),
    maxReceiptBytes: 1000, scope, reservationId,
    verifyObject: async () => false,
    query: async () => { writes++; return { rows: [{ published: true }] }; },
  }), /hosted_receipt_invalid/);
  assert.equal(writes, 0);
});

test('missing reservation or database confirmation is not publication', async () => {
  let checks = 0;
  for (const invalid of [undefined, 'not-a-uuid']) {
    await assert.rejects(publishStagedReceipt({ receipt: receipt(),
      maxReceiptBytes: 1000, scope, reservationId: invalid,
      verifyObject: async () => { checks++; return true; },
      query: async () => ({ rows: [{ published: true }] }),
    }), /hosted_publication_failed/);
  }
  assert.equal(checks, 0);
  await assert.rejects(publishStagedReceipt({ receipt: receipt(),
    maxReceiptBytes: 1000, scope, reservationId,
    verifyObject: async () => true,
    query: async () => ({ rows: [{ published: false }] }),
  }), /hosted_publication_failed/);
});
