import test from 'node:test';
import assert from 'node:assert/strict';
import worker from './worker.mjs';

class SyntheticBucket {
  objects = new Map();

  async metadata(key) {
    const body = this.objects.get(key);
    if (!body) return null;
    return { key, size: body.byteLength, version: 'synthetic-v1',
      checksums: { sha256: await crypto.subtle.digest('SHA-256', body) } };
  }

  async head(key) { return this.metadata(key); }

  async put(key, value, options) {
    assert.equal(options.onlyIf.get('If-None-Match'), '*');
    const body = new Uint8Array(await new Response(value).arrayBuffer());
    const actual = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', body)),
      byte => byte.toString(16).padStart(2, '0')).join('');
    if (actual !== options.sha256) throw Error('synthetic_checksum_mismatch');
    if (this.objects.has(key)) return null;
    this.objects.set(key, body);
    return this.metadata(key);
  }

  async get(key) {
    const body = this.objects.get(key);
    if (!body) return null;
    return { ...await this.metadata(key), body: new ReadableStream({
      start(controller) { controller.enqueue(body); controller.close(); },
    }) };
  }

  async delete(keys) {
    for (const key of Array.isArray(keys) ? keys : [keys]) {
      this.objects.delete(key);
    }
  }
}

test('sandbox probe is inert without an explicit local enable flag', async () => {
  const request = new Request('http://127.0.0.1/probe', { method: 'POST' });
  const response = await worker.fetch(request, {});
  assert.equal(response.status, 404);
});

test('sandbox probe refuses non-loopback hosts even when enabled', async () => {
  const request = new Request('https://example.com/probe', { method: 'POST' });
  const response = await worker.fetch(request, { PROBE_ENABLED: '1' });
  assert.equal(response.status, 404);
});

test('sandbox probe refuses other paths and methods', async () => {
  for (const request of [new Request('http://localhost/probe'),
    new Request('http://localhost/other', { method: 'POST' })]) {
    const response = await worker.fetch(request, { PROBE_ENABLED: '1' });
    assert.equal(response.status, 404);
  }
});

test('probe checks exact deletion, retry, and wrong-digest refusal', async () => {
  const bucket = new SyntheticBucket();
  const response = await worker.fetch(new Request('http://127.0.0.1/probe',
    { method: 'POST' }), { PROBE_ENABLED: '1', SANDBOX_BUCKET: bucket });
  assert.equal(response.status, 200);
  const flags = await response.json();
  assert.deepEqual(Object.keys(flags).sort(), [
    'uploaded', 'checked', 'reused', 'wrongDigestRejected', 'restored',
    'mismatchDeleteBlocked', 'deletedExact', 'repeatDeleteNoop', 'removed',
  ].sort());
  assert.equal(Object.values(flags).every(Boolean), true);
  assert.equal(bucket.objects.size, 0);
});

test('transport probe exercises the authenticated Worker route and cleans up', async () => {
  const bucket = new SyntheticBucket();
  const response = await worker.fetch(new Request('http://127.0.0.1/probe-transport',
    { method: 'POST' }), { PROBE_ENABLED: '1', SANDBOX_BUCKET: bucket });
  assert.equal(response.status, 200);
  const flags = await response.json();
  assert.deepEqual(Object.keys(flags).sort(), [
    'uploaded', 'reused', 'checked', 'restored', 'wrongMethodBlocked',
    'corruptBodyBlocked', 'deleted', 'removed',
  ].sort());
  assert.equal(Object.values(flags).every(Boolean), true);
  assert.equal(bucket.objects.size, 0);
});
