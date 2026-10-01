// A capability grant must use a freshly retrieved Stripe Subscription, the
// enrollment row loaded for the authenticated customer, and a server-held
// price catalog. A Checkout redirect, webhook payload, email address, or
// download link is not enough. The catalog must never come from the client.

function identified(value, prefix) {
  return typeof value === 'string' &&
    new RegExp(`^${prefix}_[A-Za-z0-9]+$`).test(value);
}

function uploadAllowance(subscription, enrollment, live, priceCatalog) {
  const plan = identified(enrollment?.priceId, 'price') &&
    priceCatalog instanceof Map && priceCatalog.get(enrollment.priceId);
  if (!subscription || !enrollment || typeof live !== 'boolean' ||
      !identified(enrollment.subscriptionId, 'sub') ||
      !identified(enrollment.customerId, 'cus') ||
      !plan || !Number.isSafeInteger(plan.priceCents) || plan.priceCents <= 0 ||
      !Number.isSafeInteger(plan.allowanceBytes) || plan.allowanceBytes <= 0 ||
      subscription.id !== enrollment.subscriptionId ||
      subscription.customer !== enrollment.customerId ||
      subscription.livemode !== live ||
      !['trialing', 'active'].includes(subscription.status) ||
      subscription.collection_method !== 'charge_automatically' ||
      subscription.pause_collection != null ||
      !Array.isArray(subscription.items?.data) ||
      subscription.items.data.length !== 1) return null;

  const item = subscription.items.data[0];
  const price = item?.price;
  if (!(item?.quantity === 1 && price?.id === enrollment.priceId &&
    price?.livemode === live && price?.type === 'recurring' &&
    price?.currency === 'usd' && price?.unit_amount === plan.priceCents &&
    price?.billing_scheme === 'per_unit' &&
    price?.recurring?.interval === 'month' &&
    price?.recurring?.interval_count === 1)) return null;
  return plan.allowanceBytes;
}

function uploadEntitled(subscription, enrollment, live, priceCatalog) {
  return uploadAllowance(subscription, enrollment, live, priceCatalog) !== null;
}

module.exports = { uploadAllowance, uploadEntitled };
