const test = require('node:test');
const assert = require('node:assert/strict');
const { randomBytes } = require('node:crypto');
const { isAuthorizedScope } = require('../hosted/access');
const { verifyObjectCapability } = require('../hosted/object_capability');
const { issuePutCapability } = require('../hosted/upload_grant');
const { accountId, vaultId, freshScope } = require('./hosted-subscriber-fixture');

const reservationId = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const key = `accounts/${accountId}/vaults/${vaultId}/metadata/11111111-1111-4111-8111-111111111111.json`;
const item = Object.freeze({ key, bytes: 20, sha256: 'a'.repeat(64) });
const secret = randomBytes(32);

test('only a fresh owned scope and durable reservation can sign one exact PUT', async () => {
  const authorized = await freshScope();
  let queries = 0;
  const token = await issuePutCapability({ scope: authorized, reservationId,
    item, secret, query: async (sql, values) => {
      queries++;
      assert.match(sql, /reserve_object_grant_elastic_current/);
      assert.deepEqual(values, [accountId, vaultId, reservationId,
        key, 20, item.sha256, 100_000_000]);
      return { rows: [{ allowed: true }] };
    } });
  assert.equal(queries, 1);
  assert.deepEqual(await verifyObjectCapability(token, 'PUT', key, secret), item);
  await assert.rejects(verifyObjectCapability(token, 'PUT', key, secret,
    Date.now() + 30_000), /hosted_object_access_denied/);
  assert.equal(isAuthorizedScope(authorized), false);
  await assert.rejects(issuePutCapability({ scope: authorized, reservationId,
    item, secret, query: async () => { queries++; } }), /hosted_upload_grant_denied/);
  assert.equal(queries, 1);
});

test('foreign and client-shaped scopes fail before database or signing', async () => {
  let queries = 0;
  const query = async () => { queries++; return { rows: [{ allowed: true }] }; };
  const foreign = { ...item, key: key.replace(vaultId,
    'dddddddd-dddd-4ddd-8ddd-dddddddddddd') };
  await assert.rejects(issuePutCapability({ scope: await freshScope(), reservationId,
    item: foreign, secret, query }), /hosted_upload_grant_denied/);
  await assert.rejects(issuePutCapability({ scope: { accountId, vaultId,
    allowanceBytes: 100_000_000 }, reservationId, item, secret, query }),
  /hosted_upload_grant_denied/);
  assert.equal(queries, 0);
});

test('quota, reservation, and signing failures disclose no internals', async () => {
  for (const [query, signingSecret] of [
    [async () => ({ rows: [{ allowed: false }] }), secret],
    [async () => { throw Error('private database detail'); }, secret],
    [async () => ({ rows: [{ allowed: true }] }), Buffer.from('wrong key')],
  ]) {
    await assert.rejects(issuePutCapability({ scope: await freshScope(),
      reservationId, item, secret: signingSecret, query }), error =>
      error.message === 'hosted_upload_grant_denied');
  }
});
