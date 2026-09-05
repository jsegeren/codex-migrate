const test = require('node:test');
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const { prepareArchive, uploadCandidate, main } = require('../ops/commerce-upload');
const bytes = Buffer.from([0x50, 0x4b, 3, 4, 1, 2, 3]); // Synthetic header, not an app/signature proof.
const receipt = { build_mode: 'release', source_dirty: false, source_revision: 'a'.repeat(40), architecture: 'arm64',
  version: '0.1.0', bundle_version: '1', built_at: '2026-09-05T00:00:00Z',
  notarization: { id: '12345678-1234-1234-1234-123456789abc', status: 'Accepted' },
  artifact: 'Codex-Migrate-0.1.0-build1-arm64.zip', sha256: createHash('sha256').update(bytes).digest('hex') };
const candidate = prepareArchive(receipt, bytes, 'v0.1.0-arm64');
test('upload preparation binds exact bytes and leaves human acceptance false', () => {
  assert.equal(candidate.accepted, false); assert.equal(candidate.size, bytes.length);
  assert.equal(candidate.pathname, `live/${receipt.sha256}/${receipt.artifact}`);
});
for (const patch of [{ build_mode: 'local-test' }, { source_dirty: true }, { source_revision: 'bad' },
  { architecture: 'other' }, { version: '../bad' }, { bundle_version: '0' }, { notarization: { status: 'Submitted' } },
  { artifact: '../secrets.zip' }, { sha256: 'a'.repeat(64) }, { built_at: 'bad' }]) {
  test(`invalid receipt blocked: ${Object.keys(patch)[0]}`, () => {
    assert.throws(() => prepareArchive({ ...receipt, ...patch }, bytes, 'v1'));
  });
}
test('edited bytes and invalid release identifiers fail preparation', () => {
  assert.throws(() => prepareArchive(receipt, Buffer.from('not a zip'), 'v1'));
  assert.throws(() => prepareArchive(receipt, bytes, '../v1'));
});
function fixture(existing = false, wrongBytes = false) {
  let uploaded = existing; let writes = 0;
  const sdk = {
    get: async (url, options) => {
      assert.equal(options.access, 'private'); assert.equal(options.useCache, false);
      if (!uploaded) return null;
      return { statusCode: 200, blob: { url, pathname: candidate.pathname, size: bytes.length, contentType: 'application/zip' },
        stream: new ReadableStream({ start(c) { c.enqueue(wrongBytes ? Buffer.alloc(bytes.length) : bytes); c.close(); } }) };
    },
    put: async (pathname, value, options) => {
      assert.equal(pathname, candidate.pathname); assert.deepEqual(value, bytes);
      assert.equal(options.access, 'private'); assert.equal(options.allowOverwrite, false); assert.equal(options.addRandomSuffix, false);
      writes++; uploaded = true;
    },
  };
  return { sdk, writes: () => writes };
}
test('new private upload is independently read back and verified', async () => {
  const f = fixture(); const result = await uploadCandidate(candidate, bytes, f.sdk);
  assert.equal(result.bytesVerified, bytes.length); assert.equal(result.accepted, false); assert.equal(f.writes(), 1);
});
test('retry reuses exact existing verified bytes without overwriting', async () => {
  const f = fixture(true); await uploadCandidate(candidate, bytes, f.sdk); assert.equal(f.writes(), 0);
});
test('corrupt existing object stops without overwriting or granting acceptance', async () => {
  const f = fixture(true, true); await assert.rejects(uploadCandidate(candidate, bytes, f.sdk), /checksum/); assert.equal(f.writes(), 0);
});
test('edited upload candidate is rejected before network access', async () => {
  const f = fixture(); await assert.rejects(uploadCandidate({ ...candidate, accepted: true }, bytes, f.sdk)); assert.equal(f.writes(), 0);
});
test('missing and duplicate arguments never upload', async () => {
  await assert.rejects(main([]), /required/);
  await assert.rejects(main(['--apply', '--apply']), /arguments/);
});
