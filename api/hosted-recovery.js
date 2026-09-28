// Deliberately sandbox-only. Customer deployment requires the separate hosted
// release gates: enrollment, retention, trial/billing, scheduled backup, and
// a clean-Mac disaster restore. No production environment can open this route.
const { reply } = require('../commerce/http');
const { recoveryRuntime } = require('../hosted/recovery_runtime');
const { authorizeReadScope, HostedAccessError } = require('../hosted/access');
const { getLastGoodSnapshot, listPublishedObjects } = require('../hosted/read_inventory');
const { issuePublishedGet, issueLastGoodManifest } = require('../hosted/read_grant');

const BEARER = /^Bearer (hv1_[A-Za-z0-9_-]{43})$/;
const MAX_BODY = 600;

function requestBody(req) {
  if (req.headers.origin && req.headers.origin !== 'https://migrate.segeren.com') {
    throw Error('invalid_request');
  }
  if ((req.headers['content-type'] || '').split(';')[0] !== 'application/json' ||
      Number(req.headers['content-length']) > MAX_BODY ||
      !req.body || typeof req.body !== 'object' || Array.isArray(req.body)) {
    throw Error('invalid_request');
  }
  const raw = JSON.stringify(req.body);
  if (Buffer.byteLength(raw) > MAX_BODY) throw Error('invalid_request');
  const { action } = req.body;
  const allowed = action === 'latest' ? ['action', 'vaultId'] :
    action === 'objects' ? ['action', 'vaultId', 'snapshotId', 'afterKey'] :
    action === 'manifest' ? ['action', 'vaultId', 'snapshotId'] :
    action === 'get' ? ['action', 'vaultId', 'snapshotId', 'relativeKey'] : [];
  if (!allowed.length || Object.keys(req.body).some(key => !allowed.includes(key)) ||
      typeof req.body.vaultId !== 'string') throw Error('invalid_request');
  if (action !== 'latest' && typeof req.body.snapshotId !== 'string') {
    throw Error('invalid_request');
  }
  if (action === 'objects' && req.body.afterKey !== undefined &&
      typeof req.body.afterKey !== 'string') throw Error('invalid_request');
  if (action === 'get' && typeof req.body.relativeKey !== 'string') {
    throw Error('invalid_request');
  }
  return req.body;
}

function makeHandler(load = recoveryRuntime, env = process.env) {
  return async (req, res) => {
    if (env.HOSTED_MODE !== 'sandbox' ||
        env.HOSTED_SANDBOX_RECOVERY_OPEN !== 'yes') {
      return reply(res, 404, { error: 'not_found' });
    }
    if (req.method !== 'POST') {
      res.setHeader('Allow', 'POST');
      return reply(res, 405, { error: 'post_required' });
    }
    let data;
    let token;
    try {
      data = requestBody(req);
      token = BEARER.exec(req.headers.authorization || '')?.[1];
      if (!token) return reply(res, 403, { error: 'access_denied' });
    } catch { return reply(res, 400, { error: 'invalid_request' }); }
    try {
      const { query, workerOrigin, secret } = await load(env);
      const scope = await authorizeReadScope({ sessionToken: token,
        vaultId: data.vaultId, query });
      if (data.action === 'latest') {
        return reply(res, 200, { accountId: scope.accountId, workerOrigin,
          latest: await getLastGoodSnapshot({ scope, query }) });
      }
      if (data.action === 'objects') {
        const page = await listPublishedObjects({ scope,
          snapshotId: data.snapshotId, afterKey: data.afterKey || null, query });
        return reply(res, 200, page);
      }
      if (data.action === 'manifest') {
        const manifest = await issueLastGoodManifest({ scope,
          snapshotId: data.snapshotId, secret, query });
        return reply(res, 200, { accountId: scope.accountId, workerOrigin,
          snapshotId: data.snapshotId, ...manifest });
      }
      const grant = await issuePublishedGet({ scope, snapshotId: data.snapshotId,
        relativeKey: data.relativeKey, secret, query });
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
