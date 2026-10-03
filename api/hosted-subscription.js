// Explicit sandbox-only opt-in. Shipping clients and Production are disabled.
const { reply } = require('../commerce/http');
const { allowedBrowserOrigin } = require('../hosted/http_origin');
const { subscriptionRuntime } = require('../hosted/subscription_runtime');
const { subscriptionCheckout } = require('../hosted/subscription_checkout');
const BEARER = /^Bearer (hv1_[A-Za-z0-9_-]{43})$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

function makeHandler(load = subscriptionRuntime, env = process.env) {
  return async (req, res) => {
    if (env.HOSTED_MODE !== 'sandbox' || env.COMMERCE_MODE !== 'sandbox' ||
        env.HOSTED_SANDBOX_SUBSCRIPTION_OPEN !== 'yes') {
      return reply(res, 404, { error: 'not_found' });
    }
    if (req.method !== 'POST') {
      res.setHeader('Allow', 'POST');
      return reply(res, 405, { error: 'post_required' });
    }
    const data = req.body;
    if (!allowedBrowserOrigin(req.headers.origin) ||
        (req.headers['content-type'] || '').split(';')[0] !== 'application/json' ||
        Number(req.headers['content-length']) > 256 ||
        !data || typeof data !== 'object' || Array.isArray(data) ||
        Buffer.byteLength(JSON.stringify(data)) > 256 ||
        Object.keys(data).sort().join(',') !== 'action,deviceId' ||
        !['begin', 'status'].includes(data.action) || !UUID.test(data.deviceId || '')) {
      return reply(res, 400, { error: 'invalid_request' });
    }
    const deviceToken = BEARER.exec(req.headers.authorization || '')?.[1];
    if (!deviceToken) return reply(res, 403, { error: 'access_denied' });
    try {
      return reply(res, 200, await subscriptionCheckout({ ...await load(env),
        action: data.action, deviceId: data.deviceId, deviceToken }));
    } catch { return reply(res, 503, { error: 'temporarily_unavailable' }); }
  };
}

module.exports = makeHandler();
module.exports.makeHandler = makeHandler;
