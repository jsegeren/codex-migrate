const test = require('node:test');
const assert = require('node:assert/strict');
const { publishStoredPages } = require('../hosted/stored_publication');
const { accountId, vaultId, freshScope } = require('./hosted-subscriber-fixture');

const reservationId = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const snapshotId = '11111111-1111-4111-8111-111111111111';
const prefix = `accounts/${accountId}/vaults/${vaultId}/`;
const item = (key, bytes, hash) => ({ object_key: prefix + key,
  object_bytes: String(bytes), sha256: hash.repeat(64) });
function rows(chunkCount = 1) {
  const items = [item(`metadata/${snapshotId}.json`, 10, 'a')];
  for (let index = 0; index < chunkCount; index++) {
    const id = index.toString(16).padStart(64, '0');
    items.push(item(`objects/${id.slice(0, 2)}/${id.slice(2)}.cvchunk`, 40, 'b'));
  }
  items.push(item(`manifests/${snapshotId}.cvmanifest`, 10, 'c'));
  items.push(item(`refs/${snapshotId}.json`, 10, 'd'));
  const total = 30 + 40 * chunkCount;
  return items.reverse().map(value => ({ ...value,
    staged_snapshot_id: snapshotId, staged_count: items.length,
    staged_bytes: String(total), declared_count: items.length,
    declared_bytes: String(total) }));
}

test('stored pages are assembled, provider-verified, then published', async () => {
  let verificationCalls = 0;
  let publicationCalls = 0;
  const result = await publishStoredPages({ scope: await freshScope(),
    reservationId, snapshotId,
    verifyBatch: async items => {
      verificationCalls++;
      assert.equal(items.length, 4);
      assert.ok(items.every(value => value.key.startsWith(prefix)));
      return true;
    },
    query: async (sql, values) => {
      if (sql.includes('FROM hosted.upload_reservations')) {
        assert.deepEqual(values, [accountId, vaultId, reservationId, snapshotId]);
        return { rows: rows() };
      }
      assert.match(sql, /publish_declared_verified_staged_current/);
      publicationCalls++;
      const objects = JSON.parse(values[4]);
      assert.equal(objects.length, 4);
      assert.equal(objects[0].key, prefix + `metadata/${snapshotId}.json`);
      assert.equal(objects[1].key, prefix +
        `objects/00/${'0'.repeat(62)}.cvchunk`);
      assert.equal(objects[3].key, prefix + `refs/${snapshotId}.json`);
      return { rows: [{ published: true }] };
    } });
  assert.equal(result.snapshotId, snapshotId);
  assert.equal(verificationCalls, 1);
  assert.equal(publicationCalls, 1);
});

test('missing, changed, or cross-account staged rows never reach publication', async () => {
  for (const broken of [
    rows().slice(1),
    rows().map((value, i) => i === 0 ? { ...value,
      staged_count: 9 } : value),
    rows().map(value => ({ ...value, declared_count: value.staged_count + 1 })),
    rows().map((value, i) => i === 0 ? { ...value,
      object_key: value.object_key.replace(accountId,
        'dddddddd-dddd-4ddd-8ddd-dddddddddddd') } : value),
  ]) {
    let verificationCalls = 0;
    await assert.rejects(publishStoredPages({ scope: await freshScope(),
      reservationId, snapshotId,
      verifyBatch: async () => { verificationCalls++; return true; },
      query: async sql => {
        if (sql.includes('FROM hosted.upload_reservations')) return { rows: broken };
        throw Error('must not publish');
      } }), /hosted_stored_publication_failed/);
    assert.equal(verificationCalls, 0);
  }
});

test('a measured-size receipt stays inside the service, not a web response', async () => {
  const syntheticRows = rows(21_907);
  let checked = 0;
  let published = 0;
  await publishStoredPages({ scope: await freshScope(), reservationId, snapshotId,
    verifyBatch: async batch => { checked += batch.length; return true; },
    query: async (sql, values) => {
      if (sql.includes('FROM hosted.upload_reservations')) {
        return { rows: syntheticRows };
      }
      published++;
      assert.equal(JSON.parse(values[4]).length, syntheticRows.length);
      return { rows: [{ published: true }] };
    } });
  assert.equal(checked, syntheticRows.length);
  assert.equal(published, 1);
});
