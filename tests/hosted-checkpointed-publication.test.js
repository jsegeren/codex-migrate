const test = require('node:test');
const assert = require('node:assert/strict');
const { publishCheckpointed } = require('../hosted/checkpointed_publication');
const { accountId, vaultId, freshScope } = require('./hosted-subscriber-fixture');

const reservationId = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const snapshotId = '11111111-1111-4111-8111-111111111111';

test('only database-confirmed publication produces a protection receipt', async () => {
  const statements = [];
  const result = await publishCheckpointed({ scope: await freshScope(),
    reservationId, snapshotId, query: async (sql, values) => {
      statements.push(sql);
      assert.deepEqual(values.slice(0, 4), [accountId, vaultId,
        reservationId, snapshotId]);
      if (statements.length === 1) {
        assert.match(sql, /publish_checkpointed_staged_current/);
        return { rows: [{ published: true }] };
      }
      assert.match(sql, /FROM hosted.snapshots/);
      return { rows: [{ verified_object_count: 21910 }] };
    } });
  assert.deepEqual(result, { snapshotId, verifiedObjectCount: 21910 });
  assert.equal(statements.length, 2);
});

test('a rejected or uncertain database publication is never a receipt', async () => {
  for (const outcome of [false, undefined, Error('database unavailable')]) {
    let countReads = 0;
    await assert.rejects(publishCheckpointed({ scope: await freshScope(),
      reservationId, snapshotId, query: async sql => {
        if (sql.includes('FROM hosted.snapshots')) {
          countReads++;
          return { rows: [{ verified_object_count: 3 }] };
        }
        if (outcome instanceof Error) throw outcome;
        return { rows: [{ published: outcome }] };
      } }), /hosted_checkpointed_publication_failed/);
    assert.equal(countReads, 0);
  }
});
