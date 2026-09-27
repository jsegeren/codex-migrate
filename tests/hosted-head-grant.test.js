const test = require('node:test');
const assert = require('node:assert/strict');
const { randomBytes } = require('node:crypto');
const { issueReuseHead } = require('../hosted/head_grant');
const { verifyObjectCapability } = require('../hosted/object_capability');
const { accountId, vaultId, freshScope } = require('./hosted-subscriber-fixture');

const reservationId = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const item = Object.freeze({ key: `accounts/${accountId}/vaults/${vaultId}/` +
  'objects/aa/' + 'a'.repeat(62) + '.cvchunk', bytes: 20, sha256: 'b'.repeat(64) });
const secret = randomBytes(32);

test('only an exact published or reserved object receives a HEAD grant', async () => {
  const scope = await freshScope();
  let calls = 0;
  const token = await issueReuseHead({ scope, reservationId, item, secret,
    query: async (sql, values) => {
      calls++;
      assert.match(sql, /hosted\.can_probe_upload_object_current/);
      assert.deepEqual(values, [accountId, vaultId, reservationId,
        item.key, item.bytes, item.sha256, 100_000_000]);
      return { rows: [{ allowed: true }] };
    } });
  assert.deepEqual(await verifyObjectCapability(token, 'HEAD', item.key, secret), item);
  await assert.rejects(verifyObjectCapability(token, 'PUT', item.key, secret),
    /hosted_object_access_denied/);
  await assert.rejects(verifyObjectCapability(token, 'HEAD', item.key, secret,
    Date.now() + 31_000), /hosted_object_access_denied/);
  await assert.rejects(issueReuseHead({ scope, reservationId, item, secret,
    query: async () => { calls++; } }), /hosted_head_grant_denied/);
  assert.equal(calls, 1);
});

test('foreign, client-shaped, unrecorded, and expired reservations cannot probe', async () => {
  let calls = 0;
  const query = async () => { calls++; return { rows: [{ allowed: false }] }; };
  await assert.rejects(issueReuseHead({ scope: { accountId, vaultId },
    reservationId, item, secret, query }), /hosted_head_grant_denied/);
  await assert.rejects(issueReuseHead({ scope: await freshScope(),
    reservationId, item: { ...item, key: item.key.replace(vaultId,
      'dddddddd-dddd-4ddd-8ddd-dddddddddddd') }, secret, query }),
  /hosted_head_grant_denied/);
  assert.equal(calls, 0);
  await assert.rejects(issueReuseHead({ scope: await freshScope(),
    reservationId, item, secret, query }), /hosted_head_grant_denied/);
  assert.equal(calls, 1);
});
