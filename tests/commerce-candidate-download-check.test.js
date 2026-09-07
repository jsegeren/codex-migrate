const test = require('node:test');
const assert = require('node:assert/strict');
const { main } = require('../ops/commerce-candidate-download-check');
const origin = 'https://ksz4f7goih2qru9i.private.blob.vercel-storage.com';
function fixture() {
  const candidate = { id: 'test', accepted: false, kind: 'signed-notarized', size: 50,
    pathname: 'live/digest/candidate.zip' };
  const calls = [];
  return { candidate, calls, plan: async () => ({ planOnly: true, uploaded: false, candidate }),
    browser: async (signed, release) => { calls.push('browser'); assert.equal(release.accepted, false);
      return { bytesVerified: 50 }; },
    sdk: { head: async () => ({ url: origin + '/' + candidate.pathname, pathname: candidate.pathname,
      size: 50, contentType: 'application/zip' }),
      issueSignedToken: async options => { calls.push(options); return { validUntil: options.validUntil }; },
      presignUrl: async () => ({ presignedUrl: origin + '/' + candidate.pathname + '?PRIVATE_SECRET' }) } };
}
const enabled = { COMMERCE_CANDIDATE_DOWNLOAD_TEST: 'yes' };
test('no opt-in or upload request performs any provider operation', async () => {
  for (const [args, env] of [[[], {}], [['--apply'], enabled]]) {
    const f = fixture();
    await assert.rejects(main(args, env, f.sdk, f.browser, f.plan));
    assert.deepEqual(f.calls, []);
  }
});
test('exact operator download never accepts a release or exports its bearer URL', async () => {
  const f = fixture();
  const result = await main([], enabled, f.sdk, f.browser, f.plan);
  assert.equal(result.accepted, false);
  assert.equal(result.bytesVerified, 50);
  assert.deepEqual(f.calls[0].operations, ['get']);
  assert.ok(!JSON.stringify(result).includes('PRIVATE_SECRET'));
});
test('mismatched metadata or origin fails before browser navigation', async () => {
  for (const fault of ['size', 'origin', 'expiry']) {
    const f = fixture();
    if (fault === 'size') f.sdk.head = async () => ({ size: 99 });
    if (fault === 'origin') f.sdk.presignUrl = async () => ({ presignedUrl: 'https://other.example/file?secret' });
    if (fault === 'expiry') f.sdk.issueSignedToken = async () => ({ validUntil: Date.now() + 999999 });
    await assert.rejects(main([], enabled, f.sdk, f.browser, f.plan));
    assert.ok(!f.calls.includes('browser'));
  }
});
