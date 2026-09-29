// Default runtime for the dark sandbox upload route. The server loads the
// subscription enrollment from its pinned database and rechecks Stripe for
// each full authorization. Object requests use only a freshly signed,
// one-minute lease plus a live device-session check; client input, webhooks,
// and checkout redirects are never entitlement.
const { runtime: commerceRuntime } = require('../commerce/runtime');
const { sandboxDatabaseRuntime, storageConfiguration } =
  require('./recovery_runtime');

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const PRICE = /^price_[A-Za-z0-9]+$/;
const SUBSCRIPTION = /^sub_[A-Za-z0-9]+$/;
const CUSTOMER = /^cus_[A-Za-z0-9]+$/;
const ENROLLMENT_SQL = `SELECT account_id, mode, subscription_id,
    customer_id, price_id FROM hosted.subscription_enrollments
  WHERE account_id = $1::uuid AND mode = 'sandbox'`;

class HostedUploadRuntimeError extends Error {
  constructor() { super('hosted_upload_unavailable'); }
}

function uploadConfiguration(env) {
  if (env.HOSTED_MODE !== 'sandbox' ||
      env.HOSTED_SANDBOX_UPLOAD_OPEN !== 'yes' ||
      env.COMMERCE_MODE !== 'sandbox') throw new HostedUploadRuntimeError();
  const priceId = env.HOSTED_SANDBOX_PRICE_ID;
  const cents = env.HOSTED_SANDBOX_PRICE_CENTS;
  const allowance = env.HOSTED_SANDBOX_ALLOWANCE_BYTES;
  if (!PRICE.test(priceId || '') || !/^[1-9][0-9]{3,6}$/.test(cents || '') ||
      !/^[1-9][0-9]{0,12}$/.test(allowance || '') ||
      Number(allowance) > 1_000_000_000_000) {
    throw new HostedUploadRuntimeError();
  }
  let storage;
  try { storage = storageConfiguration(env); }
  catch { throw new HostedUploadRuntimeError(); }
  return Object.freeze({ ...storage, priceCatalog: new Map([[priceId, {
    priceCents: Number(cents), allowanceBytes: Number(allowance),
  }]]) });
}

async function uploadRuntime(env = process.env, { openDatabase = sandboxDatabaseRuntime,
  openCommerce = commerceRuntime } = {}) {
  const config = uploadConfiguration(env);
  try {
    const [query, commerce] = await Promise.all([
      openDatabase(env), openCommerce(env),
    ]);
    if (commerce.config.mode !== 'sandbox' || commerce.config.live !== false) {
      throw new HostedUploadRuntimeError();
    }
    const getEntitlement = async accountId => {
      if (!UUID.test(accountId)) throw new HostedUploadRuntimeError();
      const result = await query(ENROLLMENT_SQL, [accountId]);
      const row = result?.rows?.[0];
      if (result?.rows?.length !== 1 || row.account_id !== accountId ||
          row.mode !== 'sandbox' ||
          !SUBSCRIPTION.test(row.subscription_id || '') ||
          !CUSTOMER.test(row.customer_id || '') ||
          !config.priceCatalog.has(row.price_id)) {
        throw new HostedUploadRuntimeError();
      }
      const subscription = await commerce.stripe.subscriptions.retrieve(
        row.subscription_id, { expand: ['items.data.price'] });
      return { enrollment: { accountId, subscriptionId: row.subscription_id,
        customerId: row.customer_id, priceId: row.price_id }, subscription };
    };
    return Object.freeze({ query, getEntitlement,
      verifyPurchase: commerce.service.verifyForHostedAuthorization,
      live: false, priceCatalog: config.priceCatalog,
      workerOrigin: config.workerOrigin, secret: config.secret });
  } catch { throw new HostedUploadRuntimeError(); }
}

module.exports = { HostedUploadRuntimeError, uploadConfiguration,
  uploadRuntime, ENROLLMENT_SQL };
