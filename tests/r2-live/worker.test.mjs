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

test('native fixture grants only narrow loopback object access', async () => {
  const bucket = new SyntheticBucket();
  const data = crypto.getRandomValues(new Uint8Array(4096));
  const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', data)),
    byte => byte.toString(16).padStart(2, '0')).join('');
  const key = `accounts/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/` +
    `vaults/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/objects/` +
    `${digest.slice(0, 2)}/${digest.slice(2)}.cvchunk`;
  const env = { PROBE_ENABLED: '1', SANDBOX_BUCKET: bucket };
  const grant = async (method, scopedKey = key) => {
    const body = JSON.stringify({ method, key: scopedKey,
      bytes: data.byteLength, sha256: digest });
    return worker.fetch(new Request('http://127.0.0.1/native-grant', {
      method: 'POST', headers: { 'Content-Length': String(Buffer.byteLength(body)) },
      body,
    }), env);
  };
  const foreign = key.replace('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'cccccccc-cccc-4ccc-8ccc-cccccccccccc');
  assert.equal((await grant('PUT', foreign)).status, 400);
  assert.equal((await worker.fetch(new Request('https://example.test/native-grant', {
    method: 'POST', body: '{}', headers: { 'Content-Length': '2' },
  }), env)).status, 404);
  const put = await (await grant('PUT')).json();
  const response = await worker.fetch(new Request(`http://127.0.0.1/v1/object/${key}`, {
    method: 'PUT', headers: { Authorization: `Bearer ${put.token}`,
      'Content-Length': String(data.byteLength) }, body: data,
  }), env);
  assert.equal(response.status, 201);
  const remove = await (await grant('DELETE')).json();
  assert.equal((await worker.fetch(new Request(`http://127.0.0.1/v1/object/${key}`, {
    method: 'DELETE', headers: { Authorization: `Bearer ${remove.token}`,
      'Content-Length': '0' }, body: new Uint8Array(0),
  }), env)).status, 204);
  assert.equal(bucket.objects.size, 0);
});

test('encrypted roundtrip fixture grants only the four scoped object classes', async () => {
  const env = { PROBE_ENABLED: '1', SANDBOX_BUCKET: new SyntheticBucket() };
  const prefix = 'accounts/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/' +
    'vaults/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/';
  const snapshot = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
  const digest = 'a'.repeat(64);
  const grant = async (key, bytes = 100) => {
    const body = JSON.stringify({ method: 'HEAD', key, bytes, sha256: digest });
    return worker.fetch(new Request('http://127.0.0.1/native-grant', {
      method: 'POST', headers: { 'Content-Length': String(Buffer.byteLength(body)) },
      body,
    }), env);
  };
  for (const key of [
    `metadata/${snapshot}.json`,
    `objects/aa/${'a'.repeat(62)}.cvchunk`,
    `manifests/${snapshot}.cvmanifest`,
    `refs/${snapshot}.json`,
  ]) {
    assert.equal((await grant(prefix + key)).status, 200, key);
  }
  assert.equal((await grant(prefix + `auth/${snapshot}.json`)).status, 400);
  assert.equal((await grant(prefix + `metadata/${snapshot}.json`, 1024 * 1024 + 1)).status, 400);
});
