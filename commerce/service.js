const { createHmac, timingSafeEqual } = require('node:crypto');
const { CommerceError, validRelease } = require('./config');

function sessionId(id, live) {
  return typeof id === 'string' && id.length <= 255 &&
    (live ? /^cs_live_[A-Za-z0-9]+$/ : /^cs_test_[A-Za-z0-9]+$/).test(id);
}
function tokenFor(id, config) {
  return `${id}.${createHmac('sha256', config.secret).update(`${config.mode}:${id}`).digest('hex')}`;
}
function tokenSession(token, config) {
  if (typeof token !== 'string' || token.length > 330) throw new CommerceError('invalid_link', 403);
  const [id, mac, extra] = token.split('.');
  if (extra || !sessionId(id, config.live) || !/^[a-f0-9]{64}$/.test(mac || '')) throw new CommerceError('invalid_link', 403);
  const expected = tokenFor(id, config).split('.')[1];
  if (!timingSafeEqual(Buffer.from(mac), Buffer.from(expected))) throw new CommerceError('invalid_link', 403);
  return id;
}
function validatePurchase(session, config) {
  const item = session?.line_items?.data?.[0];
  const price = item?.price;
  const product = typeof price?.product === 'string' ? price.product : price?.product?.id;
  // Metadata alone is not payment authority. Match the paid Stripe line item,
  // environment, quantity, actual amount and the successful charge as well.
  if (!sessionId(session?.id, config.live) || session.livemode !== config.live ||
      session.mode !== 'payment' || session.status !== 'complete' ||
      session.payment_status !== 'paid' || session.managed_payments?.enabled !== true ||
      session.metadata?.product !== 'codex-migrate' ||
      session.metadata?.release !== config.release.id ||
      session.line_items?.has_more !== false || session.line_items.data.length !== 1 ||
      price?.id !== config.price || product !== config.product || price.livemode !== config.live ||
      price.type !== 'one_time' || price.recurring != null || price.currency !== 'usd' ||
      price.unit_amount !== 5000 || item.quantity !== 1 || item.amount_subtotal !== 5000 ||
      session.amount_subtotal !== 5000 || session.currency !== 'usd' ||
      session.total_details?.amount_discount !== 0) throw new CommerceError('purchase_not_verified', 409);
  const intent = session.payment_intent;
  const charge = intent?.latest_charge;
  if (typeof intent !== 'object' || intent.status !== 'succeeded' || intent.livemode !== config.live ||
      !/^pi_[A-Za-z0-9]+$/.test(intent.id || '') ||
      typeof charge !== 'object' || charge?.paid !== true || charge.livemode !== config.live ||
      charge.status !== 'succeeded' || charge.currency !== 'usd' ||
      !Number.isSafeInteger(session.amount_total) || session.amount_total < 5000 ||
      intent.amount_received !== session.amount_total || charge.amount !== session.amount_total) {
    throw new CommerceError('purchase_not_verified', 409);
  }
  if (charge.refunded !== false || charge.amount_refunded !== 0 || charge.disputed !== false) {
    throw new CommerceError('purchase_requires_support', 403);
  }
  const email = session.customer_details?.email;
  if (typeof email !== 'string' || email.length > 254 ||
      !/^[^\s<>@\r\n]+@[^\s<>@\r\n]+\.[^\s<>@\r\n]+$/.test(email)) {
    throw new CommerceError('purchase_requires_support', 409);
  }
  return { sessionId: session.id, mode: config.mode, releaseId: config.release.id,
    paymentIntent: intent.id, email };
}

function service({ config, stripe, store, sendMail, signDownload }) {
  async function verified(id) {
    if (!sessionId(id, config.live)) throw new CommerceError('invalid_link', 403);
    const account = await stripe.accounts.retrieve();
    if (account.id !== config.account) throw new CommerceError('account_mismatch');
    const session = await stripe.checkout.sessions.retrieve(id, {
      expand: ['line_items', 'payment_intent.latest_charge'],
    });
    const release = config.catalog?.[session.metadata?.release];
    if (!validRelease(release, config.live) || release.id !== session.metadata.release) {
      throw new CommerceError('release_unavailable');
    }
    // Keep old paid releases recoverable when the current release changes.
    return { ...validatePurchase(session, { ...config, release }), release };
  }
  async function fulfill(id) {
    const purchase = await verified(id);
    // Unique session key grants one entitlement under concurrent/replayed events.
    await store.ensure(purchase);
    const claim = await store.claim(id, config.mode);
    if (!claim) return { status: 'recorded' };
    const link = `${config.site}/purchase#${tokenFor(id, config)}`;
    let result;
    try { result = await sendMail({ to: purchase.email, link, release: purchase.release, live: config.live }); }
    catch { result = 'uncertain'; }
    // The provider and database cannot share a transaction. Never blindly resend
    // after a timeout/crash: retain an explicit uncertain delivery for review.
    await store.mailResult(id, config.mode, claim, result);
    if (result !== 'accepted') throw new CommerceError('delivery_needs_retry');
    return { status: 'recorded' };
  }
  async function download(token) {
    const id = tokenSession(token, config);
    // Recheck current refund/dispute/payment state, not just an old webhook.
    const purchase = await verified(id);
    await store.ensure(purchase);
    if (typeof signDownload !== 'function') throw new CommerceError('release_unavailable');
    const signed = await signDownload(purchase.release);
    return { ...signed, sha256: purchase.release.sha256, release: purchase.release.id,
      filename: purchase.release.filename, size: purchase.release.size };
  }
  async function status(id) {
    const purchase = await verified(id);
    await store.ensure(purchase);
    return { token: tokenFor(id, config), release: purchase.release.id };
  }
  return { fulfill, download, status };
}
module.exports = { service, validatePurchase, tokenFor, tokenSession, sessionId };
