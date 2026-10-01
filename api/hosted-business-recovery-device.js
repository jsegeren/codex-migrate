// A default-off sandbox route for explicitly authorized, audited, read-only
// access to an existing encrypted business Vault after loss of the first Mac.
const { reply } = require('../commerce/http');
const { allowedBrowserOrigin } = require('../hosted/http_origin');
const { sandboxDatabaseUrl,
  sandboxDatabaseRuntime } = require('../hosted/recovery_runtime');
const { businessRecoveryMail } = require('../hosted/business_recovery_mail');
const { beginBusinessRecovery,
  claimBusinessRecovery } = require('../hosted/business_recovery_device');

const ADMIN_BEARER = /^Bearer (hva1_[A-Za-z0-9_-]{43})$/;
const MAX_BODY = 768;

function requestBody(req) {
  if (!allowedBrowserOrigin(req.headers.origin) ||
      (req.headers['content-type'] || '').split(';')[0] !== 'application/json' ||
      Number(req.headers['content-length']) > MAX_BODY ||
      !req.body || typeof req.body !== 'object' || Array.isArray(req.body) ||
      Buffer.byteLength(JSON.stringify(req.body)) > MAX_BODY) {
    throw Error('invalid_request');
  }
  const data = req.body;
  const keys = Object.keys(data).sort().join(',');
  const expected = data.action === 'begin' ?
    'accountId,action,purpose,seatId,vaultId' :
    data.action === 'claim' ?
      'accountId,action,code,deviceId,deviceTokenHash,requestId,seatId,vaultId' : null;
  if (keys !== expected ||
      (data.action === 'begin' &&
        ['accountId', 'seatId', 'vaultId', 'purpose']
          .some(key => typeof data[key] !== 'string')) ||
      (data.action === 'claim' &&
        ['accountId', 'seatId', 'vaultId', 'requestId', 'code',
          'deviceId', 'deviceTokenHash']
          .some(key => typeof data[key] !== 'string'))) {
    throw Error('invalid_request');
  }
  return data;
}

async function businessRecoveryRuntime(env) {
  sandboxDatabaseUrl(env);
  return Object.freeze({ query: await sandboxDatabaseRuntime(env),
    sendChallenge: value => businessRecoveryMail(value, env) });
}

function makeHandler(load = businessRecoveryRuntime, env = process.env) {
  return async (req, res) => {
    if (env.HOSTED_MODE !== 'sandbox' ||
        env.HOSTED_BUSINESS_RECOVERY_SANDBOX_OPEN !== 'yes') {
      return reply(res, 404, { error: 'not_found' });
    }
    if (req.method !== 'POST') {
      res.setHeader('Allow', 'POST');
      return reply(res, 405, { error: 'post_required' });
    }
    let data;
    try { data = requestBody(req); }
    catch { return reply(res, 400, { error: 'invalid_request' }); }
    const adminToken = ADMIN_BEARER.exec(req.headers.authorization || '')?.[1];
    if (data.action === 'begin' && !adminToken) {
      return reply(res, 403, { error: 'access_denied' });
    }
    res.setHeader('Cache-Control', 'no-store');
    try {
      const { query, sendChallenge } = await load(env);
      if (data.action === 'begin') {
        return reply(res, 200, await beginBusinessRecovery({
          adminSessionToken: adminToken, accountId: data.accountId,
          seatId: data.seatId, vaultId: data.vaultId,
          purpose: data.purpose, query, sendChallenge,
        }));
      }
      return reply(res, 200, await claimBusinessRecovery({
        accountId: data.accountId, seatId: data.seatId,
        vaultId: data.vaultId, requestId: data.requestId, code: data.code,
        deviceId: data.deviceId, deviceTokenHash: data.deviceTokenHash, query,
      }));
    } catch {
      return reply(res, 503, { error: 'temporarily_unavailable' });
    }
  };
}

module.exports = makeHandler();
module.exports.makeHandler = makeHandler;
module.exports.businessRecoveryRuntime = businessRecoveryRuntime;
