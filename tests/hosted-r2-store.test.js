const test = require('node:test');
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const { putImmutableChecked, verifiedHead, verifiedBatch,
  readVerifiedBody, deleteExactOrAbsent } = require('../hosted/r2_verified_store');
const { verifyStagedReceipt } = require('../hosted/receipt');

const account = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const vault = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const chunk = 'c'.repeat(64);
const key = `accounts/${account}/vaults/${vault}/objects/${chunk.slice(0, 2)}/${chunk.slice(2)}.cvchunk`;
const hash = value => createHash('sha256').update(value).digest('hex');
const itemForKey = (objectKey, value) => ({ key: objectKey, bytes: value.length,
  sha256: hash(value) });
const itemFor = value => itemForKey(key, value);

class FakeR2 {
  constructor() { this.objects = new Map(); this.race = null; this.putCalls = 0;
    this.deleteCalls = 0; }
  metadata(key) {
    const record = this.objects.get(key);
    return record && { key, size: record.bytes.length, version: record.version,
      checksums: record.checksum ? { sha256: Uint8Array.from(
        Buffer.from(record.checksum, 'hex')).buffer } : {} };
  }
  async head(key) { return this.metadata(key) || null; }
  async get(key) {
    const record = this.objects.get(key);
    if (!record) return null;
    return { ...this.metadata(key), body: new ReadableStream({
      start(controller) {
        controller.enqueue(Uint8Array.from(record.bytes));
        controller.close();
      },
    }) };
  }
  async put(key, body, options) {
    this.putCalls++;
    assert.equal(options.onlyIf.get('If-None-Match'), '*');
    if (this.race) {
      this.objects.set(key, this.race);
      this.race = null;
    }
    if (this.objects.has(key)) return null;
    const bytes = Buffer.from(body);
    if (hash(bytes) !== options.sha256) throw new Error('provider digest mismatch');
    this.objects.set(key, { bytes, checksum: options.sha256, version: 'new-version' });
    return this.metadata(key);
  }
  async delete(key) { this.deleteCalls++; this.objects.delete(key); }
}

test('cleanup deletes only exact ciphertext and confirms provider absence', async () => {
  const bucket = new FakeR2();
  const bytes = Buffer.from('synthetic orphan ciphertext');
  const item = itemFor(bytes);
  assert.equal(await deleteExactOrAbsent(bucket, item), 'absent');
  assert.equal(bucket.deleteCalls, 0);
  await putImmutableChecked(bucket, item, bytes);
  await assert.rejects(deleteExactOrAbsent(bucket,
    { ...item, sha256: '0'.repeat(64) }), /hosted_object_unverified/);
  assert.equal(bucket.deleteCalls, 0);
  assert.equal(await deleteExactOrAbsent(bucket, item), 'deleted');
  assert.equal(bucket.deleteCalls, 1);
  assert.equal(await bucket.head(key), null);
  assert.equal(await deleteExactOrAbsent(bucket, item), 'absent');
  assert.equal(bucket.deleteCalls, 1);
});

test('cleanup refuses a failed DELETE or an object still present afterward', async () => {
  const bucket = new FakeR2();
  const bytes = Buffer.from('synthetic orphan ciphertext');
  const item = itemFor(bytes);
  await putImmutableChecked(bucket, item, bytes);
  bucket.delete = async () => { throw new Error('private provider detail'); };
  await assert.rejects(deleteExactOrAbsent(bucket, item), error =>
    error.message === 'hosted_object_unverified');
  assert.ok(await bucket.head(key));
  bucket.delete = async () => {};
  await assert.rejects(deleteExactOrAbsent(bucket, item),
    /hosted_object_unverified/);
  assert.ok(await bucket.head(key));
});

test('R2 checksum-checked conditional write is reusable and independently readable', async () => {
  const bucket = new FakeR2();
  const bytes = Buffer.from('synthetic encrypted chunk');
  const item = itemFor(bytes);
  assert.equal(await putImmutableChecked(bucket, item, bytes), 'uploaded');
  assert.equal(await verifiedHead(bucket, item), true);
  assert.equal(await putImmutableChecked(bucket, item, bytes), 'reused');
  assert.equal(bucket.putCalls, 1);
  assert.deepEqual(bucket.objects.get(key).bytes, bytes);
});

test('mismatched content and a raced conflicting immutable key fail closed', async () => {
  const bucket = new FakeR2();
  const item = itemFor(Buffer.from('expected'));
  await assert.rejects(putImmutableChecked(bucket, item, Buffer.from('changed')),
    /hosted_object_unverified/);
  assert.equal(bucket.objects.size, 0);
  bucket.race = { bytes: Buffer.from('foreign'), checksum: hash('foreign'), version: 'other' };
  await assert.rejects(putImmutableChecked(bucket, item, Buffer.from('expected')),
    /hosted_object_unverified/);
  assert.equal(await verifiedHead(bucket, item), false);
});

test('a matching concurrent write is reusable without replacing it', async () => {
  const bucket = new FakeR2();
  const bytes = Buffer.from('same encrypted content');
  const item = itemFor(bytes);
  bucket.race = { bytes, checksum: item.sha256, version: 'racer' };
  assert.equal(await putImmutableChecked(bucket, item, bytes), 'reused');
  assert.equal(bucket.objects.get(key).version, 'racer');
});

test('a changed object after PUT cannot pass post-write verification', async () => {
  const bucket = new FakeR2();
  const bytes = Buffer.from('same encrypted content');
  const item = itemFor(bytes);
  const originalHead = bucket.head.bind(bucket);
  let calls = 0;
  bucket.head = async checkedKey => {
    if (++calls === 2) {
      bucket.objects.set(checkedKey, {
        bytes, checksum: item.sha256, version: 'later-replacement',
      });
    }
    return originalHead(checkedKey);
  };
  await assert.rejects(putImmutableChecked(bucket, item, bytes),
    /hosted_object_unverified/);
});

