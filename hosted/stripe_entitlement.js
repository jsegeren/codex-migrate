// A capability grant must use a freshly retrieved Stripe Subscription and
// the enrollment row loaded for the authenticated customer. A Checkout
// redirect, webhook payload, email address, or download link is not enough.

const PRICE_CENTS = 1000;

function identified(value, prefix) {
  return typeof value === 'string' &&
    new RegExp(`^${prefix}_[A-Za-z0-9]+$`).test(value);
}

function uploadEntitled(subscription, enrollment, live) {
  if (!subscription || !enrollment || typeof live !== 'boolean' ||
      !identified(enrollment.subscriptionId, 'sub') ||
      !identified(enrollment.customerId, 'cus') ||
      !identified(enrollment.priceId, 'price') ||
      subscription.id !== enrollment.subscriptionId ||
      subscription.customer !== enrollment.customerId ||
      subscription.livemode !== live ||
      !['trialing', 'active'].includes(subscription.status) ||
      subscription.collection_method !== 'charge_automatically' ||
      subscription.pause_collection != null ||
      !Array.isArray(subscription.items?.data) ||
      subscription.items.data.length !== 1) return false;

  const item = subscription.items.data[0];
  const price = item?.price;
  return item?.quantity === 1 && price?.id === enrollment.priceId &&
    price?.livemode === live && price?.type === 'recurring' &&
    price?.currency === 'usd' && price?.unit_amount === PRICE_CENTS &&
    price?.billing_scheme === 'per_unit' &&
    price?.recurring?.interval === 'month' &&
    price?.recurring?.interval_count === 1;
}

module.exports = { uploadEntitled };
