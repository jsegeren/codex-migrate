#!/usr/bin/env node
// Sandbox-only browser transport for a committed fixture or test-only candidate.
// The signed URL remains in process/browser memory and is never printed.
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const { readFile } = require('node:fs/promises');
const releases = require('../commerce/releases.json');
const { validRelease } = require('../commerce/config');
const { privateDownloads } = require('../commerce/artifacts');

let failureStage = 'preflight';

async function verifyBrowserDownload(signed, release) {
  const { chromium } = require('playwright');
  const browser = await chromium.launch({ headless: true, channel: 'chrome' });
  try {
    const page = await browser.newPage({ acceptDownloads: true });
    await page.setContent('<!doctype html><html lang="en"><title>Download check</title><a id="download">Download candidate</a></html>');
    await page.locator('#download').evaluate((link, url) => { link.href = url; }, signed.url);
    const pending = page.waitForEvent('download', { timeout: 30000 });
    await page.locator('#download').click();
    const download = await pending;
    assert.equal(await download.failure(), null);
    assert.equal(download.suggestedFilename(), release.filename);
    const bytes = await readFile(await download.path());
    assert.equal(bytes.length, release.size);
    assert.equal(createHash('sha256').update(bytes).digest('hex'), release.sha256);
    return { browser: 'chrome', trustedClick: true, attachment: true,
      filenameVerified: true, bytesVerified: bytes.length, sha256Verified: true };
  } finally {
    await browser.close();
  }
}

async function main() {
  if (process.env.COMMERCE_BROWSER_DOWNLOAD_TEST !== 'yes' ||
      process.env.COMMERCE_MODE !== 'sandbox') throw new Error('explicit_sandbox_opt_in_required');
  const release = releases[process.env.COMMERCE_RELEASE];
  const storeId = process.env.COMMERCE_BLOB_STORE_ID;
  if (!validRelease(release, false) ||
      !/^[A-Za-z0-9]{8,64}$/.test(storeId || '')) throw new Error('sandbox_fixture_unavailable');

  // Keep the operator-only browser dependency out of ordinary application and
  // test startup. It is loaded only after the explicit sandbox gates pass.
  failureStage = 'private-authorization';
  const signed = await privateDownloads({ live: false, blobStore: storeId })(release);
  failureStage = 'browser-download';
  console.log(JSON.stringify({ ...await verifyBrowserDownload(signed, release), mode: 'sandbox',
    releaseId: release.id, buyerFlowVerified: false }));
}

module.exports = { verifyBrowserDownload, main };

if (require.main === module) main().catch(() => {
  // Provider and browser errors may contain private signed URLs. Never emit them.
  console.error(JSON.stringify({ ok: false, code: 'browser_download_check_failed', stage: failureStage }));
  process.exitCode = 1;
});
