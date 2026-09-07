#!/usr/bin/env node
// Operator-only exact signed-candidate browser transport. Not a buyer entitlement
// or a release-acceptance bypass: no catalog, payment or application state writes.
const assert = require('node:assert/strict');
const blob = require('@vercel/blob');
const uploader = require('./commerce-upload');
const { verifyBrowserDownload } = require('./commerce-browser-download-check');
const STORE = 'Ksz4f7gOIH2qRu9I';
const ORIGIN = `https://${STORE.toLowerCase()}.private.blob.vercel-storage.com`;
let stage = 'preflight';

async function main(args = process.argv.slice(2), env = process.env,
                    sdk = blob, browser = verifyBrowserDownload, plan = uploader.main) {
  if (env.COMMERCE_CANDIDATE_DOWNLOAD_TEST !== 'yes' || args.includes('--apply')) {
    throw Error('explicit_read_only_candidate_opt_in_required');
  }
  if (browser === verifyBrowserDownload) {
    stage = 'browser-runtime';
    require.resolve('playwright'); // Fail before requesting a private link.
  }
  // Existing uploader performs only its local, receipt-bound plan here.
  stage = 'receipt';
  const prepared = await plan(args);
  assert.equal(prepared.planOnly, true);
  assert.equal(prepared.uploaded, false);
  const release = prepared.candidate;
  assert.equal(release.accepted, false);
  assert.equal(release.kind, 'signed-notarized');
  const auth = { storeId: STORE };
  const expected = `${ORIGIN}/${release.pathname}`;
  stage = 'private-metadata';
  const metadata = await sdk.head(expected, { ...auth, abortSignal: AbortSignal.timeout(15000) });
  assert.equal(metadata.url, expected);
  assert.equal(metadata.pathname, release.pathname);
  assert.equal(metadata.size, release.size);
  assert.equal(metadata.contentType, 'application/zip');
  const validUntil = Date.now() + 120000;
  stage = 'link-authorization';
  const token = await sdk.issueSignedToken({ ...auth, pathname: release.pathname,
    operations: ['get'], validUntil, abortSignal: AbortSignal.timeout(15000) });
  assert.ok(Number.isSafeInteger(token.validUntil) && token.validUntil <= validUntil && token.validUntil > Date.now());
  const signed = await sdk.presignUrl(token, { operation: 'get', pathname: release.pathname,
    access: 'private', validUntil: token.validUntil });
  const url = new URL(signed.presignedUrl);
  assert.equal(url.origin, ORIGIN);
  assert.equal(url.pathname, '/' + release.pathname);
  assert.ok(url.search && !url.username && !url.password && !url.hash);
  stage = 'browser-download';
  const result = await browser({ url: url.toString() }, release);
  return { ...result, releaseId: release.id, accepted: false,
    scope: 'operator browser transport only; no purchase, clean-Mac launch or migration proof' };
}

module.exports = { main };
if (require.main === module) main().then(result => console.log(JSON.stringify(result))).catch(() => {
  console.error(JSON.stringify({ ok: false, stage, code: 'candidate_download_failed' }));
  process.exitCode = 1;
});
