const test = require('node:test');
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const { PassThrough } = require('node:stream');
const { makeHandler: appcast } = require('../api/appcast');
const { makeHandler: archive } = require('../api/update-archive');
const { tokenFor } = require('../commerce/service');
const release = { ...require('../commerce/releases.json')['beta-build15-arm64'],
  sparkleSignature: Buffer.alloc(64, 7).toString('base64') };
const config = { live: true, mode: 'live', secret: 'c'.repeat(64), release,
  blobStore: 'fixturestore' };
const token = tokenFor('cs_live_fixture', config);

function plainResponse() {
  return { headers: {}, setHeader(key, value) { this.headers[key] = value; },
    end(data = '') { this.data = data; } };
}

test('appcast advertises only an approved, signed, compatible archive', () => {
  const handler = appcast(() => config);
  const response = plainResponse();
  handler({ method: 'GET' }, response);
  assert.equal(response.statusCode, 200);
  assert.match(response.data, /<sparkle:version>15<\/sparkle:version>/);
  assert.match(response.data, /sparkle:edSignature=/);
  assert.match(response.data, /https:\/\/migrate\.segeren\.com\/api\/update-archive/);
  assert.equal(response.data.includes('private.blob'), false);
  assert.equal(response.data.includes(token), false);
  for (const changed of [{ ...release, sparkleSignature: undefined },
    { ...release, accepted: false }, { ...release, filename: 'Codex-Migrate-0.1.0-build15-x86_64.zip' }]) {
    const failed = plainResponse();
    appcast(() => ({ ...config, release: changed }))({ method: 'GET' }, failed);
    assert.equal(failed.statusCode, 503);
  }
});

test('update archive rejects missing bearer authority before opening runtime', async () => {
  let loads = 0;
  const handler = archive(async () => { loads++; throw Error('unexpected'); }, fetch, {}, () => config);
  const response = plainResponse();
  await handler({ method: 'GET', url: '/api/update-archive', headers: {} }, response);
  assert.equal(response.statusCode, 403);
  assert.equal(loads, 0);
});

test('update archive rejects a forged bearer before opening the runtime', async () => {
  let loads = 0;
  const handler = archive(async () => { loads++; throw Error('unexpected'); }, fetch, {}, () => config);
  const response = plainResponse();
  await handler({ method: 'GET', url: '/api/update-archive',
    headers: { authorization: `Bearer cs_live_fixture.${'0'.repeat(64)}` } }, response);
  assert.equal(response.statusCode, 403);
  assert.equal(loads, 0);
});

test('update archive streams the approved private build without exposing its blob URL', async () => {
  const bytes = Buffer.from('signed archive fixture');
  const updateConfig = { ...config, release: { ...release, size: bytes.length } };
  const signedURL = `https://fixturestore.private.blob.vercel-storage.com/${release.pathname}?signed=fixture`;
  let requested;
  const handler = archive(async () => ({ config: updateConfig,
    service: { downloadLatest: async credential => {
      assert.equal(credential, token);
      return { updateAvailable: false, release: release.id, sha256: release.sha256,
        size: bytes.length, filename: release.filename, url: signedURL };
    } } }), async (url, options) => {
    requested = url.toString();
    assert.equal(options.redirect, 'error');
    return { status: 200, headers: { get: () => String(bytes.length) },
      body: new ReadableStream({ start(controller) { controller.enqueue(bytes); controller.close(); } }) };
  }, {}, () => updateConfig);
  const response = new PassThrough();
  response.headers = {};
  response.setHeader = (key, value) => { response.headers[key] = value; };
  const output = [];
  response.on('data', chunk => output.push(chunk));
  await handler({ method: 'GET', url: '/api/update-archive', headers: { authorization: `Bearer ${token}` } }, response);
  assert.equal(response.statusCode, 200);
  assert.equal(requested, signedURL);
  assert.equal(Buffer.concat(output).toString(), bytes.toString());
  assert.equal(JSON.stringify(response.headers).includes('signed=fixture'), false);
});

test('update archive streams an app-sized release without buffering or changing bytes', async () => {
  const chunk = Buffer.alloc(64 * 1024, 0x5a);
  const count = 147;
  const size = chunk.length * count;
  const digest = createHash('sha256');
  for (let i = 0; i < count; i++) digest.update(chunk);
  const updateConfig = { ...config, release: { ...release, size } };
  const signedURL = `https://fixturestore.private.blob.vercel-storage.com/${release.pathname}?signed=fixture`;
  const handler = archive(async () => ({ config: updateConfig,
    service: { downloadLatest: async () => ({ release: release.id, sha256: release.sha256,
      size, filename: release.filename, url: signedURL }) } }), async () => ({
    status: 200, headers: { get: () => String(size) },
    body: new ReadableStream({
      pull(controller) {
        if (this.sent === count) { controller.close(); return; }
        controller.enqueue(chunk);
        this.sent = (this.sent || 0) + 1;
      },
    }),
  }), {}, () => updateConfig);
  const response = new PassThrough();
  response.headers = {};
  response.setHeader = (key, value) => { response.headers[key] = value; };
  const received = createHash('sha256');
  let receivedBytes = 0;
  response.on('data', data => { received.update(data); receivedBytes += data.length; });
  await handler({ method: 'GET', url: '/api/update-archive',
    headers: { authorization: `Bearer ${token}` } }, response);
  assert.equal(response.statusCode, 200);
  assert.equal(response.headers['Content-Length'], String(size));
  assert.equal(receivedBytes, size);
  assert.equal(received.digest('hex'), digest.digest('hex'));
});
