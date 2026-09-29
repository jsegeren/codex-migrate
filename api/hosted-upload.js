// Dark sandbox-only upload control plane. This route never accepts bytes or
// storage credentials: it reserves quota and issues exact, short-lived grants
// after either a fresh Stripe check or a one-minute, device-bound lease.
const { reply } = require('../commerce/http');
const { uploadRuntime } = require('../hosted/upload_runtime');
const { authorizeUploadScope, authorizeLeasedUploadScope, authorizeReadScope,
  consumeAuthorizedScope, tokenHash, HostedAccessError } = require('../hosted/access');
const { HostedUploadLeaseError, mintUploadLease,
  requireActiveReservation } = require('../hosted/upload_lease');
const { createUploadReservation, renewUploadReservation,
  abandonUploadReservation, readUploadReservationStatus } =
  require('../hosted/reservation');
const { decideUploadObject } = require('../hosted/upload_decision');
const { issuePutCapability } = require('../hosted/upload_grant');
const { prepareUploadBatch, MAX_ITEMS } = require('../hosted/upload_batch');

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const UUID_PATH = '[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}';
const BEARER = /^Bearer (hv1_[A-Za-z0-9_-]{43})$/;
const RELATIVE = new RegExp(`^(?:metadata/${UUID_PATH}\\.json|objects/[0-9a-f]{2}/[0-9a-f]{62}\\.cvchunk|manifests/${UUID_PATH}\\.cvmanifest|refs/${UUID_PATH}\\.json)$`);
const HEX = /^[0-9a-f]{64}$/;
const MAX_BODY = 700;
const MAX_BATCH_BODY = 2_000;

function validRequestItem(item) {
  return item && typeof item === 'object' && !Array.isArray(item) &&
    Object.keys(item).sort().join(',') === 'bytes,key,sha256' &&
    typeof item.key === 'string' && RELATIVE.test(item.key) &&
    Number.isSafeInteger(item.bytes) && item.bytes >= 1 &&
    item.bytes <= 100_000_000 &&
    typeof item.sha256 === 'string' && HEX.test(item.sha256);
}

function requestBody(req) {
  if (req.headers.origin && req.headers.origin !== 'https://migrate.segeren.com') {
    throw Error('invalid_request');
  }
  const limit = req.body?.action === 'batch' ? MAX_BATCH_BODY : MAX_BODY;
  if ((req.headers['content-type'] || '').split(';')[0] !== 'application/json' ||
      Number(req.headers['content-length']) > limit ||
      !req.body || typeof req.body !== 'object' || Array.isArray(req.body) ||
      Buffer.byteLength(JSON.stringify(req.body)) > limit) {
    throw Error('invalid_request');
  }
  const data = req.body;
  const keys = Object.keys(data).sort().join(',');
  const expected = data.action === 'reserve' ?
    (keys === 'action,bytes,reservationId,vaultId' ? keys : 'action,bytes,vaultId') :
    ['renew', 'abandon', 'status', 'lease'].includes(data.action) ?
      'action,reservationId,vaultId' :
    data.action === 'batch' ? 'action,items,reservationId,vaultId' :
    ['decide', 'put'].includes(data.action) ?
      'action,item,reservationId,vaultId' : null;
  if (keys !== expected || !UUID.test(data.vaultId)) {
    throw Error('invalid_request');
  }
  if (data.action === 'reserve') {
    if (!Number.isSafeInteger(data.bytes) || data.bytes < 1 ||
        data.bytes > 1_000_000_000_000 ||
        (data.reservationId !== undefined && !UUID.test(data.reservationId))) {
      throw Error('invalid_request');
    }
  } else if (!UUID.test(data.reservationId)) throw Error('invalid_request');
  if (data.action === 'decide' || data.action === 'put') {
    if (!validRequestItem(data.item)) throw Error('invalid_request');
  }
  if (data.action === 'batch') {
    if (!Array.isArray(data.items) || data.items.length < 1 ||
        data.items.length > MAX_ITEMS ||
        data.items.some(item => !validRequestItem(item)) ||
        new Set(data.items.map(item => item.key)).size !== data.items.length) {
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
    const scopedObject = ['decide', 'put', 'batch'].includes(data.action);
    if (scopedObject &&
        (typeof req.headers['x-hosted-upload-lease'] !== 'string' ||
         req.headers['x-hosted-upload-lease'].length > 750)) {
      return reply(res, 403, { error: 'access_denied' });
    }
    try {
      const { query, getEntitlement, verifyPurchase, live, priceCatalog,
        workerOrigin, secret } = await load(env);
      if (live !== false) throw Error('hosted_upload_unavailable');
      if (data.action === 'abandon' || data.action === 'status') {
        const scope = await authorizeReadScope({ sessionToken: token,
          vaultId: data.vaultId, query });
        return reply(res, 200, await (data.action === 'abandon' ?
          abandonUploadReservation : readUploadReservationStatus)({ scope,
            reservationId: data.reservationId, query }));
      }
      const scope = scopedObject ? await authorizeLeasedUploadScope({
        sessionToken: token, vaultId: data.vaultId,
        reservationId: data.reservationId,
        lease: req.headers['x-hosted-upload-lease'], secret, query,
      }) : await authorizeUploadScope({ sessionToken: token,
        vaultId: data.vaultId, query, getEntitlement, verifyPurchase,
        live, priceCatalog });
      if (data.action === 'lease') {
        await requireActiveReservation({ accountId: scope.accountId,
          vaultId: scope.vaultId, reservationId: data.reservationId, query });
        if (!consumeAuthorizedScope(scope)) throw Error('upload_scope_expired');
        return reply(res, 200, { lease: mintUploadLease({
          accountId: scope.accountId, vaultId: scope.vaultId,
          reservationId: data.reservationId, deviceHash: tokenHash(token),
          allowanceBytes: scope.allowanceBytes, secret,
        }) });
      }
      if (data.action === 'reserve') {
        return reply(res, 200, await createUploadReservation({ scope,
          bytes: data.bytes, reservationId: data.reservationId, query }));
      }
      if (data.action === 'renew') {
        return reply(res, 200, await renewUploadReservation({ scope,
          reservationId: data.reservationId, query }));
      }
      if (data.action === 'batch') {
        const prefix = `accounts/${scope.accountId}/vaults/${scope.vaultId}/`;
        const items = data.items.map(item => ({ ...item,
          key: prefix + item.key }));
        return reply(res, 200, { workerOrigin,
          objects: await prepareUploadBatch({ scope,
            reservationId: data.reservationId, items, secret, query }) });
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
      const denied = error instanceof HostedAccessError ||
        error instanceof HostedUploadLeaseError;
      return reply(res, denied ? 403 : 503,
        { error: denied ? 'access_denied' :
          'temporarily_unavailable' });
    }
  };
}

module.exports = makeHandler();
module.exports.makeHandler = makeHandler;
module.exports.requestBody = requestBody;
