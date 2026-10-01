const test = require('node:test');
const assert = require('node:assert/strict');
const { randomBytes } = require('node:crypto');
const { createBatchVerifier } = require('../hosted/batch_verifier');

const secret = randomBytes(32);
const key = 'accounts/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/vaults/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/metadata/11111111-1111-4111-8111-111111111111.json';
const item = { key, bytes: 10, sha256: 'a'.repeat(64) };

test('server-signed batch reaches the actual Worker verifier with no redirect', async () => {
  const { handleBatchVerification } = await import('../hosted/r2_object_worker.mjs');
  let calls = 0;
  let present = true;
  const bucket = { head: async path => {
    calls++;
    if (!present || path !== key) return null;
    return { key, size: item.bytes,
      checksums: { sha256: Uint8Array.from(Buffer.from(item.sha256, 'hex')).buffer } };
  } };
  const fetchImpl = async (url, options) => {
    assert.equal(options.redirect, 'error');
    assert.equal(new URL(url).origin, 'https://backup.example.test');
    return handleBatchVerification(new Request(url, options), bucket, secret);
  };
  const verify = createBatchVerifier({ origin: 'https://backup.example.test',
    secret, fetchImpl });
  assert.equal(await verify([item]), true);
  assert.equal(calls, 1);
  present = false;
  assert.equal(await verify([item]), false);
  assert.equal(calls, 2);
});

test('bad scope, origin, and upstream responses fail without a false proof', async () => {
  assert.throws(() => createBatchVerifier({ origin: 'http://other.example', secret }),
    /hosted_batch_verification_failed/);
  assert.throws(() => createBatchVerifier({ origin: 'https://user:pass@other.example',
    secret }), /hosted_batch_verification_failed/);
  let calls = 0;
  const verify = createBatchVerifier({ origin: 'https://backup.example.test',
    secret, fetchImpl: async () => { calls++; return { status: 302 }; } });
  await assert.rejects(verify([item]), /hosted_batch_verification_failed/);
  await assert.rejects(verify([{ ...item, key: '../foreign' }]),
    /hosted_batch_verification_failed/);
  assert.equal(calls, 1);
});
