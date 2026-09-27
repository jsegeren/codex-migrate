const test = require('node:test');
const assert = require('node:assert/strict');
const { publishStagedReceipt } = require('../hosted/publication');
const { validateReceipt } = require('../hosted/receipt');
const { mintSessionSecret, authorizeUploadScope } = require('../hosted/access');

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

async function publicationScope() {
  const { token } = mintSessionSecret();
  return authorizeUploadScope({ sessionToken: token, vaultId: scope.vaultId,
    query: async () => ({ rows: [{ account_id: scope.accountId,
      vault_id: scope.vaultId, purchase_session_id: 'cs_test_fixture',
      purchase_mode: 'sandbox' }] }),
    verifyPurchase: async () => ({ sessionId: 'cs_test_fixture',
      mode: 'sandbox' }),
    getEntitlement: async () => ({
      enrollment: { accountId: scope.accountId, subscriptionId: 'sub_fixture',
        customerId: 'cus_fixture', priceId: 'price_fixture' },
      subscription: { id: 'sub_fixture', customer: 'cus_fixture',
        livemode: false, status: 'active', collection_method: 'charge_automatically',
        pause_collection: null, items: { data: [{ quantity: 1, price: {
          id: 'price_fixture', livemode: false, type: 'recurring',
          currency: 'usd', unit_amount: 1000, billing_scheme: 'per_unit',
          recurring: { interval: 'month', interval_count: 1 },
        } }] } },
    }),
    live: false,
    priceCatalog: new Map([['price_fixture', { priceCents: 1000,
      allowanceBytes: 100_000_000_000 }]]),
  });
}

test('a receipt over the database object limit is rejected before verification', () => {
  const claim = receipt();
  claim.objects = Array(1_000_001);
  assert.throws(() => validateReceipt(claim, 1000), /hosted_receipt_invalid/);
});

test('publishes only the provider-verified frozen object list', async () => {
  const claim = receipt();
  const checked = [];
  const calls = [];
  const published = await publishStagedReceipt({ receipt: claim, maxReceiptBytes: 1000,
    scope: await publicationScope(), reservationId,
    verifyBatch: async batch => {
      checked.push(...batch.map(item => item.key));
      claim.objects[1].sha256 = 'b'.repeat(64);
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
    maxReceiptBytes: 1000, scope: await publicationScope(), reservationId,
    verifyBatch: async () => false,
    query: async () => { writes++; return { rows: [{ published: true }] }; },
  }), /hosted_receipt_invalid/);
  assert.equal(writes, 0);
});

test('missing reservation or database confirmation is not publication', async () => {
  let checks = 0;
  for (const invalid of [undefined, 'not-a-uuid']) {
    await assert.rejects(publishStagedReceipt({ receipt: receipt(),
      maxReceiptBytes: 1000, scope: await publicationScope(), reservationId: invalid,
      verifyBatch: async () => { checks++; return true; },
      query: async () => ({ rows: [{ published: true }] }),
    }), /hosted_publication_failed/);
  }
  assert.equal(checks, 0);
  await assert.rejects(publishStagedReceipt({ receipt: receipt(),
    maxReceiptBytes: 1000, scope: await publicationScope(), reservationId,
    verifyBatch: async () => true,
    query: async () => ({ rows: [{ published: false }] }),
  }), /hosted_publication_failed/);
});

test('database errors do not expose private publication details', async () => {
  await assert.rejects(publishStagedReceipt({ receipt: receipt(),
    maxReceiptBytes: 1000, scope: await publicationScope(), reservationId,
    verifyBatch: async () => true,
    query: async () => { throw new Error('private database endpoint and account'); },
  }), error => error.message === 'hosted_publication_failed');
});

test('a failed later batch never publishes a large receipt', async () => {
  const claim = receipt();
  claim.objects.splice(1, 1);
  for (let index = 0; index < 600; index++) {
    const digest = index.toString(16).padStart(64, '0');
    claim.objects.splice(claim.objects.length - 2, 0, {
      key: `objects/${digest.slice(0, 2)}/${digest.slice(2)}.cvchunk`,
      bytes: 10, sha256: 'a'.repeat(64),
    });
  }
  claim.remote_bytes_checked = claim.objects.reduce((sum, item) => sum + item.bytes, 0);
  let batches = 0;
  let writes = 0;
  await assert.rejects(publishStagedReceipt({ receipt: claim,
    maxReceiptBytes: claim.remote_bytes_checked, scope: await publicationScope(), reservationId,
    verifyBatch: async () => ++batches !== 2,
    query: async () => { writes++; return { rows: [{ published: true }] }; },
  }), /hosted_receipt_invalid/);
  assert.equal(batches, 2);
  assert.equal(writes, 0);
});
