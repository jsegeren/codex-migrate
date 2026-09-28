const test = require('node:test');
const assert = require('node:assert/strict');
const { createHash, randomBytes } = require('node:crypto');
const { decodeSecret, signObjectCapability, verifyObjectCapability,
  signBatchVerification, verifyBatchVerification } =
  require('../hosted/object_capability');

const account = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const vault = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const objectId = 'c'.repeat(64);
const key = `accounts/${account}/vaults/${vault}/objects/${objectId.slice(0, 2)}/${objectId.slice(2)}.cvchunk`;
const bytes = Buffer.from('synthetic encrypted data');
const hash = value => createHash('sha256').update(value).digest('hex');
const item = Object.freeze({ key, bytes: bytes.length, sha256: hash(bytes) });
const secret = randomBytes(32);

class FakeBucket {
  constructor() { this.objects = new Map(); this.puts = 0; this.heads = 0;
    this.deletes = 0; }
  metadata(path) {
    const data = this.objects.get(path);
    return data && { key: path, size: data.length, version: 'v1',
      checksums: { sha256: Uint8Array.from(Buffer.from(hash(data), 'hex')).buffer } };
  }
  async head(path) { this.heads++; return this.metadata(path) || null; }
  async get(path) {
    const data = this.objects.get(path);
    return data && { ...this.metadata(path), body: new ReadableStream({
      start(controller) { controller.enqueue(data); controller.close(); },
    }) };
  }
  async put(path, body, options) {
    this.puts++;
    assert.equal(options.onlyIf.get('If-None-Match'), '*');
    const data = Buffer.from(await new Response(body).arrayBuffer());
    if (hash(data) !== options.sha256) throw Error('digest mismatch');
    if (this.objects.has(path)) return null;
    this.objects.set(path, data);
    return this.metadata(path);
  }
  async delete(path) { this.deletes++; this.objects.delete(path); }
}

test('cleanup DELETE capability is method-bound and requires provider absence', async () => {
  const { handleObjectRequest } = await worker();
  const bucket = new FakeBucket();
  bucket.objects.set(key, bytes);
  const token = await signObjectCapability('DELETE', item, secret);
  const put = await signObjectCapability('PUT', item, secret);
  assert.equal((await handleObjectRequest(request('DELETE', key, put),
    bucket, secret)).status, 403);
  assert.equal((await handleObjectRequest(request('GET', key, token),
    bucket, secret)).status, 403);
  assert.equal((await handleObjectRequest(request('DELETE', key, token,
    Buffer.from('body')), bucket, secret)).status, 400);
  const disguisedBody = new Request(`https://backup.example.test/v1/object/${key}`, {
    method: 'DELETE', headers: { Authorization: `Bearer ${token}`,
      'Content-Length': '0' }, body: Buffer.from('body'),
  });
  assert.equal((await handleObjectRequest(disguisedBody, bucket, secret)).status, 400);
  assert.equal(bucket.deletes, 0);
  assert.equal((await handleObjectRequest(request('DELETE', key, token),
    bucket, secret)).status, 204);
  assert.equal(bucket.deletes, 1);
  assert.equal(bucket.objects.has(key), false);
  // Workerd may expose urllib's Content-Length: 0 as an empty body stream.
  bucket.objects.set(key, bytes);
  assert.equal((await handleObjectRequest(request('DELETE', key, token,
    Buffer.alloc(0)), bucket, secret)).status, 204);
  assert.equal(bucket.deletes, 2);
  assert.equal(bucket.objects.has(key), false);
  assert.equal((await handleObjectRequest(request('DELETE', key, token),
    bucket, secret)).status, 204);
  assert.equal(bucket.deletes, 2);
});

async function worker() { return import('../hosted/r2_object_worker.mjs'); }
function request(method, objectKey, token, body) {
  const headers = { Authorization: `Bearer ${token}` };
  if (body !== undefined) headers['Content-Length'] = String(body.length);
  return new Request(`https://backup.example.test/v1/object/${objectKey}`, {
    method, headers, ...(body === undefined ? {} : { body }),
  });
}

test('capability is short-lived and bound to exact method, scoped key, size, and digest', async () => {
  const now = 1_000_000;
  const token = await signObjectCapability('PUT', item, secret, now);
  assert.deepEqual(await verifyObjectCapability(token, 'PUT', key, secret, now), item);
  for (const [method, path, at] of [
    ['GET', key, now], ['PUT', key + 'x', now], ['PUT', key, now + 60_000],
    ['PUT', key, now - 1],
  ]) {
    await assert.rejects(verifyObjectCapability(token, method, path, secret, at),
      /hosted_object_access_denied/);
  }
  await assert.rejects(verifyObjectCapability(token, 'PUT', key, randomBytes(32), now),
    /hosted_object_access_denied/);
  await assert.rejects(verifyObjectCapability(token + 'A', 'PUT', key, secret, now),
    /hosted_object_access_denied/);
  await assert.rejects(signObjectCapability('PUT', { ...item, key: '../other' }, secret),
    /hosted_object_access_denied/);
  await assert.rejects(signObjectCapability('PUT', { ...item, bytes: 100_000_001 }, secret),
    /hosted_object_access_denied/);
  assert.deepEqual(Buffer.from(decodeSecret(secret.toString('base64url'))), secret);
  assert.throws(() => decodeSecret('not-a-key'), /hosted_object_access_denied/);
});

