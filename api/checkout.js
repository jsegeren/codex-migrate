const { timingSafeEqual } = require('node:crypto');
const { runtime } = require('../commerce/runtime');
const { reply, failure, body } = require('../commerce/http');
const { CommerceError, configuration, commerceSite } = require('../commerce/config');
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
      if (price.livemode !== config.live || !price.active || price.unit_amount !== 5000 || price.currency !== 'usd' ||
          price.type !== 'one_time' || price.recurring != null || price.billing_scheme !== 'per_unit' ||
          price.transform_quantity != null || price.product?.id !== config.product ||
          price.product.livemode !== config.live || !price.product.active) throw new CommerceError('catalog_mismatch');
      const session = await stripe.checkout.sessions.create({
        mode: 'payment', line_items: [{ price: config.price, quantity: 1 }], managed_payments: { enabled: true },
        metadata: { product: 'codex-migrate', release: config.release.id },
        success_url: `${config.site}/purchase#session={CHECKOUT_SESSION_ID}`, cancel_url: `${config.site}/#founding-edition`,
      }, { idempotencyKey: `codex-migrate-${config.mode}-${config.release.id}-${data.requestId}` });
      const url = new URL(session.url);
      if (session.livemode !== config.live || session.managed_payments?.enabled !== true ||
          url.origin !== 'https://checkout.stripe.com' || url.username || url.password) throw new CommerceError('checkout_not_verified');
      return reply(res, 200, { url: url.toString() });
    } catch (error) { return failure(res, error); }
  };
}
module.exports = makeHandler();
module.exports.makeHandler = makeHandler;
