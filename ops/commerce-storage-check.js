#!/usr/bin/env node
// Operator-only transport acceptance. Uploads one synthetic 8 MiB object into
// this product's development-only private store. Never uploads an app/customer file.
const assert = require('node:assert/strict');
const { createHash, randomBytes } = require('node:crypto');
const blob = require('@vercel/blob');
const { privateDownloads } = require('../commerce/artifacts');

async function main() {
  if (process.env.COMMERCE_STORAGE_TEST !== 'yes') throw Error('explicit_opt_in_required');
  const storeId = 'Ksz4f7gOIH2qRu9I';
  const origin = `https://${storeId.toLowerCase()}.private.blob.vercel-storage.com`;
  const auth = { storeId };
  const bytes = randomBytes(8 * 1024 * 1024);
  const hash = b => createHash('sha256').update(b).digest('hex');
  const sha256 = hash(bytes);
  const release = { id: 'transport-fixture', kind: 'sandbox-fixture', source: '0'.repeat(40),
    filename: 'transport-fixture.zip', sha256, size: bytes.length,
    pathname: `sandbox/${sha256}/transport-fixture.zip` };
  // This deliberately synthetic binary tests transport, not ZIP/app validity.
  const uploaded = await blob.put(release.pathname, bytes, { ...auth, access: 'private',
    addRandomSuffix: false, allowOverwrite: false, contentType: 'application/zip',
    abortSignal: AbortSignal.timeout(30000) });
  assert.equal(uploaded.url, `${origin}/${release.pathname}`);
  const anonymous = await fetch(uploaded.url, { redirect: 'error', signal: AbortSignal.timeout(15000) });
  assert.ok([401, 403, 404].includes(anonymous.status)); await anonymous.body?.cancel();
  const download = privateDownloads({ live: false, blobStore: storeId });
  const signed = await download(release);
  const response = await fetch(signed.url, { redirect: 'error', signal: AbortSignal.timeout(30000) });
  assert.equal(response.status, 200);
  const received = Buffer.from(await response.arrayBuffer());
  assert.equal(received.length, bytes.length); assert.equal(hash(received), sha256);
  const disposition = response.headers.get('content-disposition') || '';
  assert.ok(disposition.startsWith('attachment;'));
  const tampered = new URL(signed.url); tampered.pathname += '-other';
  const denied = await fetch(tampered, { redirect: 'error', signal: AbortSignal.timeout(15000) });
  assert.ok([401, 403, 404].includes(denied.status)); await denied.body?.cancel();
  // Verify expiry at the real provider, not only with a mock clock.
  const validUntil = Date.now() + 2000;
  const short = await blob.issueSignedToken({ ...auth, pathname: release.pathname, operations: ['get'], validUntil });
  const expired = await blob.presignUrl(short, { operation: 'get', pathname: release.pathname, access: 'private', validUntil });
  await new Promise(resolve => setTimeout(resolve, Math.max(0, validUntil - Date.now()) + 1500));
  const expiredResponse = await fetch(expired.presignedUrl, { redirect: 'error', signal: AbortSignal.timeout(15000) });
  assert.ok([401, 403].includes(expiredResponse.status)); await expiredResponse.body?.cancel();
  console.log(JSON.stringify({ private: true, bytesVerified: received.length, attachment: true,
    alteredPathDenied: true, expiredLinkDenied: true, fixtureRetained: release.pathname,
    note: 'Storage transport only; no payment, email, app, or migration acceptance.' }));
}
main().catch(error => {
  // Provider errors may embed signed URLs and credentials. Print no error payload.
  console.error(JSON.stringify({ ok: false, code: error instanceof assert.AssertionError ? 'storage_assertion_failed' : 'storage_check_failed' }));
  process.exitCode = 1;
});
