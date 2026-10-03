const { runtime: commerceRuntime } = require('../commerce/runtime');
const { sandboxDatabaseUrl, sandboxDatabaseRuntime } = require('./recovery_runtime');
const { HostedSubscriptionError } = require('./subscription_checkout');

function subscriptionConfiguration(env) {
  if (env.HOSTED_MODE !== 'sandbox' || env.COMMERCE_MODE !== 'sandbox' ||
      env.HOSTED_SANDBOX_SUBSCRIPTION_OPEN !== 'yes') throw new HostedSubscriptionError();
  sandboxDatabaseUrl(env);
  const priceId = env.HOSTED_SANDBOX_PRICE_ID;
  const cents = env.HOSTED_SANDBOX_PRICE_CENTS;
  const allowance = env.HOSTED_SANDBOX_ALLOWANCE_BYTES;
  if (!/^price_[A-Za-z0-9]+$/.test(priceId || '') ||
      !/^[1-9][0-9]{3,6}$/.test(cents || '') ||
      !/^[1-9][0-9]{0,12}$/.test(allowance || '') ||
      Number(allowance) > 1_000_000_000_000) throw new HostedSubscriptionError();
  return Object.freeze({ priceId, priceCents: Number(cents),
    allowanceBytes: Number(allowance) });
}

async function subscriptionRuntime(env = process.env, {
  openDatabase = sandboxDatabaseRuntime, openCommerce = commerceRuntime,
} = {}) {
  const config = subscriptionConfiguration(env);
  try {
    const [query, commerce] = await Promise.all([openDatabase(env), openCommerce(env)]);
    if (commerce.config.mode !== 'sandbox' || commerce.config.live !== false ||
        !/^https:\/\/codex-migrate-[a-z0-9]+-joshuas-projects-d3a5c48d\.vercel\.app$/.test(
          commerce.config.site)) throw new HostedSubscriptionError();
    return Object.freeze({ query, stripe: commerce.stripe,
      verifyPurchase: commerce.service.verifyForHostedAuthorization,
      config: Object.freeze({ ...config, site: commerce.config.site }) });
  } catch { throw new HostedSubscriptionError(); }
}

module.exports = { subscriptionConfiguration, subscriptionRuntime };