test('worker uploads once, verifies metadata, and streams a matching read', async () => {
  const { handleObjectRequest } = await worker();
  const bucket = new FakeBucket();
  const put = await signObjectCapability('PUT', item, secret);
  const head = await signObjectCapability('HEAD', item, secret);
  const get = await signObjectCapability('GET', item, secret);
  assert.equal((await handleObjectRequest(request('HEAD', key, head), bucket, secret)).status, 404);
  assert.equal((await handleObjectRequest(request('PUT', key, put, bytes), bucket, secret)).status, 201);
  assert.equal((await handleObjectRequest(request('PUT', key, put, bytes), bucket, secret)).status, 200);
  assert.equal(bucket.puts, 1);
  assert.equal((await handleObjectRequest(request('HEAD', key, head), bucket, secret)).status, 200);
  // One client HEAD must cost only one R2 metadata operation.
  assert.equal(bucket.heads, 5);
  bucket.objects.set(key, Buffer.from('different ciphertext'));
  assert.equal((await handleObjectRequest(request('HEAD', key, head), bucket, secret)).status, 409);
  bucket.objects.set(key, bytes);
  const response = await handleObjectRequest(request('GET', key, get), bucket, secret);
  assert.equal(response.status, 200);
  assert.deepEqual(Buffer.from(await response.arrayBuffer()), bytes);
  assert.equal(response.headers.get('cache-control'), 'private, no-store');
});

test('worker refuses altered, oversized, foreign, and unauthenticated requests', async () => {
  const { handleObjectRequest } = await worker();
  const bucket = new FakeBucket();
  const put = await signObjectCapability('PUT', item, secret);
  const foreignKey = key.replace(account, 'dddddddd-dddd-4ddd-8ddd-dddddddddddd');
  assert.equal((await handleObjectRequest(request('PUT', foreignKey, put, bytes), bucket, secret)).status, 403);
  assert.equal((await handleObjectRequest(request('GET', key, put), bucket, secret)).status, 403);
  assert.equal((await handleObjectRequest(new Request(`https://backup.example.test/v1/object/${key}?secret=x`, {
    method: 'PUT', headers: { Authorization: `Bearer ${put}` }, body: bytes,
  }), bucket, secret)).status, 404);
  assert.equal((await handleObjectRequest(request('PUT', key, put, bytes.subarray(0, -1)),
    bucket, secret)).status, 400);
  const altered = Buffer.from(bytes);
  altered[0] ^= 1;
  assert.equal((await handleObjectRequest(request('PUT', key, put, altered), bucket, secret)).status, 409);
  assert.equal(bucket.objects.size, 0);
  const overstated = Buffer.concat([bytes, Buffer.from('extra')]);
  const oversized = new Request(`https://backup.example.test/v1/object/${key}`, {
    method: 'PUT', headers: { Authorization: `Bearer ${put}`,
      'Content-Length': String(item.bytes) }, body: overstated,
  });
  assert.equal((await handleObjectRequest(oversized, bucket, secret)).status, 409);
  assert.equal(bucket.objects.size, 0);
  const shortStream = new ReadableStream({
    start(controller) { controller.enqueue(bytes.subarray(0, -1)); controller.close(); },
  });
  const truncated = new Request(`https://backup.example.test/v1/object/${key}`, {
    method: 'PUT', headers: { Authorization: `Bearer ${put}`,
      'Content-Length': String(item.bytes) }, body: shortStream, duplex: 'half',
  });
  assert.equal((await handleObjectRequest(truncated, bucket, secret)).status, 409);
  assert.equal(bucket.objects.size, 0);
  const defaultWorker = (await worker()).default;
  assert.equal((await defaultWorker.fetch(request('GET', key, put), {})).status, 404);
});

test('one signed batch verifies exact scoped objects without a public probe', async () => {
  const { handleBatchVerification } = await worker();
  const bucket = new FakeBucket();
  bucket.objects.set(key, bytes);
  const keyFor = id => key.replace(`objects/${objectId.slice(0, 2)}/${objectId.slice(2)}`,
    `objects/${id.slice(0, 2)}/${id.slice(2)}`);
  const secondKey = keyFor('d'.repeat(64));
  const second = { key: secondKey, bytes: bytes.length, sha256: hash(bytes) };
  bucket.objects.set(secondKey, bytes);
  const signed = await signBatchVerification([item, second], secret);
  const make = (body, token = signed.token) => new Request(
    'https://backup.example.test/v1/verify-batch', { method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json',
        'Content-Length': String(Buffer.byteLength(body)) }, body });
  assert.deepEqual(await verifyBatchVerification(signed.token, signed.body, secret),
    [item, second]);
  assert.equal((await handleBatchVerification(make(signed.body), bucket, secret)).status, 204);
  assert.equal(bucket.heads, 2);
  bucket.objects.delete(secondKey);
  assert.equal((await handleBatchVerification(make(signed.body), bucket, secret)).status, 409);
  assert.equal((await handleBatchVerification(make(signed.body.replace(item.sha256,
    'f'.repeat(64))), bucket, secret)).status, 403);
  assert.equal((await handleBatchVerification(make(signed.body, 'forged.token'),
    bucket, secret)).status, 403);
  await assert.rejects(signBatchVerification([item, item], secret),
    /hosted_object_access_denied/);
  await assert.rejects(signBatchVerification(Array.from({ length: 513 }, (_, i) => ({
    ...item, key: keyFor(i.toString(16).padStart(64, '0')),
  })), secret), /hosted_object_access_denied/);
  await assert.rejects(verifyBatchVerification(signed.token, signed.body,
    secret, Date.now() + 30_000), /hosted_object_access_denied/);
});
