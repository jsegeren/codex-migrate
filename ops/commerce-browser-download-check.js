#!/usr/bin/env node
// Sandbox-only browser acceptance for the committed private delivery fixture.
// The signed URL remains in process/browser memory and is never printed.
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const { readFile } = require('node:fs/promises');
const releases = require('../commerce/releases.json');
const { validRelease } = require('../commerce/config');
const { privateDownloads } = require('../commerce/artifacts');

let failureStage = 'preflight';

async function main() {
  if (process.env.COMMERCE_BROWSER_DOWNLOAD_TEST !== 'yes' ||
      process.env.COMMERCE_MODE !== 'sandbox') throw new Error('explicit_sandbox_opt_in_required');
  const release = releases[process.env.COMMERCE_RELEASE];
  const storeId = process.env.COMMERCE_BLOB_STORE_ID;
  if (!validRelease(release, false) || release.kind !== 'sandbox-fixture' ||
      !/^[A-Za-z0-9]{8,64}$/.test(storeId || '')) throw new Error('sandbox_fixture_unavailable');

  // Keep the operator-only browser dependency out of ordinary application and
  // test startup. It is loaded only after the explicit sandbox gates pass.
  failureStage = 'browser-load';
  const { chromium } = require('playwright');
  failureStage = 'private-authorization';
  const signed = await privateDownloads({ live: false, blobStore: storeId })(release);
  failureStage = 'browser-launch';
  // Use the customer-facing stable browser already installed on this Mac. This
  // keeps the acceptance helper independent of Playwright's downloaded builds.
  const browser = await chromium.launch({ headless: true, channel: 'chrome' });
  try {
    failureStage = 'trusted-click';
    const page = await browser.newPage({ acceptDownloads: true });
    await page.setContent('<!doctype html><html lang="en"><title>Download fixture</title><a id="download">Download fixture</a></html>');
    await page.locator('#download').evaluate((link, url) => { link.href = url; }, signed.url);
    const pending = page.waitForEvent('download', { timeout: 30000 });
    await page.locator('#download').click();
    const download = await pending;
    failureStage = 'attachment-verify';
    assert.equal(await download.failure(), null);
    assert.equal(download.suggestedFilename(), release.filename);
    const path = await download.path();
    const bytes = await readFile(path);
    assert.equal(bytes.length, release.size);
    assert.equal(createHash('sha256').update(bytes).digest('hex'), release.sha256);
    console.log(JSON.stringify({ browser: 'chrome', trustedClick: true,
      attachment: true, filenameVerified: true, bytesVerified: bytes.length,
      sha256Verified: true, mode: 'sandbox' }));
  } finally {
    await browser.close();
  }
}

if (require.main === module) main().catch(() => {
  // Provider and browser errors may contain private signed URLs. Never emit them.
  console.error(JSON.stringify({ ok: false, code: 'browser_download_check_failed', stage: failureStage }));
  process.exitCode = 1;
});
