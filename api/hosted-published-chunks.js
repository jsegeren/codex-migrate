// Dark sandbox lookup for immutable ciphertext reuse. It returns no object
// bytes and is not a capability: later HEAD/PUT and publication still require
// their own fresh authorization and independent provider verification.
const { reply } = require('../commerce/http');
const { uploadRuntime } = require('../hosted/upload_runtime');
const { authorizeUploadScope, HostedAccessError } = require('../hosted/access');
const { lookupPublishedChunks } = require('../hosted/published_chunks');

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const HEX = /^[0-9a-f]{64}$/;
const BEARER = /^Bearer (hv1_[A-Za-z0-9_-]{43})$/;
const MAX_BODY = 18_000;

function requestBody(req) {
  if (req.headers.origin && req.headers.origin !== 'https://migrate.segeren.com') {
    throw Error('invalid_request');
  }
  if ((req.headers['content-type'] || '').split(';')[0] !== 'application/json' ||
      Number(req.headers['content-length']) > MAX_BODY ||
      !req.body || typeof req.body !== 'object' || Array.isArray(req.body) ||
      Object.keys(req.body).sort().join(',') !== 'ids,vaultId' ||
      !UUID.test(req.body.vaultId) || !Array.isArray(req.body.ids) ||
      req.body.ids.length < 1 || req.body.ids.length > 256 ||
      !req.body.ids.every(id => typeof id === 'string' && HEX.test(id)) ||
      new Set(req.body.ids).size !== req.body.ids.length ||
      Buffer.byteLength(JSON.stringify(req.body)) > MAX_BODY) {
    throw Error('invalid_request');
  }
  return req.body;
}

function makeHandler(load = uploadRuntime, env = process.env) {
  return async (req, res) => {
    if (env.HOSTED_MODE !== 'sandbox' ||
        env.HOSTED_SANDBOX_UPLOAD_OPEN !== 'yes') {
      return reply(res, 404, { error: 'not_found' });
    }
    if (req.method !== 'POST') {
      res.setHeader('Allow', 'POST');
      return reply(res, 405, { error: 'post_required' });
    }
    let data;
    try { data = requestBody(req); }
    catch { return reply(res, 400, { error: 'invalid_request' }); }
    const token = BEARER.exec(req.headers.authorization || '')?.[1];
    if (!token) return reply(res, 403, { error: 'access_denied' });
    try {
      const { query, getEntitlement, verifyPurchase, live, priceCatalog } =
        await load(env);
      if (live !== false) throw Error('hosted_lookup_unavailable');
      const scope = await authorizeUploadScope({ sessionToken: token,
        vaultId: data.vaultId, query, getEntitlement, verifyPurchase,
        live, priceCatalog });
      const objects = await lookupPublishedChunks({ scope,
        ids: data.ids, query });
      return reply(res, 200, { objects });
    } catch (error) {
      return reply(res, error instanceof HostedAccessError ? 403 : 503,
        { error: error instanceof HostedAccessError ? 'access_denied' :
          'temporarily_unavailable' });
    }
  };
}

module.exports = makeHandler();
module.exports.makeHandler = makeHandler;
module.exports.requestBody = requestBody;
