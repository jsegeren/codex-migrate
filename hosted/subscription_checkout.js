// Dark test-mode checkout. A device owns an account, not an email or a
// caller-supplied session ID. Persist an attempt before contacting Stripe;
// a lost create response never permits a different idempotency key.
const { resolveFirstDevice } = require('./enrollment');
const { uploadAllowance } = require('./stripe_entitlement');

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const SESSION = /^cs_test_[A-Za-z0-9]+$/;
const RESERVE_SQL = `SELECT * FROM hosted.reserve_subscription_checkout(
  $1::uuid, $2::text, $3::integer, $4::bigint, $5::text)`;
const SAVE_SQL = `SELECT hosted.record_subscription_checkout(
  $1::uuid, $2::uuid, $3::text) AS recorded`;
const ENROLL_SQL = `SELECT hosted.enroll_checkout_subscription(
  $1::uuid, $2::uuid, $3::text, $4::text, $5::text) AS enrolled`;
const LOOKUP_SQL = `SELECT *, created_at > clock_timestamp() - interval '23 hours'
  AS retry_allowed FROM hosted.subscription_checkout_attempts
  WHERE account_id = $1::uuid AND mode = 'sandbox'`;
const POLICY = 'sandbox-monthly-30-day-trial-v1';

class HostedSubscriptionError extends Error {
  constructor() { super('hosted_subscription_unavailable'); }
}

function attemptFrom(result, accountId, config) {
  const row = result?.rows?.[0];
  if (result?.rows?.length !== 1 || row.account_id !== accountId ||
      !UUID.test(row.attempt_id) || row.mode !== 'sandbox' ||
      row.price_id !== config.priceId ||
      Number(row.price_cents) !== config.priceCents ||
      Number(row.allowance_bytes) !== config.allowanceBytes ||
      row.policy !== POLICY || typeof row.retry_allowed !== 'boolean' ||
      !/^https:\/\/codex-migrate-[a-z0-9]+-joshuas-projects-d3a5c48d\.vercel\.app$/.test(row.site || '') ||
      (row.session_id != null && !SESSION.test(row.session_id))) {
    throw new HostedSubscriptionError();
  }
  return row;
}

function metadata(attempt) {
  return { product: 'codex-backup-hosted-sandbox',
    account_id: attempt.account_id, checkout_attempt: attempt.attempt_id,
    policy: POLICY };
}

function ownedSession(session, attempt) {
  const expected = metadata(attempt);
  return SESSION.test(session?.id || '') &&
    session.livemode === false && session.mode === 'subscription' &&
    session.client_reference_id === attempt.account_id &&
    Object.entries(expected).every(([key, value]) => session.metadata?.[key] === value) &&
    (attempt.session_id == null || session.id === attempt.session_id);
}

function checkoutUrl(session, attempt) {
  if (!ownedSession(session, attempt) || session.status !== 'open') {
    throw new HostedSubscriptionError();
  }
  let url;
  try { url = new URL(session.url); } catch { throw new HostedSubscriptionError(); }
  if (url.origin !== 'https://checkout.stripe.com' || url.username ||
      url.password || !url.pathname.startsWith('/c/pay/')) {
    throw new HostedSubscriptionError();
  }
  return url.href;
}

function validSubscription(session, subscription, attempt, config) {
  if (!ownedSession(session, attempt) || session.status !== 'complete' ||
      !['paid', 'no_payment_required'].includes(session.payment_status) ||
      !/^cus_[A-Za-z0-9]+$/.test(session.customer || '') ||
      !/^sub_[A-Za-z0-9]+$/.test(session.subscription || '') ||
      subscription?.id !== session.subscription ||
      subscription.customer !== session.customer ||
      !Object.entries(metadata(attempt)).every(([key, value]) =>
        subscription.metadata?.[key] === value)) return false;
  return uploadAllowance(subscription, { subscriptionId: session.subscription,
    customerId: session.customer, priceId: config.priceId }, false,
  new Map([[config.priceId, { priceCents: config.priceCents,
    allowanceBytes: config.allowanceBytes }]])) === config.allowanceBytes;
}

