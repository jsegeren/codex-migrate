const { timingSafeEqual } = require('node:crypto');
const { runtime } = require('../commerce/runtime');
const { reply, failure, body } = require('../commerce/http');
const { CommerceError, currentPriceCents, configuration, commerceSite } = require('../commerce/config');
function makeHandler(load = runtime, env = process.env, configure = configuration) {
  return async (req, res) => {
    if (req.method !== 'POST') { res.setHeader('Allow', 'POST'); return reply(res, 405, { error: 'post_required' }); }
    try {
      if (env.COMMERCE_CHECKOUT_OPEN !== 'yes') throw new CommerceError('checkout_closed');
      const data = body(req, commerceSite(env));
      if (Object.keys(data).some(k => k !== 'requestId') || typeof data.requestId !== 'string' ||
          !/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/.test(data.requestId || '')) {
        throw new CommerceError('invalid_request', 400);
      }
      const config = configure(env);
      if (!config.live) {
        const expected = env.COMMERCE_SANDBOX_OPERATOR_TOKEN;
        const supplied = req.headers.authorization || '';
        if (typeof supplied !== 'string' || !/^Bearer [a-f0-9]{64}$/.test(supplied) ||
            !/^[a-f0-9]{64}$/.test(expected || '') ||
            !timingSafeEqual(Buffer.from(supplied), Buffer.from(`Bearer ${expected}`))) throw new CommerceError('sandbox_operator_required', 403);
      }
      // No database connection or provider request before sandbox authorization.
      const { stripe } = await load(env);
      if ((await stripe.accounts.retrieve()).id !== config.account) throw new CommerceError('account_mismatch');
      const price = await stripe.prices.retrieve(config.price, { expand: ['product'] });
      if (price.livemode !== config.live || !price.active || price.unit_amount !== currentPriceCents(config.live) || price.currency !== 'usd' ||
          price.type !== 'one_time' || price.recurring != null || price.billing_scheme !== 'per_unit' ||
          price.transform_quantity != null || price.product?.id !== config.product ||
          price.product.livemode !== config.live || !price.product.active) throw new CommerceError('catalog_mismatch');
      const standard = config.checkoutProvider === 'stripe';
      // Stripe requires separate account-level promotional-email terms before
      // these fields are accepted. Keep ordinary paid checkout independent so
      // recovery can be enabled deliberately without blocking sales.
      const checkoutRecovery = env.COMMERCE_CHECKOUT_RECOVERY === 'yes';
      const session = await stripe.checkout.sessions.create({
        mode: 'payment', line_items: [{ price: config.price, quantity: 1 }],
        ...(checkoutRecovery ? {
          consent_collection: { promotions: 'auto' },
          after_expiration: { recovery: { enabled: true } },
        } : {}),
        ...(standard ? {} : { managed_payments: { enabled: true } }),
        ...(config.release.channel === 'beta' ? { custom_text: { submit: { message:
          'Beta software for Apple silicon Macs. Keep your old Mac and an independent backup until you verify the move. A 30-day refund policy applies.' } } } : {}),
        metadata: { product: 'codex-migrate', release: config.release.id,
          ...(config.release.channel === 'beta' ? { release_channel: 'beta' } : {}),
          checkout_provider: standard ? 'stripe' : 'managed' },
        success_url: `${config.site}/purchase#session={CHECKOUT_SESSION_ID}`, cancel_url: `${config.site}/#founding-edition`,
      }, { idempotencyKey: `codex-migrate-${config.mode}-${config.release.id}-${standard ? 'stripe-' : ''}${checkoutRecovery ? 'recovery-' : ''}${data.requestId}` });
      const url = new URL(session.url);
      if (session.livemode !== config.live || (standard
          ? session.managed_payments != null && session.managed_payments.enabled !== false
          : session.managed_payments?.enabled !== true) ||
          url.origin !== 'https://checkout.stripe.com' || url.username || url.password) throw new CommerceError('checkout_not_verified');
      return reply(res, 200, { url: url.toString() });
    } catch (error) { return failure(res, error); }
  };
}
module.exports = makeHandler();
module.exports.makeHandler = makeHandler;
