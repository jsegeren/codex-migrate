// Opt-in deployment-time provisioning check. No public route, payment, email,
// schema mutation or release-catalog bypass. Fixture transport is not app acceptance.
const { createHash } = require('node:crypto');
const EXPECTED = Object.freeze({
  account: 'acct_1Rkc6eJfbWpcJIZb', product: 'prod_VCxpogUxaT0OeT',
  price: 'price_1UCXtaJfbWpcJIZbp9W60sIv', store: 'Ksz4f7gOIH2qRu9I',
  database: 'ep-holy-surf-av4n95ee-pooler.c-11.us-east-1.aws.neon.tech',
});
const fixture = require('../commerce/releases.json')['sandbox-delivery-2026-09-05'];

function required(condition) { if (!condition) throw new Error('preflight_check_failed'); }
function validateEnvironment(env) {
  required(env.VERCEL_ENV === 'production' && env.COMMERCE_MODE === 'live' &&
    env.COMMERCE_CHECKOUT_OPEN === 'no');
  required(env.COMMERCE_STRIPE_ACCOUNT === EXPECTED.account &&
    env.COMMERCE_PRODUCT === EXPECTED.product && env.COMMERCE_PRICE === EXPECTED.price &&
    env.COMMERCE_BLOB_STORE_ID === EXPECTED.store);
  required(/^rk_live_[A-Za-z0-9]+$/.test(env.COMMERCE_STRIPE_KEY || '') &&
    /^[a-f0-9]{64}$/.test(env.COMMERCE_LINK_SECRET || '') &&
    /^whsec_[A-Za-z0-9]+$/.test(env.COMMERCE_WEBHOOK_SECRET || ''));
  const url = new URL(env.COMMERCE_DATABASE_URL);
  required(['postgres:', 'postgresql:'].includes(url.protocol) &&
    url.hostname === EXPECTED.database && url.pathname === '/neondb' &&
    url.searchParams.get('sslmode') === 'require');
}

function dependencies(env) {
  const Stripe = require('stripe');
  const { database } = require('../commerce/database');
  const { sql } = require('drizzle-orm');
  const { privateDownloads } = require('../commerce/artifacts');
  const stripe = new Stripe(env.COMMERCE_STRIPE_KEY,
    { apiVersion: '2025-03-31.basil', maxNetworkRetries: 0, timeout: 10000 });
  return {
    account: () => stripe.accounts.retrieve(),
    product: () => stripe.products.retrieve(EXPECTED.product),
    price: () => stripe.prices.retrieve(EXPECTED.price),
    database: async () => {
      const db = database(env.COMMERCE_DATABASE_URL);
      return (await db.execute(sql`select name, mode from commerce_environment`)).rows;
    },
    signFixture: () => privateDownloads({ live: false, blobStore: EXPECTED.store }, env)(fixture),
    request: (url) => fetch(url, { redirect: 'error', signal: AbortSignal.timeout(15000) }),
  };
}

async function preflight(env = process.env, makeDependencies = dependencies) {
  if (env.COMMERCE_PREFLIGHT !== 'yes') return { skipped: true };
  let stage = 'configuration';
  try {
    validateEnvironment(env);
    const deps = makeDependencies(env);
    stage = 'stripe-account';
    const account = await deps.account();
    required(account.id === EXPECTED.account);
    stage = 'stripe-product';
    const product = await deps.product();
    required(product.id === EXPECTED.product && product.livemode === true && product.active === true);
    stage = 'stripe-price';
    const price = await deps.price();
    required(price.id === EXPECTED.price && price.product === EXPECTED.product &&
      price.livemode === true && price.active === true && price.unit_amount === 5000 &&
      price.currency === 'usd' && price.type === 'one_time' && price.recurring == null);
    stage = 'database';
    const rows = await deps.database();
    required(rows.length === 1 && rows[0].name === 'codex-migrate-commerce' && rows[0].mode === 'live');
    stage = 'private-fixture';
    const size = await verifyFixture(deps);
    return { configured: true, stripeCatalog: true, liveDatabase: true,
      privateFixtureBytes: size, anonymousAccessDenied: true, checkoutOpen: false,
      note: 'Provisioning only; no live payment, email, signed-app or migration acceptance.' };
  } catch {
    const error = new Error('commerce_preflight_failed'); error.stage = stage; throw error;
  }
}

async function verifyFixture(deps, artifact = fixture) {
  const signed = await deps.signFixture();
  const response = await deps.request(signed.url);
  required(response.status === 200);
  // The committed fixture is 451 bytes. Bound reading even if storage is corrupt.
  let size = 0; const chunks = [];
  for await (const chunk of response.body) {
    size += chunk.length;
    required(size <= artifact.size);
    chunks.push(Buffer.from(chunk));
  }
  required(size === artifact.size &&
    createHash('sha256').update(Buffer.concat(chunks)).digest('hex') === artifact.sha256);
  const anonymous = new URL(signed.url); anonymous.search = '';
  const denied = await deps.request(anonymous.toString());
  await denied.body?.cancel();
  required([401, 403, 404].includes(denied.status));
  return size;
}

async function main(env = process.env, factory = dependencies, report = console.log) {
  try { report(JSON.stringify(await preflight(env, factory))); return 0; }
  catch (error) {
    // SDK errors can contain credentials, signed URLs or customer/provider data.
    report(JSON.stringify({ configured: false, code: 'commerce_preflight_failed', stage: error.stage }));
    return 1;
  }
}
module.exports = { preflight, main, verifyFixture, EXPECTED };
if (require.main === module) main().then(code => { process.exitCode = code; });
