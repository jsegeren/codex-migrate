const { runtime } = require('../commerce/runtime');
const { reply, failure, body } = require('../commerce/http');
const { CommerceError } = require('../commerce/config');
const { tokenSession, sessionId } = require('../commerce/service');
const { configuration, commerceSite } = require('../commerce/config');
function makeHandler(load = runtime, configure = configuration, env = process.env) {
  return async (req, res) => {
    if (req.method !== 'POST') { res.setHeader('Allow', 'POST'); return reply(res, 405, { error: 'post_required' }); }
    try {
      const data = body(req, commerceSite(env));
      if (Object.keys(data).some(k => !['action', 'credential'].includes(k)) || typeof data.credential !== 'string') {
        throw new CommerceError('invalid_request', 400);
      }
      const config = configure(env);
      // Reject bogus bearer credentials before opening a database connection.
      if (data.action === 'download') tokenSession(data.credential, config);
      else if (data.action !== 'status' || !sessionId(data.credential, config.live)) throw new CommerceError('invalid_link', 403);
      const { service } = await load(env);
      if (data.action === 'status') return reply(res, 200, await service.status(data.credential));
      if (data.action === 'download') return reply(res, 200, await service.download(data.credential));
      throw new CommerceError('invalid_request', 400);
    } catch (error) { return failure(res, error); }
  };
}
module.exports = makeHandler();
module.exports.makeHandler = makeHandler;
