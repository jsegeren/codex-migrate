// Dark sandbox-only admission of bounded ciphertext object claims. An ACK
// does not verify R2 or advance last-good; publication is a separate job.
const { reply } = require('../commerce/http');
const { allowedBrowserOrigin } = require('../hosted/http_origin');
const { uploadRuntime } = require('../hosted/upload_runtime');
const { HostedAccessError } = require('../hosted/access');
const { deviceCredential, authorizeWrite } = require('../hosted/request_access');
const { appendStagedPage } = require('../hosted/receipt_pages');

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const MAX_BODY = 256 * 1024;

function requestBody(req) {
  if (!allowedBrowserOrigin(req.headers.origin)) {
    throw Error('invalid_request');
  }
  if ((req.headers['content-type'] || '').split(';')[0] !== 'application/json' ||
      Number(req.headers['content-length']) > MAX_BODY ||
      !req.body || typeof req.body !== 'object' || Array.isArray(req.body) ||
      Buffer.byteLength(JSON.stringify(req.body)) > MAX_BODY ||
      Object.keys(req.body).sort().join(',') !==
        'action,expectedBytes,expectedCount,objects,reservationId,snapshotId,vaultId' ||
      req.body.action !== 'page' || !UUID.test(req.body.vaultId) ||
      !UUID.test(req.body.reservationId) || !UUID.test(req.body.snapshotId)) {
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
    const credential = deviceCredential(req.headers.authorization, env);
    if (!credential) return reply(res, 403, { error: 'access_denied' });
    try {
      const { query, getEntitlement, verifyPurchase, live, priceCatalog } =
        await load(env, credential);
      if (live !== false) throw Error('hosted_page_unavailable');
      const scope = await authorizeWrite({ credential,
        vaultId: data.vaultId, query, getEntitlement, verifyPurchase,
        live, priceCatalog });
      const result = await appendStagedPage({ scope,
        reservationId: data.reservationId, snapshotId: data.snapshotId,
        objects: data.objects, expectedCount: data.expectedCount,
        expectedBytes: data.expectedBytes, query });
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
