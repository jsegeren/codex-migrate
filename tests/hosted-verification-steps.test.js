const test = require('node:test');
const assert = require('node:assert/strict');
const { verifyNextPage } = require('../hosted/verification_steps');
const { accountId, vaultId, freshScope } = require('./hosted-subscriber-fixture');

const reservationId = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const snapshotId = '11111111-1111-4111-8111-111111111111';
const prefix = `accounts/${accountId}/vaults/${vaultId}/`;
const staged = { object_key: prefix + `metadata/${snapshotId}.json`,
  object_bytes: '10', sha256: 'a'.repeat(64) };

function queryWith(rows, events) {
  return async (sql, values) => {
    if (sql.includes('FROM hosted.upload_reservations')) {
      return { rows: [{ staged_count: 3, staged_bytes: '30',
        declared_count: 3, declared_bytes: '30', state: 'active',
        lease_valid: true }] };
    }
    if (sql.includes('reuse_recent_published_chunk_proofs_current')) {
      return { rows: [{ reused: 0 }] };
    }
    if (sql.includes('FROM hosted.staged_receipt_objects')) {
      assert.deepEqual(values, [reservationId]);
      return { rows };
    }
    assert.match(sql, /record_verified_receipt_page_current/);
    events.push('record');
    assert.deepEqual(JSON.parse(values[4]), [{ key: staged.object_key,
      bytes: 10, sha256: staged.sha256 }]);
    return { rows: [{ accepted: rows.length }] };
  };
}

test('one bounded page is independently checked before its durable checkpoint', async () => {
  const events = [];
  const result = await verifyNextPage({ scope: await freshScope(),
    reservationId, snapshotId,
    verifyBatch: async batch => {
      events.push('provider');
      assert.deepEqual(batch, [{ key: staged.object_key, bytes: 10,
        sha256: staged.sha256 }]);
      return true;
    }, query: queryWith([staged], events) });
  assert.deepEqual(result, { verifiedObjects: 1, ready: false });
  assert.deepEqual(events, ['provider', 'record']);
});

test('empty next page is only ready for a separate guarded publication', async () => {
  const events = [];
  const result = await verifyNextPage({ scope: await freshScope(),
    reservationId, snapshotId, verifyBatch: async () => {
      throw Error('no provider work');
    }, query: queryWith([], events) });
  assert.deepEqual(result, { verifiedObjects: 0, ready: true });
  assert.deepEqual(events, []);
});

test('a bounded published proof page skips R2 without claiming publication', async () => {
  const calls = [];
  const result = await verifyNextPage({ scope: await freshScope(),
    reservationId, snapshotId,
    verifyBatch: async () => { throw Error('no repeated provider check'); },
    query: async (sql, values) => {
      if (sql.includes('FROM hosted.upload_reservations')) {
        return { rows: [{ staged_count: 3, staged_bytes: '30',
          declared_count: 3, declared_bytes: '30', state: 'active',
          lease_valid: true }] };
      }
      assert.match(sql, /reuse_recent_published_chunk_proofs_current/);
      assert.deepEqual(values.slice(2, 4), [reservationId, snapshotId]);
      calls.push('reuse');
      return { rows: [{ reused: 2 }] };
    } });
  assert.deepEqual(result, { verifiedObjects: 2, ready: false });
  assert.deepEqual(calls, ['reuse']);
});

test('malformed proof-reuse result fails closed before any provider work', async () => {
  await assert.rejects(verifyNextPage({ scope: await freshScope(),
    reservationId, snapshotId,
    verifyBatch: async () => { throw Error('should not run'); },
    query: async sql => sql.includes('FROM hosted.upload_reservations')
      ? { rows: [{ staged_count: 3, staged_bytes: '30', declared_count: 3,
        declared_bytes: '30', state: 'active', lease_valid: true }] }
      : { rows: [{ reused: 2049 }] } }), /hosted_verification_step_failed/);
});

test('an already-published reservation can reconcile a lost final response', async () => {
  const result = await verifyNextPage({ scope: await freshScope(),
    reservationId, snapshotId, verifyBatch: async () => {
      throw Error('published objects need no second scan');
    }, query: async sql => {
      assert.match(sql, /FROM hosted.upload_reservations/);
      return { rows: [{ staged_count: 3, staged_bytes: '30',
        declared_count: 3, declared_bytes: '30', state: 'published',
        lease_valid: false }] };
    } });
  assert.deepEqual(result, { verifiedObjects: 0, ready: true });
});

test('provider failure, mismatched rows, and incomplete declarations record nothing', async () => {
  for (const failure of ['provider', 'cross_account', 'incomplete']) {
    const events = [];
    await assert.rejects(verifyNextPage({ scope: await freshScope(),
      reservationId, snapshotId,
      verifyBatch: async () => failure !== 'provider',
      query: async (sql, values) => {
        if (sql.includes('FROM hosted.upload_reservations')) {
          return { rows: [{ staged_count: 3, staged_bytes: '30',
            declared_count: failure === 'incomplete' ? 4 : 3,
            declared_bytes: '30', state: 'active', lease_valid: true }] };
        }
        if (sql.includes('reuse_recent_published_chunk_proofs_current')) {
          return { rows: [{ reused: 0 }] };
        }
        if (sql.includes('FROM hosted.staged_receipt_objects')) {
          assert.deepEqual(values, [reservationId]);
          return { rows: [failure === 'cross_account' ? {
            ...staged, object_key: staged.object_key.replace(accountId,
              'dddddddd-dddd-4ddd-8ddd-dddddddddddd') } : staged] };
        }
        events.push('record');
        return { rows: [{ accepted: 1 }] };
      } }), /hosted_verification_step_failed/);
    assert.deepEqual(events, []);
  }
});