test('missing provider checksum never becomes an integrity or reuse claim', async () => {
  const bucket = new FakeR2();
  const bytes = Buffer.from('synthetic encrypted chunk');
  const item = itemFor(bytes);
  bucket.objects.set(key, { bytes, checksum: null, version: 'older-s3-write' });
  assert.equal(await verifiedHead(bucket, item), false);
  await assert.rejects(putImmutableChecked(bucket, item, bytes),
    /hosted_object_unverified/);
  assert.equal(bucket.putCalls, 0);
});

test('malformed scope, bytes, digest, or absent provider fail before any write', async () => {
  const bucket = new FakeR2();
  const bytes = Buffer.from('fixture');
  const item = itemFor(bytes);
  for (const changed of [
    { ...item, key: '../foreign' },
    { ...item, key: `accounts/${account}/vaults/${vault}/objects/../escape` },
    { ...item, bytes: 100_000_001 },
    { ...item, sha256: 'bad' },
  ]) {
    await assert.rejects(putImmutableChecked(bucket, changed, bytes),
      /hosted_object_unverified/);
    assert.equal(await verifiedHead(bucket, changed), false);
  }
  await assert.rejects(putImmutableChecked(null, item, bytes),
    /hosted_object_unverified/);
  assert.equal(bucket.putCalls, 0);
});

test('provider errors are redacted', async () => {
  const bucket = { head: async () => { throw new Error('secret R2 location'); },
    put: async () => null };
  await assert.rejects(putImmutableChecked(bucket, itemFor(Buffer.from('x')),
    Buffer.from('x')), error => error.message === 'hosted_object_unverified');
});

test('R2 metadata verifies the full scoped receipt without downloading ciphertext', async () => {
  const bucket = new FakeR2();
  const snapshot = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
  const base = `accounts/${account}/vaults/${vault}/`;
  const paths = [
    `metadata/${snapshot}.json`,
    `objects/${chunk.slice(0, 2)}/${chunk.slice(2)}.cvchunk`,
    `manifests/${snapshot}.cvmanifest`,
    `refs/${snapshot}.json`,
  ];
  const objects = [];
  for (const path of paths) {
    const bytes = Buffer.from(`synthetic encrypted:${path}`);
    const item = itemForKey(base + path, bytes);
    await putImmutableChecked(bucket, item, bytes);
    objects.push({ ...item, key: path });
  }
  const receipt = { version: 1, snapshot_id: snapshot,
    remote_bytes_checked: objects.reduce((total, item) => total + item.bytes, 0),
    objects };
  const scope = { accountId: account, vaultId: vault };
  const proof = await verifyStagedReceipt(receipt, 10_000, scope,
    item => verifiedHead(bucket, item));
  assert.equal(proof.objectCount, 4);
  bucket.objects.delete(base + paths[1]);
  await assert.rejects(verifyStagedReceipt(receipt, 10_000, scope,
    item => verifiedHead(bucket, item)), /hosted_receipt_invalid/);
});

test('R2 batch verification enforces a bounded per-invocation object count', async () => {
  const bucket = new FakeR2();
  const bytes = Buffer.from('encrypted object');
  const item = itemFor(bytes);
  await putImmutableChecked(bucket, item, bytes);
  assert.equal(await verifiedBatch(bucket, [item]), true);
  assert.equal(await verifiedBatch(bucket, [{ ...item, sha256: '0'.repeat(64) }]), false);
  assert.equal(await verifiedBatch(bucket, []), false);
  assert.equal(await verifiedBatch(bucket, Array(513).fill(item)), false);
});

test('R2 batch verification bounds concurrent reads and stops after a failed wave', async () => {
  const bytes = Buffer.from('encrypted object');
  const item = itemFor(bytes);
  let inFlight = 0;
  let peak = 0;
  let calls = 0;
  const bucket = { head: async objectKey => {
    calls++;
    inFlight++;
    peak = Math.max(peak, inFlight);
    await Promise.resolve();
    inFlight--;
    return { key: objectKey, size: item.bytes,
      checksums: { sha256: Uint8Array.from(Buffer.from(item.sha256, 'hex')).buffer } };
  } };
  assert.equal(await verifiedBatch(bucket, Array(33).fill(item)), true);
  assert.equal(calls, 33);
  assert.equal(peak, 16);

  calls = 0;
  bucket.head = async objectKey => {
    calls++;
    return calls === 1 ? null : { key: objectKey, size: item.bytes,
      checksums: { sha256: Uint8Array.from(Buffer.from(item.sha256, 'hex')).buffer } };
  };
  assert.equal(await verifiedBatch(bucket, Array(33).fill(item)), false);
  assert.equal(calls, 16);
});

test('restore streams only a matching encrypted object', async () => {
  const bucket = new FakeR2();
  const bytes = Buffer.from('encrypted restore chunk');
  const item = itemFor(bytes);
  await assert.rejects(readVerifiedBody(bucket, item), /hosted_object_unverified/);
  await putImmutableChecked(bucket, item, bytes);
  const stream = await readVerifiedBody(bucket, item);
  assert.deepEqual(Buffer.from(await new Response(stream).arrayBuffer()), bytes);
  for (const changed of [
    { ...item, bytes: item.bytes + 1 },
    { ...item, sha256: '0'.repeat(64) },
    { ...item, key: '../other-vault' },
  ]) {
    await assert.rejects(readVerifiedBody(bucket, changed), /hosted_object_unverified/);
  }
  bucket.objects.get(key).checksum = null;
  await assert.rejects(readVerifiedBody(bucket, item), /hosted_object_unverified/);
});