async function subscriptionCheckout({ action, deviceToken, deviceId,
  query, stripe, verifyPurchase, config }) {
  try {
    if (!['begin', 'status'].includes(action)) throw new HostedSubscriptionError();
    const { accountId } = await resolveFirstDevice({ deviceToken, deviceId,
      query, verifyPurchase });
    const result = action === 'begin' ? await query(RESERVE_SQL,
      [accountId, config.priceId, config.priceCents, config.allowanceBytes,
        config.site]) : await query(LOOKUP_SQL, [accountId]);
    const attempt = attemptFrom(result, accountId, config);
    let session;
    if (attempt.session_id) {
      session = await stripe.checkout.sessions.retrieve(attempt.session_id);
    } else {
      if (action !== 'begin' || !attempt.retry_allowed) {
        throw new HostedSubscriptionError();
      }
      const price = await stripe.prices.retrieve(config.priceId);
      if (price?.id !== config.priceId || price.livemode !== false ||
          price.active !== true || price.type !== 'recurring' ||
          price.currency !== 'usd' || price.unit_amount !== config.priceCents ||
          price.billing_scheme !== 'per_unit' || price.recurring?.interval !== 'month' ||
          price.recurring?.interval_count !== 1) throw new HostedSubscriptionError();
      session = await stripe.checkout.sessions.create({
        mode: 'subscription', client_reference_id: accountId,
        line_items: [{ price: config.priceId, quantity: 1 }],
        payment_method_types: ['card'], payment_method_collection: 'always',
        allow_promotion_codes: false, metadata: metadata(attempt),
        subscription_data: { metadata: metadata(attempt), trial_period_days: 30,
          trial_settings: { end_behavior: { missing_payment_method: 'cancel' } } },
        success_url: `${attempt.site}/#hosted-checkout-complete`,
        cancel_url: `${attempt.site}/#hosted-checkout-canceled`,
      }, { idempotencyKey: `hosted-subscription-sandbox-${attempt.attempt_id}` });
      if (!ownedSession(session, attempt)) throw new HostedSubscriptionError();
      const saved = await query(SAVE_SQL, [accountId, attempt.attempt_id, session.id]);
      if (saved?.rows?.length !== 1 || saved.rows[0].recorded !== true) {
        throw new HostedSubscriptionError();
      }
      attempt.session_id = session.id;
    }
    if (!ownedSession(session, attempt)) throw new HostedSubscriptionError();
    if (session.status === 'open') return Object.freeze({ status: 'checkout_required',
      checkoutUrl: checkoutUrl(session, attempt), testMode: true });
    if (session.status === 'expired') return Object.freeze({ status: 'needs_support',
      testMode: true });
    if (session.status !== 'complete') throw new HostedSubscriptionError();
    const subscription = await stripe.subscriptions.retrieve(session.subscription,
      { expand: ['items.data.price'] });
    if (!validSubscription(session, subscription, attempt, config)) {
      return Object.freeze({ status: 'not_entitled', testMode: true });
    }
    const enrolled = await query(ENROLL_SQL, [accountId, attempt.attempt_id,
      session.id, subscription.id, session.customer]);
    if (enrolled?.rows?.length !== 1 || enrolled.rows[0].enrolled !== true) {
      throw new HostedSubscriptionError();
    }
    // This is not a backup receipt. Every later upload independently checks
    // the original purchase and fresh subscription status, price and customer.
    return Object.freeze({ status: 'subscribed', testMode: true });
  } catch { throw new HostedSubscriptionError(); }
}

module.exports = { subscriptionCheckout, HostedSubscriptionError, RESERVE_SQL,
  SAVE_SQL, ENROLL_SQL, LOOKUP_SQL, POLICY };
