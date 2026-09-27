// Dark sandbox-only upload control plane. This route never accepts bytes or
// storage credentials: it reserves quota and issues exact, short-lived grants
// only after a fresh device, app-purchase, and Stripe Subscription check.
const { reply } = require('../commerce/http');
const { uploadRuntime } = require('../hosted/upload_runtime');
const { authorizeUploadScope, HostedAccessError } = require('../hosted/access');
const { createUploadReservation, renewUploadReservation } =
  require('../hosted/reservation');
const { decideUploadObject } = require('../hosted/upload_decision');
const { issuePutCapability } = require('../hosted/upload_grant');

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const UUID_PATH = '[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}';
const BEARER = /^Bearer (hv1_[A-Za-z0-9_-]{43})$/;
const RELATIVE = new RegExp(`^(?:metadata/${UUID_PATH}\\.json|objects/[0-9a-f]{2}/[0-9a-f]{62}\\.cvchunk|manifests/${UUID_PATH}\\.cvmanifest|refs/${UUID_PATH}\\.json)$`);
const HEX = /^[0-9a-f]{64}$/;
const MAX_BODY = 700;

function requestBody(req) {
  if (req.headers.origin && req.headers.origin !== 'https://migrate.segeren.com') {
    throw Error('invalid_request');
  }
  if ((req.headers['content-type'] || '').split(';')[0] !== 'application/json' ||
      Number(req.headers['content-length']) > MAX_BODY ||
      !req.body || typeof req.body !== 'object' || Array.isArray(req.body) ||
      Buffer.byteLength(JSON.stringify(req.body)) > MAX_BODY) {
    throw Error('invalid_request');
  }
  const data = req.body;
  const keys = Object.keys(data).sort().join(',');
  const expected = data.action === 'reserve' ? 'action,bytes,vaultId' :
    data.action === 'renew' ? 'action,reservationId,vaultId' :
    ['decide', 'put'].includes(data.action) ?
      'action,item,reservationId,vaultId' : null;
  if (keys !== expected || !UUID.test(data.vaultId)) {
    throw Error('invalid_request');
  }
  if (data.action === 'reserve') {
    if (!Number.isSafeInteger(data.bytes) || data.bytes < 1 ||
        data.bytes > 1_000_000_000_000) throw Error('invalid_request');
  } else if (!UUID.test(data.reservationId)) throw Error('invalid_request');
  if (data.action === 'decide' || data.action === 'put') {
    const item = data.item;
    if (!item || typeof item !== 'object' || Array.isArray(item) ||
        Object.keys(item).sort().join(',') !== 'bytes,key,sha256' ||
        typeof item.key !== 'string' || !RELATIVE.test(item.key) ||
        !Number.isSafeInteger(item.bytes) || item.bytes < 1 ||
        item.bytes > 100_000_000 ||
        typeof item.sha256 !== 'string' || !HEX.test(item.sha256)) {
      throw Error('invalid_request');
    }
  }
  return data;
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
      const { query, getEntitlement, verifyPurchase, live, priceCatalog,
        workerOrigin, secret } = await load(env);
      if (live !== false) throw Error('hosted_upload_unavailable');
      const scope = await authorizeUploadScope({ sessionToken: token,
        vaultId: data.vaultId, query, getEntitlement, verifyPurchase,
        live, priceCatalog });
      if (data.action === 'reserve') {
        return reply(res, 200, await createUploadReservation({ scope,
          bytes: data.bytes, query }));
      }
      if (data.action === 'renew') {
        return reply(res, 200, await renewUploadReservation({ scope,
          reservationId: data.reservationId, query }));
      }
      const item = { key: `accounts/${scope.accountId}/vaults/${scope.vaultId}/` +
        data.item.key, bytes: data.item.bytes, sha256: data.item.sha256 };
      if (data.action === 'decide') {
        const decision = await decideUploadObject({ scope,
          reservationId: data.reservationId, item, secret, query });
        return reply(res, 200, decision.action === 'head' ?
          { action: 'head', workerOrigin, grant: decision.grant } : decision);
      }
      const grant = await issuePutCapability({ scope,
        reservationId: data.reservationId, item, secret, query });
      return reply(res, 200, { workerOrigin, grant });
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
