const blob = require('@vercel/blob');
const { CommerceError, validRelease } = require('./config');

// Every link is GET-only, bound to one content-addressed object, and expires
// within five minutes. No signing key or whole-store delegation reaches clients.
function privateDownloads(config, env = process.env, sdk = blob, clock = Date.now) {
  const auth = { storeId: config.blobStore,
    ...(env.COMMERCE_BLOB_READ_WRITE_TOKEN ? { token: env.COMMERCE_BLOB_READ_WRITE_TOKEN } : {}) };
  return async release => {
    if (!validRelease(release, config.live)) throw new CommerceError('release_unavailable');
    const origin = `https://${config.blobStore.toLowerCase()}.private.blob.vercel-storage.com`;
    const expected = `${origin}/${release.pathname}`;
    const metadata = await sdk.head(expected, { ...auth, abortSignal: AbortSignal.timeout(8000) });
    if (metadata.url !== expected || metadata.pathname !== release.pathname ||
        metadata.size !== release.size || metadata.contentType !== 'application/zip') {
      throw new CommerceError('release_unavailable');
    }
    const expiresAt = clock() + 5 * 60 * 1000;
    const delegation = await sdk.issueSignedToken({ ...auth, pathname: release.pathname,
      operations: ['get'], validUntil: expiresAt, abortSignal: AbortSignal.timeout(8000) });
    if (!Number.isSafeInteger(delegation.validUntil) || delegation.validUntil > expiresAt || delegation.validUntil <= clock()) {
      throw new CommerceError('release_unavailable');
    }
    const { presignedUrl } = await sdk.presignUrl(delegation, { operation: 'get',
      pathname: release.pathname, access: 'private', validUntil: delegation.validUntil });
    const url = new URL(presignedUrl);
    if (url.origin !== origin || url.pathname !== `/${release.pathname}` ||
        url.username || url.password || url.hash || !url.search) throw new CommerceError('release_unavailable');
    return { url: url.toString(), expiresAt: delegation.validUntil };
  };
}
module.exports = { privateDownloads };
