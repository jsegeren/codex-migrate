// Dark sandbox-only administrator proof and bounded seat approval. No backup,
// device enrollment, recovery, or business entitlement is reachable here.
const { reply } = require('../commerce/http');
const { allowedBrowserOrigin } = require('../hosted/http_origin');
const { sandboxDatabaseUrl,
  sandboxDatabaseRuntime } = require('../hosted/recovery_runtime');
const { businessAdminMail } = require('../hosted/business_admin_mail');
const { beginBusinessAdminAccess, claimBusinessAdminAccess,
  resolveBusinessAdmin, approveBusinessSeat } = require('../hosted/business_admin');

const BEARER = /^Bearer (hva1_[A-Za-z0-9_-]{43})$/;
const MAX_BODY = 512;

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
  const expected = data.action === 'begin' ? 'accountId,action' :
    data.action === 'claim' ? 'accountId,action,code' :
    data.action === 'resolve' ? 'action' :
    data.action === 'approve-seat' ?
      'action,approvalReference,seatId,workerEmail' : null;
  if (keys !== expected ||
      (['begin', 'claim'].includes(data.action) &&
        typeof data.accountId !== 'string') ||
      (data.action === 'claim' && typeof data.code !== 'string') ||
      (data.action === 'approve-seat' &&
        (typeof data.seatId !== 'string' ||
         typeof data.workerEmail !== 'string' ||
         typeof data.approvalReference !== 'string'))) {
    throw Error('invalid_request');
  }
  return data;
}

async function businessAdminRuntime(env) {
  sandboxDatabaseUrl(env);
  return Object.freeze({ query: await sandboxDatabaseRuntime(env),
    sendChallenge: value => businessAdminMail(value, env) });
}

function makeHandler(load = businessAdminRuntime, env = process.env) {
  return async (req, res) => {
    if (env.HOSTED_MODE !== 'sandbox' ||
        env.HOSTED_BUSINESS_ADMIN_SANDBOX_OPEN !== 'yes') {
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
    if (['resolve', 'approve-seat'].includes(data.action) && !token) {
      return reply(res, 403, { error: 'access_denied' });
    }
    res.setHeader('Cache-Control', 'no-store');
    try {
      const { query, sendChallenge } = await load(env);
      if (data.action === 'begin') {
        return reply(res, 200, await beginBusinessAdminAccess({
          accountId: data.accountId, query, sendChallenge,
        }));
      }
      if (data.action === 'claim') {
        return reply(res, 200, await claimBusinessAdminAccess({
          accountId: data.accountId, code: data.code, query,
        }));
      }
      if (data.action === 'approve-seat') {
        return reply(res, 200, await approveBusinessSeat({
          sessionToken: token, seatId: data.seatId,
          workerEmail: data.workerEmail,
          approvalReference: data.approvalReference, query,
        }));
      }
      return reply(res, 200, await resolveBusinessAdmin({
        sessionToken: token, query,
      }));
    } catch {
      // Never expose company contact, code, bearer, SQL, or mail-provider state.
      return reply(res, 503, { error: 'temporarily_unavailable' });
    }
  };
}

module.exports = makeHandler();
module.exports.makeHandler = makeHandler;
module.exports.businessAdminRuntime = businessAdminRuntime;
