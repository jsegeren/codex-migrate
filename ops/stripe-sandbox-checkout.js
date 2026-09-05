// Operator-only sandbox preparation. This is not a public checkout endpoint.
// No live credentials, customer information, product writes, or payment capture.
const { randomUUID } = require('node:crypto');

const API = 'https://api.stripe.com/v1';
const PRODUCT_NAME = 'Codex Migrate — Founding Edition (TEST ONLY)';
const SITE = 'https://migrate.segeren.com';
const TAX_CODES = new Set(['txcd_10000000', 'txcd_10202000', 'txcd_10202001', 'txcd_10202003']);

function configuration(env) {
  const key = env.CODEX_MIGRATE_STRIPE_TEST_KEY;
  const account = env.CODEX_MIGRATE_STRIPE_TEST_ACCOUNT;
  const product = env.CODEX_MIGRATE_STRIPE_TEST_PRODUCT;
  const price = env.CODEX_MIGRATE_STRIPE_TEST_PRICE;
  if (!/^(sk|rk)_test_[A-Za-z0-9]+$/.test(key || '') ||
      !/^acct_[A-Za-z0-9]+$/.test(account || '') ||
      !/^prod_[A-Za-z0-9]+$/.test(product || '') ||
      !/^price_[A-Za-z0-9]+$/.test(price || '')) {
    throw new Error('Configure the four Codex Migrate sandbox variables; live keys are never accepted.');
  }
  return { key, account, product, price };
}

async function prepare({ env = process.env, request = fetch, create = false } = {}) {
  const config = configuration(env);
  async function stripe(path, body) {
    let response;
    try {
      response = await request(API + path, {
        method: body ? 'POST' : 'GET',
        redirect: 'error',
        signal: AbortSignal.timeout(10000),
        headers: {
          Authorization: `Bearer ${config.key}`,
          'Stripe-Version': '2025-03-31.basil',
          ...(body ? { 'Content-Type': 'application/x-www-form-urlencoded',
            'Idempotency-Key': `codex-migrate-sandbox-${randomUUID()}` } : {}),
        },
        ...(body ? { body: body.toString() } : {}),
      });
    } catch {
      // Provider exceptions can contain credentials or request details.
      throw new Error('Stripe request was not confirmed. Check the sandbox dashboard before retrying.');
    }
    if (!response.ok) {
      throw new Error('Stripe declined the sandbox request. Check permissions and Managed Payments setup.');
    }
    try { return await response.json(); }
    catch { throw new Error('Stripe returned an unreadable response. No checkout was confirmed.'); }
  }

  const account = await stripe('/account');
  if (account?.id !== config.account) throw new Error('Sandbox account mismatch; stopped before checkout.');
  const price = await stripe(`/prices/${config.price}?expand%5B%5D=product`);
  const product = price?.product;
  const taxCode = typeof product?.tax_code === 'string' ? product.tax_code : product?.tax_code?.id;
  if (price?.id !== config.price || price.livemode !== false || price.active !== true ||
      price.type !== 'one_time' || price.recurring != null || price.currency !== 'usd' ||
      price.unit_amount !== 5000 || price.billing_scheme !== 'per_unit' ||
      price.transform_quantity != null || product?.id !== config.product ||
      product.livemode !== false || product.active !== true || product.name !== PRODUCT_NAME ||
      !TAX_CODES.has(taxCode)) {
    throw new Error('Expected the exact active $50 USD one-time Codex Migrate TEST ONLY product and price.');
  }
  if (!create) return { status: 'sandbox_catalog_verified', checkoutCreated: false };

  const body = new URLSearchParams({
    mode: 'payment',
    'line_items[0][price]': config.price,
    'line_items[0][quantity]': '1',
    'managed_payments[enabled]': 'true',
    'metadata[product]': 'codex-migrate',
    'metadata[purpose]': 'sandbox-acceptance-only',
    success_url: `${SITE}/success.html`,
    cancel_url: `${SITE}/#founding-edition`,
    'custom_text[submit][message]': 'Sandbox acceptance test only. No app, license, or real purchase is delivered.',
  });
  const session = await stripe('/checkout/sessions', body);
  let url;
  try { url = new URL(session?.url); } catch { /* validated below */ }
  if (session?.livemode !== false || session.mode !== 'payment' ||
      session.managed_payments?.enabled !== true || session.status !== 'open' ||
      !/^cs_test_[A-Za-z0-9]+$/.test(session.id || '') ||
      url?.origin !== 'https://checkout.stripe.com' || url.username || url.password) {
    throw new Error('Sandbox session could not be verified. Inspect Stripe; no ordinary-payment fallback was attempted.');
  }
  // Only the public sandbox session ID is returned. Never print keys, full
  // provider responses, account identity/contact fields, or checkout URL tokens.
  return { status: 'sandbox_session_created', session: session.id, checkoutCreated: true };
}

module.exports = { prepare };
if (require.main === module) {
  const args = process.argv.slice(2);
  if (args.length > 1 || (args.length === 1 && args[0] !== '--create')) {
    process.stderr.write('Usage: node ops/stripe-sandbox-checkout.js [--create]\n');
    process.exitCode = 2;
  } else {
    prepare({ create: args[0] === '--create' }).then(result => {
      process.stdout.write(JSON.stringify(result) + '\n');
    }).catch(error => {
      process.stderr.write(error.message + '\n');
      process.exitCode = 1;
    });
  }
}
