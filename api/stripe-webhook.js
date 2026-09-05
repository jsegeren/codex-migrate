const Stripe = require('stripe');
const { configuration } = require('../commerce/config');
const { runtime } = require('../commerce/runtime');
const { reply, failure } = require('../commerce/http');
const TYPES = new Set(['checkout.session.completed', 'checkout.session.async_payment_succeeded']);
function makeHandler(load = runtime, configure = configuration) {
  return async (req, res) => {
    if (req.method !== 'POST') { res.setHeader('Allow', 'POST'); return reply(res, 405, { error: 'post_required' }); }
    let config;
    try { config = configure(); } catch (error) { return failure(res, error); }
    let event;
    try {
      const chunks = []; let size = 0;
      // Never verify a reserialized req.body. The signature covers raw bytes.
      for await (const chunk of req) {
        size += Buffer.byteLength(chunk);
        if (size > 262144) return reply(res, 413, { error: 'request_too_large' });
        chunks.push(Buffer.from(chunk));
      }
      event = Stripe.webhooks.constructEvent(Buffer.concat(chunks), req.headers['stripe-signature'], config.webhookSecret, 300);
    } catch { return reply(res, 400, { error: 'invalid_signature' }); }
    if (event.livemode !== config.live || event.account) return reply(res, 400, { error: 'wrong_environment' });
    if (!TYPES.has(event.type)) return reply(res, 200, { received: true });
    const session = event.data?.object;
    // Shared account events belonging to You.one are acknowledged but untouched.
    if (session?.metadata?.product !== 'codex-migrate') return reply(res, 200, { received: true });
    if (session.payment_status === 'unpaid') return reply(res, 200, { received: true });
    try {
      const { service } = await load();
      await service.fulfill(session.id);
      return reply(res, 200, { received: true });
    } catch (error) { return failure(res, error); }
  };
}
module.exports = makeHandler();
module.exports.makeHandler = makeHandler;
module.exports.config = { api: { bodyParser: false } };
