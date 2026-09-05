const { configuration } = require('../commerce/config');
const { reply } = require('../commerce/http');
function makeHandler(configure = configuration, env = process.env) {
  return (req, res) => {
    if (req.method !== 'GET') { res.setHeader('Allow', 'GET'); return reply(res, 405, { error: 'get_required' }); }
    let result = { available: false };
    try {
      if (env.COMMERCE_CHECKOUT_OPEN === 'yes' && env.COMMERCE_MODE === 'live') {
        const config = configure(env);
        const architecture = config.release.filename.match(/-(arm64|x86_64)\.zip$/)?.[1];
        if (config.live && architecture) result = { available: true, priceUSD: 50, architecture };
      }
    } catch { /* Missing or unreviewed release stays closed; expose no configuration. */ }
    return reply(res, 200, result);
  };
}
module.exports = makeHandler();
module.exports.makeHandler = makeHandler;
