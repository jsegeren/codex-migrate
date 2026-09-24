const test = require('node:test');
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const { PassThrough } = require('node:stream');
const { makeHandler: appcast } = require('../api/appcast');
const { makeHandler: archive } = require('../api/update-archive');
const { CommerceError } = require('../commerce/config');
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
test('a signed disk-image update is advertised with the disk-image media type', () => {
  const disk = { ...release, filename: release.filename.replace(/\.zip$/, '.dmg'),
    pathname: release.pathname.replace(/\.zip$/, '.dmg'),
    diskImageNotarization: { id: 'abcdef12-1234-1234-1234-123456789abc', status: 'Accepted' } };
  const response = plainResponse();
  appcast(() => ({ ...config, release: disk }))({ method: 'GET' }, response);
  assert.equal(response.statusCode, 200);
  assert.match(response.data, /type="application\/x-apple-diskimage"/);
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

test('canary update requires an exact Founder session and explicit release pin before opening runtime', async () => {
  const candidate = require('../commerce/releases.json')['codex-migrate-0.1.0-build17-quit-guard-arm64'];
  const canaryConfig = { ...config, catalog: { [release.id]: release, [candidate.id]: candidate } };
  const canaryEnv = { COMMERCE_UPDATER_CANARY_RELEASE: candidate.id,
    COMMERCE_UPDATER_CANARY_SESSION: 'cs_live_fixture',
    COMMERCE_UPDATER_CANARY_SHA256: candidate.sha256,
    COMMERCE_UPDATER_CANARY_EXPIRES_AT: new Date(Date.now() + 3600000).toISOString().replace(/\.\d{3}Z$/, 'Z') };
  for (const [headers, environment] of [
    [{ 'x-codex-migrate-canary': candidate.id }, {}],
    [{ 'x-codex-migrate-canary': candidate.id }, { ...canaryEnv, COMMERCE_UPDATER_CANARY_SESSION: 'cs_live_other' }],
    [{ 'x-codex-migrate-canary': candidate.id }, { ...canaryEnv, COMMERCE_UPDATER_CANARY_EXPIRES_AT: '2020-01-01T00:00:00Z' }],
    [{ 'x-codex-migrate-canary': 'other-release' }, canaryEnv],
    [{ 'x-codex-migrate-canary': [candidate.id, candidate.id] }, canaryEnv],
  ]) {
    let loads = 0;
    const handler = archive(async () => { loads++; throw Error('runtime reached'); }, fetch,
      environment, () => canaryConfig);
    const response = plainResponse();
    await handler({ method: 'GET', url: '/api/update-archive',
      headers: { authorization: `Bearer ${token}`, ...headers } }, response);
    assert.equal(response.statusCode, 403);
    assert.equal(loads, 0);
  }
});

test('canary update streams only the exact private candidate; public appcast stays on approved build', async () => {
  const candidate = require('../commerce/releases.json')['codex-migrate-0.1.0-build17-quit-guard-arm64'];
  const canaryConfig = { ...config, catalog: { [release.id]: release, [candidate.id]: candidate } };
  const canaryEnv = { COMMERCE_UPDATER_CANARY_RELEASE: candidate.id,
    COMMERCE_UPDATER_CANARY_SESSION: 'cs_live_fixture',
    COMMERCE_UPDATER_CANARY_SHA256: candidate.sha256,
    COMMERCE_UPDATER_CANARY_EXPIRES_AT: new Date(Date.now() + 3600000).toISOString().replace(/\.\d{3}Z$/, 'Z') };
  const feed = plainResponse();
  appcast(() => canaryConfig)({ method: 'GET' }, feed);
  assert.match(feed.data, /<sparkle:version>15<\/sparkle:version>/);
  assert.doesNotMatch(feed.data, /build17|sandbox\//);
  const bytes = Buffer.from('private canary fixture');
  const signedURL = `https://fixturestore.private.blob.vercel-storage.com/${candidate.pathname}?signed=fixture`;
  let canaryCalls = 0;
  const handler = archive(async () => ({ config: canaryConfig, service: {
    downloadCanary: async (credential, releaseId) => {
      assert.equal(credential, token);
      assert.equal(releaseId, candidate.id);
      canaryCalls++;
      return { release: candidate.id, sha256: candidate.sha256,
        size: candidate.size, filename: candidate.filename, url: signedURL };
    },
  } }), async (url, options) => {
    assert.equal(url.toString(), signedURL);
    assert.equal(options.redirect, 'error');
    return { status: 200, headers: { get: () => String(candidate.size) },
      body: new ReadableStream({ start(controller) { controller.enqueue(bytes); controller.close(); } }) };
  }, canaryEnv, () => canaryConfig);
  const response = new PassThrough();
  response.headers = {};
  response.setHeader = (key, value) => { response.headers[key] = value; };
  const output = [];
  response.on('data', chunk => output.push(chunk));
  await handler({ method: 'GET', url: '/api/update-archive', headers: {
    authorization: `Bearer ${token}`, 'x-codex-migrate-canary': candidate.id,
  } }, response);
  assert.equal(response.statusCode, 200);
  assert.equal(canaryCalls, 1);
  assert.equal(response.headers['Content-Type'], 'application/x-apple-diskimage');
  assert.equal(Buffer.concat(output).toString(), bytes.toString());
  assert.equal(JSON.stringify(response.headers).includes('signed=fixture'), false);
});

test('canary update rejects a changed catalog candidate before signing or streaming', async () => {
  const candidate = require('../commerce/releases.json')['codex-migrate-0.1.0-build17-quit-guard-arm64'];
  const canaryConfig = { ...config, catalog: { [candidate.id]: { ...candidate, accepted: true } } };
  const canaryEnv = { COMMERCE_UPDATER_CANARY_RELEASE: candidate.id,
    COMMERCE_UPDATER_CANARY_SESSION: 'cs_live_fixture',
    COMMERCE_UPDATER_CANARY_SHA256: candidate.sha256,
    COMMERCE_UPDATER_CANARY_EXPIRES_AT: new Date(Date.now() + 3600000).toISOString().replace(/\.\d{3}Z$/, 'Z') };
  let downloads = 0;
  const handler = archive(async () => ({ config: canaryConfig, service: {
    downloadCanary: async () => { downloads++; throw Error('unexpected'); },
  } }), async () => { throw Error('unexpected Blob request'); }, canaryEnv, () => canaryConfig);
  const response = plainResponse();
  await handler({ method: 'GET', url: '/api/update-archive', headers: {
    authorization: `Bearer ${token}`, 'x-codex-migrate-canary': candidate.id,
  } }, response);
  assert.equal(response.statusCode, 503);
  assert.equal(downloads, 0);
  assert.equal(response.headers['Content-Length'], undefined);
});

test('canary update refuses a digest-pinned mismatch before signing or streaming', async () => {
  const candidate = require('../commerce/releases.json')['codex-migrate-0.1.0-build17-quit-guard-arm64'];
  const canaryConfig = { ...config, catalog: { [candidate.id]: candidate } };
  const canaryEnv = { COMMERCE_UPDATER_CANARY_RELEASE: candidate.id,
    COMMERCE_UPDATER_CANARY_SESSION: 'cs_live_fixture',
    COMMERCE_UPDATER_CANARY_SHA256: '0'.repeat(64),
    COMMERCE_UPDATER_CANARY_EXPIRES_AT: new Date(Date.now() + 3600000).toISOString().replace(/\.\d{3}Z$/, 'Z') };
  let downloads = 0;
  const handler = archive(async () => ({ config: canaryConfig, service: {
    downloadCanary: async () => { downloads++; throw Error('unexpected'); },
  } }), async () => { throw Error('unexpected Blob request'); }, canaryEnv, () => canaryConfig);
  const response = plainResponse();
  await handler({ method: 'GET', url: '/api/update-archive', headers: {
    authorization: `Bearer ${token}`, 'x-codex-migrate-canary': candidate.id,
  } }, response);
  assert.equal(response.statusCode, 503);
  assert.equal(downloads, 0);
});

test('paid updater sends no archive when entitlement or upstream delivery fails', async () => {
  const signedURL = `https://fixturestore.private.blob.vercel-storage.com/${release.pathname}?signed=fixture`;
  const responseFor = async (downloadLatest, request) => {
    const handler = archive(async () => ({ config,
      service: { downloadLatest } }), request, {}, () => config);
    const response = plainResponse();
    await handler({ method: 'GET', url: '/api/update-archive',
      headers: { authorization: `Bearer ${token}` } }, response);
    assert.equal(response.data, '');
    assert.equal(response.headers['Content-Length'], undefined);
    assert.equal(response.headers['Content-Disposition'], undefined);
    return response;
  };
  const revoked = await responseFor(async () => {
    throw new CommerceError('purchase_requires_support', 403);
  }, async () => { throw Error('revoked purchase reached Blob'); });
  assert.equal(revoked.statusCode, 403);

  const authorized = async () => ({ release: release.id, sha256: release.sha256,
    size: release.size, filename: release.filename, url: signedURL });
  const failures = [
    async () => { throw Error('network offline'); },
    async () => ({ status: 403, body: null, headers: { get: () => null } }),
    async () => ({ status: 200, body: null, headers: { get: () => null } }),
    async () => ({ status: 200, body: new ReadableStream(),
      headers: { get: () => String(release.size - 1) } }),
  ];
  for (const request of failures) {
    const response = await responseFor(authorized, request);
    assert.equal(response.statusCode, 503);
  }
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

test('paid updater streams a notarized rotation disk image with its correct type', async () => {
  const disk = { ...release, filename: release.filename.replace(/\.zip$/, '.dmg'),
    pathname: release.pathname.replace(/\.zip$/, '.dmg'),
    diskImageNotarization: { id: 'abcdef12-1234-1234-1234-123456789abc', status: 'Accepted' } };
  const diskConfig = { ...config, release: disk };
  const bytes = Buffer.from('synthetic disk-image response');
  disk.size = bytes.length;
  const handler = archive(async () => ({ config: diskConfig, service: {
    downloadLatest: async () => ({ release: disk.id, sha256: disk.sha256,
      filename: disk.filename, size: disk.size,
      url: `https://fixturestore.private.blob.vercel-storage.com/${disk.pathname}?signed=fixture` })
  } }), async () => ({ status: 200, headers: { get: () => String(bytes.length) },
    body: new ReadableStream({ start(controller) { controller.enqueue(bytes); controller.close(); } })
  }), {}, () => diskConfig);
  const response = new PassThrough();
  response.headers = {};
  response.setHeader = (key, value) => { response.headers[key] = value; };
  response.on('data', () => {});
  await handler({ method: 'GET', url: '/api/update-archive',
    headers: { authorization: `Bearer ${token}` } }, response);
  assert.equal(response.statusCode, 200);
  assert.equal(response.headers['Content-Type'], 'application/x-apple-diskimage');
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
