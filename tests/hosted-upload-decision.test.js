const test = require('node:test');
const assert = require('node:assert/strict');
const { randomBytes } = require('node:crypto');
const { decideUploadObject } = require('../hosted/upload_decision');
const { verifyObjectCapability } = require('../hosted/object_capability');
const { accountId, vaultId, freshScope } = require('./hosted-subscriber-fixture');

const reservationId = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
const item = Object.freeze({ key: `accounts/${accountId}/vaults/${vaultId}/` +
  'objects/aa/' + 'a'.repeat(62) + '.cvchunk', bytes: 20,
sha256: 'b'.repeat(64) });
const secret = randomBytes(32);

test('new object requires a separate PUT grant, not a storage capability', async () => {
  const result = await decideUploadObject({ scope: await freshScope(),
    reservationId, item, secret, query: async (sql, values) => {
      assert.match(sql, /classify_upload_object_current/);
      assert.deepEqual(values, [accountId, vaultId, reservationId,
        item.key, item.bytes, item.sha256, 100_000_000]);
      return { rows: [{ decision: 'put' }] };
    } });
  assert.deepEqual(result, { action: 'put_required' });
  assert.equal(Object.isFrozen(result), true);
});

test('known exact object receives only a short-lived HEAD capability', async () => {
  const result = await decideUploadObject({ scope: await freshScope(),
    reservationId, item, secret,
    query: async () => ({ rows: [{ decision: 'head' }] }) });
  assert.equal(result.action, 'head');
  assert.deepEqual(await verifyObjectCapability(result.grant,
    'HEAD', item.key, secret), item);
  await assert.rejects(verifyObjectCapability(result.grant,
    'GET', item.key, secret), /hosted_object_access_denied/);
});

test('invalid, foreign, expired, and unavailable decisions fail closed', async () => {
  let calls = 0;
  const query = async () => { calls++; return { rows: [{ decision: 'put' }] }; };
  const scope = await freshScope();
  await assert.rejects(decideUploadObject({ scope: { accountId, vaultId,
    allowanceBytes: 100_000_000 }, reservationId, item, secret, query }),
  /hosted_upload_decision_denied/);
  await assert.rejects(decideUploadObject({ scope,
    reservationId, item: { ...item, key: item.key.replace(vaultId,
      'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee') }, secret, query }),
  /hosted_upload_decision_denied/);
  await assert.rejects(decideUploadObject({ scope,
    reservationId, item, secret, query }), /hosted_upload_decision_denied/);
  assert.equal(calls, 0);
  for (const answer of [null, 'denied', true, undefined]) {
    await assert.rejects(decideUploadObject({ scope: await freshScope(),
      reservationId, item, secret,
      query: async () => ({ rows: [{ decision: answer }] }) }), error =>
      error.message === 'hosted_upload_decision_denied');
  }
  await assert.rejects(decideUploadObject({ scope: await freshScope(),
    reservationId, item, secret,
    query: async () => { throw Error('private account details'); } }), error =>
    error.message === 'hosted_upload_decision_denied');
});
