const test = require('node:test');
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const { validateReceipt, verifyStagedReceipt } = require('../hosted/receipt');

const snapshot = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const chunk = 'ab' + 'c'.repeat(62);
const keys = [
  `metadata/${snapshot}.json`,
  `objects/${chunk.slice(0, 2)}/${chunk.slice(2)}.cvchunk`,
  `manifests/${snapshot}.cvmanifest`,
  `refs/${snapshot}.json`,
];
const digest = value => createHash('sha256').update(value).digest('hex');
function fixture() {
  const stored = new Map(keys.map(key => [key, Buffer.from(`synthetic:${key}`)]));
  const objects = keys.map(key => ({ key, bytes: stored.get(key).length,
    sha256: digest(stored.get(key)) }));
  const receipt = { version: 1, snapshot_id: snapshot,
    remote_bytes_checked: objects.reduce((sum, item) => sum + item.bytes, 0), objects };
  const verify = async item => {
    const value = stored.get(item.key);
    return Boolean(value && value.length === item.bytes && digest(value) === item.sha256);
  };
  return { receipt, stored, verify };
}

test('independently verified objects produce only a content-free proof', async () => {
  const { receipt, verify } = fixture();
  assert.equal(validateReceipt(receipt, 1024).totalBytes, receipt.remote_bytes_checked);
  assert.deepEqual(await verifyStagedReceipt(receipt, 1024, verify), {
    snapshotId: snapshot, objectCount: 4, totalBytes: receipt.remote_bytes_checked,
  });
});

test('a missing or altered object refuses verification', async () => {
  const { receipt, stored, verify } = fixture();
  stored.delete(keys[1]);
  await assert.rejects(verifyStagedReceipt(receipt, 1024, verify), /hosted_receipt_invalid/);
  stored.set(keys[1], Buffer.from('tampered'));
  await assert.rejects(verifyStagedReceipt(receipt, 1024, verify), /hosted_receipt_invalid/);
});

test('bad scope, duplicate chunks, malformed hashes and quota excess fail before reads', async () => {
  for (const change of [
    receipt => { receipt.objects[0].key = `metadata/${'b'.repeat(36)}.json`; },
    receipt => { receipt.objects.splice(2, 0, { ...receipt.objects[1] }); },
    receipt => { receipt.objects[1].sha256 = '0'.repeat(63); },
    receipt => { receipt.objects[2].key = '../foreign-vault'; },
    receipt => { receipt.remote_bytes_checked += 1; },
    receipt => { receipt.objects[1].bytes = 64 * 1024 * 1024 + 1025; },
  ]) {
    const { receipt } = fixture();
    change(receipt);
    let reads = 0;
    await assert.rejects(verifyStagedReceipt(receipt, 1024, async () => {
      reads++; return true;
    }), /hosted_receipt_invalid/);
    assert.equal(reads, 0);
  }
  const { receipt } = fixture();
  assert.throws(() => validateReceipt(receipt, receipt.remote_bytes_checked - 1),
    /hosted_receipt_invalid/);
});

test('no provider verifier means no protection proof', async () => {
  const { receipt } = fixture();
  await assert.rejects(verifyStagedReceipt(receipt, 1024), /hosted_receipt_invalid/);
  await assert.rejects(verifyStagedReceipt(receipt, 1024, async () => undefined),
    /hosted_receipt_invalid/);
});

test('provider errors are redacted and an async caller cannot rewrite the checked claim', async () => {
  const { receipt, verify } = fixture();
  await assert.rejects(verifyStagedReceipt(receipt, 1024, async () => {
    throw new Error('private provider endpoint and credential');
  }), error => error.message === 'hosted_receipt_invalid');
  let first = true;
  const proof = await verifyStagedReceipt(receipt, 1024, async item => {
    if (first) {
      first = false;
      receipt.objects[1].sha256 = '0'.repeat(64);
    }
    return verify(item);
  });
  assert.equal(proof.objectCount, 4);
});
