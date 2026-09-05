const test = require('node:test');
const assert = require('node:assert/strict');
const { privateDownloads } = require('../commerce/artifacts');
const { validRelease } = require('../commerce/config');
const release = { id: 'fixture-1', kind: 'sandbox-fixture', sha256: 'a'.repeat(64), source: 'b'.repeat(40),
  filename: 'fixture.zip', size: 8000000, pathname: `sandbox/${'a'.repeat(64)}/fixture.zip` };
const config = { live: false, blobStore: 'fixturestore' };
const expected = `https://fixturestore.private.blob.vercel-storage.com/${release.pathname}`;
const now = 1788580000000;
function fixture() {
  const calls = [];
  const sdk = {
    head: async (...args) => { calls.push(['head', ...args]); return { url: expected, pathname: release.pathname, size: release.size, contentType: 'application/zip' }; },
    issueSignedToken: async options => { calls.push(['issue', options]); return { delegationToken: 'fixture-delegation', clientSigningToken: 'fixture-private', validUntil: options.validUntil }; },
    presignUrl: async (...args) => { calls.push(['sign', ...args]); return { presignedUrl: `${expected}?signed=fixture` }; },
  };
  return { sdk, calls, download: privateDownloads(config, {}, sdk, () => now) };
}
test('private download issues only exact-file GET access for five minutes', async () => {
  const f = fixture(); const result = await f.download(release);
  assert.deepEqual(Object.keys(result).sort(), ['expiresAt', 'url']);
  assert.equal(result.expiresAt, now + 300000);
  const issuance = f.calls.find(c => c[0] === 'issue')[1];
  assert.deepEqual(issuance.operations, ['get']);
  assert.equal(issuance.pathname, release.pathname);
  assert.equal(issuance.storeId, config.blobStore);
  assert.equal(JSON.stringify(result).includes('fixture-private'), false);
  assert.equal(f.calls.find(c => c[0] === 'sign')[2].access, 'private');
});
for (const [name, patch] of [
  ['public URL', { url: 'https://github.com/jsegeren/codex-migrate/releases/download/v1/app.zip' }],
  ['path escape', { pathname: '../app.zip' }], ['other environment', { pathname: release.pathname.replace('sandbox', 'live') }],
  ['wrong digest path', { pathname: release.pathname.replace('aaaa', 'bbbb') }],
  ['oversized', { size: 101 * 1024 * 1024 }], ['empty', { size: 0 }],
  ['unsafe filename', { filename: '../app.zip' }], ['unreviewed kind', { kind: 'unsigned' }],
]) test(`${name} is rejected before storage access`, async () => {
  const f = fixture(); await assert.rejects(f.download({ ...release, ...patch }), /release_unavailable/);
  assert.equal(f.calls.length, 0);
});
test('live releases require signed and accepted evidence fields, separate from sandbox', () => {
  assert.equal(validRelease(release, true), false);
  const live = { ...release, pathname: release.pathname.replace('sandbox', 'live'), kind: 'signed-notarized' };
  assert.equal(validRelease(live, true), false);
  assert.equal(validRelease({ ...live, accepted: true }, true), true);
});
for (const patch of [{ size: 1 }, { url: expected.replace('.private.', '.public.') },
  { pathname: 'other.zip' }, { contentType: 'text/html' }]) {
  test(`storage metadata mismatch blocks signing: ${Object.keys(patch)[0]}`, async () => {
    const f = fixture(); f.sdk.head = async () => ({ url: expected, pathname: release.pathname, size: release.size, contentType: 'application/zip', ...patch });
    await assert.rejects(f.download(release), /release_unavailable/);
    assert.equal(f.calls.length, 0);
  });
}
for (const until of [now, now - 1, now + 300001, undefined]) test(`invalid delegation expiry ${until} blocks delivery`, async () => {
  const f = fixture(); f.sdk.issueSignedToken = async () => ({ validUntil: until });
  await assert.rejects(f.download(release), /release_unavailable/);
  assert.equal(f.calls.some(c => c[0] === 'sign'), false);
});
for (const url of ['https://evil.example/app.zip?token=1', expected.replace('.private.', '.public.') + '?token=1',
  expected + '/other?token=1', expected, expected + '?token=1#fragment']) test('unexpected signed URL is not returned', async () => {
  const f = fixture(); f.sdk.presignUrl = async () => ({ presignedUrl: url });
  await assert.rejects(f.download(release), /release_unavailable/);
});
