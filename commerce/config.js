const releases = require('./releases.json');

const SITE = 'https://migrate.segeren.com';
class CommerceError extends Error {
  constructor(code, status = 503) { super(code); this.code = code; this.status = status; }
}
function validRelease(release, live) {
  return Boolean(release && /^[a-f0-9]{64}$/.test(release.sha256 || '') &&
    /^[a-f0-9]{40}$/.test(release.source || '') && /^[A-Za-z0-9._-]{1,100}$/.test(release.id || '') &&
    release.url === undefined && /^[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.zip$/.test(release.filename || '') &&
    Number.isSafeInteger(release.size) && release.size > 0 && release.size <= 100 * 1024 * 1024 &&
    release.pathname === `${live ? 'live' : 'sandbox'}/${release.sha256}/${release.filename}` &&
    (live ? release.kind === 'signed-notarized' && release.accepted === true : release.kind === 'sandbox-fixture'));
}
function configuration(env = process.env, catalog = releases) {
  const mode = env.COMMERCE_MODE;
  if (!['sandbox', 'live'].includes(mode)) throw new CommerceError('checkout_closed');
  const live = mode === 'live';
  const prefix = live ? 'live' : 'test';
  const key = env.COMMERCE_STRIPE_KEY;
  const secret = env.COMMERCE_LINK_SECRET;
  if (!new RegExp(`^(rk|sk)_${prefix}_[A-Za-z0-9]+$`).test(key || '') ||
      !/^[a-f0-9]{64}$/.test(secret || '') ||
      !/^acct_[A-Za-z0-9]+$/.test(env.COMMERCE_STRIPE_ACCOUNT || '') ||
      !/^prod_[A-Za-z0-9]+$/.test(env.COMMERCE_PRODUCT || '') ||
      !/^price_[A-Za-z0-9]+$/.test(env.COMMERCE_PRICE || '') ||
      !/^[A-Za-z0-9]{8,64}$/.test(env.COMMERCE_BLOB_STORE_ID || '') ||
      !/^whsec_[A-Za-z0-9]+$/.test(env.COMMERCE_WEBHOOK_SECRET || '')) {
    throw new CommerceError('commerce_not_configured');
  }
  // No release is enabled merely by an environment toggle. A reviewed manifest
  // must be committed after the exact archive has passed release acceptance.
  const release = catalog[env.COMMERCE_RELEASE];
  if (!validRelease(release, live) || release.id !== env.COMMERCE_RELEASE) {
    throw new CommerceError('release_unavailable');
  }
  return { mode, live, key, secret, release, catalog, site: SITE,
    blobStore: env.COMMERCE_BLOB_STORE_ID,
    account: env.COMMERCE_STRIPE_ACCOUNT, product: env.COMMERCE_PRODUCT,
    price: env.COMMERCE_PRICE, webhookSecret: env.COMMERCE_WEBHOOK_SECRET };
}
module.exports = { configuration, CommerceError, SITE, validRelease };
