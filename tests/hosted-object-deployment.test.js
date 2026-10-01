const test = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const { randomBytes, createHash } = require('node:crypto');
const { signObjectCapability } = require('../hosted/object_capability');

test('explicit storage deployment pins only the sandbox and real authenticated handler', () => {
  const configPath = resolve(__dirname, '../hosted/r2-sandbox.wrangler.jsonc');
  const config = JSON.parse(readFileSync(configPath, 'utf8'));
  assert.deepEqual(config, {
    name: 'codex-backup-service-sandbox',
    account_id: 'c6c00211d9bf8d7b4f493b2a6d352b9a',
    main: './r2_object_worker.mjs', compatibility_date: '2026-09-30',
    workers_dev: true, preview_urls: false,
    observability: { enabled: false },
    r2_buckets: [{ binding: 'HOSTED_BUCKET',
      bucket_name: 'codex-vault-sandbox-20260927' }],
  });
  assert.equal(resolve(configPath, '..', config.main),
    resolve(__dirname, '../hosted/r2_object_worker.mjs'));
});

test('deployed entry point is dark without both bindings and rejects probes and unsigned access', async () => {
  const worker = (await import('../hosted/r2_object_worker.mjs')).default;
  let storageCalls = 0;
  const bucket = new Proxy({}, { get() { storageCalls++; throw Error('must not touch R2'); } });
  const secret = randomBytes(32).toString('base64url');
  const paths = ['/probe', '/probe-transport', '/native-grant', '/roundtrip-grant',
    '/v1/verify-batch', '/v1/object/accounts/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'];
  for (const path of paths) {
    const request = () => new Request('https://backup.example.test' + path,
      { method: 'POST' });
    for (const env of [{}, { HOSTED_BUCKET: bucket },
      { CAPABILITY_SIGNING_KEY: secret },
      { HOSTED_BUCKET: bucket, CAPABILITY_SIGNING_KEY: 'invalid' }]) {
      assert.equal((await worker.fetch(request(), env)).status, 404);
    }
    const response = await worker.fetch(request(), {
      HOSTED_BUCKET: bucket, CAPABILITY_SIGNING_KEY: secret,
    });
    assert.ok([400, 403, 404].includes(response.status));
    assert.equal(response.headers.get('Cache-Control'), 'private, no-store');
    assert.equal(await response.text(), '');
  }
  assert.equal(storageCalls, 0);
});

test('entry point authenticates exact object access before contacting storage', async () => {
  const worker = (await import('../hosted/r2_object_worker.mjs')).default;
  const secret = randomBytes(32);
  const ciphertext = Buffer.from('synthetic opaque ciphertext');
  const sha256 = createHash('sha256').update(ciphertext).digest('hex');
  const key = 'accounts/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/' +
    'vaults/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/objects/' +
    sha256.slice(0, 2) + '/' + sha256.slice(2) + '.cvchunk';
  const item = { key, bytes: ciphertext.length, sha256 };
  let reads = 0;
  const env = { CAPABILITY_SIGNING_KEY: secret.toString('base64url'),
    HOSTED_BUCKET: { async head(requested) {
      reads++;
      assert.equal(requested, key);
      return null;
    } } };
  const token = await signObjectCapability('HEAD', item, secret);
  const request = (method, authorization, suffix = '') => new Request(
    'https://backup.example.test/v1/object/' + key + suffix,
    { method, headers: authorization ? { Authorization: 'Bearer ' + authorization } : {} });
  for (const forbidden of [request('HEAD'), request('HEAD', 'forged.token'),
    request('GET', token), request('HEAD', token, '?probe=1')]) {
    assert.ok([403, 404].includes((await worker.fetch(forbidden, env)).status));
  }
  assert.equal(reads, 0);
  assert.equal((await worker.fetch(request('HEAD', token), env)).status, 404);
  assert.equal(reads, 1);
});
