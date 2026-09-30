// Dark sandbox-only request for one bounded R2 verification checkpoint. A
// successful response is progress, not a published or recoverable backup.
const { reply } = require('../commerce/http');
const { allowedBrowserOrigin } = require('../hosted/http_origin');
const { uploadRuntime } = require('../hosted/upload_runtime');
const { authorizeUploadScope, HostedAccessError } = require('../hosted/access');
const { createBatchVerifier } = require('../hosted/batch_verifier');
const { verifyNextPage } = require('../hosted/verification_steps');

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const BEARER = /^Bearer (hv1_[A-Za-z0-9_-]{43})$/;

function requestBody(req) {
  if (!allowedBrowserOrigin(req.headers.origin)) {
    throw Error('invalid_request');
  }
  if ((req.headers['content-type'] || '').split(';')[0] !== 'application/json' ||
      Number(req.headers['content-length']) > 300 ||
      !req.body || typeof req.body !== 'object' || Array.isArray(req.body) ||
      Buffer.byteLength(JSON.stringify(req.body)) > 300 ||
      Object.keys(req.body).sort().join(',') !==
        'action,reservationId,snapshotId,vaultId' ||
      req.body.action !== 'verify_next' || !UUID.test(req.body.vaultId) ||
      !UUID.test(req.body.reservationId) || !UUID.test(req.body.snapshotId)) {
    throw Error('invalid_request');
  }
  return req.body;
}

function makeHandler(load = uploadRuntime, env = process.env,
  makeVerifier = createBatchVerifier, verify = verifyNextPage) {
  return async (req, res) => {
    if (env.HOSTED_MODE !== 'sandbox' ||
        env.HOSTED_SANDBOX_UPLOAD_OPEN !== 'yes' ||
        env.HOSTED_SANDBOX_VERIFY_OPEN !== 'yes') {
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
      const { query, getEntitlement, verifyPurchase, live, priceCatalog,
        workerOrigin, secret } = await load(env);
      if (live !== false) throw Error('hosted_verify_unavailable');
      const scope = await authorizeUploadScope({ sessionToken: token,
        vaultId: data.vaultId, query, getEntitlement, verifyPurchase,
        live, priceCatalog });
      const verifyBatch = makeVerifier({ origin: workerOrigin, secret });
      const result = await verify({ scope, reservationId: data.reservationId,
        snapshotId: data.snapshotId, verifyBatch, query });
      return reply(res, 200, result);
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
