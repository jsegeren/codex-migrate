const test = require('node:test');
const assert = require('node:assert/strict');
const { PassThrough } = require('node:stream');
const { makeHandler } = require('../api/purchase-archive');
const { tokenFor } = require('../commerce/service');

const release = { ...require('../commerce/releases.json')['beta-build16-arm64'], size: 25 };
const original = { ...require('../commerce/releases.json')['beta-build15-arm64'], size: 22 };
const config = { live: true, mode: 'live', secret: 'c'.repeat(64), release,
  catalog: { [release.id]: release, [original.id]: original }, blobStore: 'fixturestore' };
const credential = tokenFor('cs_live_fixture', config);
const origin = 'https://migrate.segeren.com';
const signed = entry => `https://fixturestore.private.blob.vercel-storage.com/${entry.pathname}?signed=fixture`;
const response = () => {
  const res = new PassThrough();
  res.headers = {};
  res.setHeader = (key, value) => { res.headers[key] = value; };
  return res;
};
const request = (version = 'latest', token = credential) => ({ method: 'POST',
  url: '/api/purchase-archive', headers: { origin,
    'content-type': 'application/x-www-form-urlencoded' },
  body: new URLSearchParams({ credential: token, version }).toString() });

test('buyer download streams latest and original through the first-party endpoint', async () => {
  for (const [version, entry] of [['latest', release], ['original', original]]) {
    const bytes = Buffer.alloc(entry.size, 0x5a);
    const service = {
      downloadLatest: async token => { assert.equal(token, credential); return {
        release: entry.id, sha256: entry.sha256, filename: entry.filename,
        size: entry.size, url: signed(entry) }; },
      download: async token => { assert.equal(token, credential); return {
        release: entry.id, sha256: entry.sha256, filename: entry.filename,
        size: entry.size, url: signed(entry) }; },
    };
    const handler = makeHandler(async () => ({ config, service }), async url => {
      assert.equal(url.toString(), signed(entry));
      return { status: 200, headers: { get: () => String(entry.size) },
        body: new ReadableStream({ start(controller) { controller.enqueue(bytes); controller.close(); } }) };
    }, {}, () => config);
    const res = response();
    const received = [];
    res.on('data', chunk => received.push(chunk));
    await handler(request(version), res);
    assert.equal(res.statusCode, 200);
    assert.equal(res.headers['Content-Length'], String(entry.size));
    assert.equal(res.headers['Content-Disposition'], `attachment; filename="${entry.filename}"`);
    assert.deepEqual(Buffer.concat(received), bytes);
    assert.equal(JSON.stringify(res.headers).includes('signed=fixture'), false);
  }
});

test('buyer archive rejects bad origin, forged authority and URL query before runtime access', async () => {
  let loads = 0;
  const handler = makeHandler(async () => { loads++; throw Error('unexpected'); }, fetch, {}, () => config);
  const bad = [
    { ...request(), headers: { ...request().headers, origin: 'https://evil.example' } },
    request('latest', `cs_live_fixture.${'0'.repeat(64)}`),
    { ...request(), url: '/api/purchase-archive?credential=leak' },
  ];
  for (const req of bad) {
    const res = response();
    await handler(req, res);
    assert.notEqual(res.statusCode, 200);
  }
  assert.equal(loads, 0);
});

test('buyer archive refuses a mismatched release and never fetches its URL', async () => {
  let fetched = false;
  const handler = makeHandler(async () => ({ config, service: { downloadLatest: async () => ({
    release: release.id, sha256: original.sha256, filename: release.filename,
    size: release.size, url: signed(release) }) } }), async () => { fetched = true; }, {}, () => config);
  const res = response();
  await handler(request(), res);
  assert.equal(res.statusCode, 503);
  assert.equal(fetched, false);
});
