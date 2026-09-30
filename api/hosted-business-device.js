// Dark sandbox-only first-device pairing. Separately gated upload/owner-read
// still requires a current business allowance; pairing alone grants neither
// storage, company recovery, nor administrator content access.
const { reply } = require('../commerce/http');
const { allowedBrowserOrigin } = require('../hosted/http_origin');
const { sandboxDatabaseUrl,
  sandboxDatabaseRuntime } = require('../hosted/recovery_runtime');
const { businessWorkerMail } = require('../hosted/business_worker_mail');
const { beginBusinessWorkerPairing, claimBusinessFirstDevice,
  resolveBusinessFirstDevice, rotateBusinessWorkerDevice } =
  require('../hosted/business_worker');

const ADMIN_BEARER = /^Bearer (hva1_[A-Za-z0-9_-]{43})$/;
const DEVICE_BEARER = /^Bearer (hvb1_[A-Za-z0-9_-]{43})$/;
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
  const expected = data.action === 'begin' ? 'accountId,action,seatId' :
    data.action === 'claim' ?
      'accountId,action,code,deviceId,deviceTokenHash,seatId,vaultId' :
    data.action === 'resolve' ? 'action,deviceId' :
    data.action === 'rotate' ?
      'action,newDeviceId,newDeviceTokenHash,oldDeviceId' : null;
  if (keys !== expected ||
      (['begin', 'claim'].includes(data.action) &&
        (typeof data.accountId !== 'string' ||
         typeof data.seatId !== 'string')) ||
      (data.action === 'claim' &&
        ['code', 'vaultId', 'deviceId', 'deviceTokenHash']
          .some(key => typeof data[key] !== 'string')) ||
      (data.action === 'resolve' && typeof data.deviceId !== 'string') ||
      (data.action === 'rotate' &&
        ['oldDeviceId', 'newDeviceId', 'newDeviceTokenHash']
          .some(key => typeof data[key] !== 'string'))) {
    throw Error('invalid_request');
  }
  return data;
}

async function businessWorkerRuntime(env) {
  sandboxDatabaseUrl(env);
  return Object.freeze({ query: await sandboxDatabaseRuntime(env),
    sendChallenge: value => businessWorkerMail(value, env) });
}

function makeHandler(load = businessWorkerRuntime, env = process.env) {
  return async (req, res) => {
    if (env.HOSTED_MODE !== 'sandbox' ||
        env.HOSTED_BUSINESS_WORKER_SANDBOX_OPEN !== 'yes') {
      return reply(res, 404, { error: 'not_found' });
    }
    if (req.method !== 'POST') {
      res.setHeader('Allow', 'POST');
      return reply(res, 405, { error: 'post_required' });
    }
    let data;
    try { data = requestBody(req); }
    catch { return reply(res, 400, { error: 'invalid_request' }); }
    const authorization = req.headers.authorization || '';
    const adminToken = ADMIN_BEARER.exec(authorization)?.[1];
    const deviceToken = DEVICE_BEARER.exec(authorization)?.[1];
    if ((data.action === 'begin' && !adminToken) ||
        (['resolve', 'rotate'].includes(data.action) && !deviceToken)) {
      return reply(res, 403, { error: 'access_denied' });
    }
    res.setHeader('Cache-Control', 'no-store');
    try {
      const { query, sendChallenge } = await load(env);
      if (data.action === 'begin') {
        return reply(res, 200, await beginBusinessWorkerPairing({
          adminSessionToken: adminToken, accountId: data.accountId,
          seatId: data.seatId,
          query, sendChallenge,
        }));
      }
      if (data.action === 'claim') {
        return reply(res, 200, await claimBusinessFirstDevice({
          accountId: data.accountId, seatId: data.seatId,
          code: data.code, vaultId: data.vaultId, deviceId: data.deviceId,
          deviceTokenHash: data.deviceTokenHash, query,
        }));
      }
      if (data.action === 'rotate') {
        return reply(res, 200, await rotateBusinessWorkerDevice({
          oldDeviceToken: deviceToken, oldDeviceId: data.oldDeviceId,
          newDeviceId: data.newDeviceId,
          newDeviceTokenHash: data.newDeviceTokenHash, query,
        }));
      }
      return reply(res, 200, await resolveBusinessFirstDevice({
        deviceToken, deviceId: data.deviceId, query,
      }));
    } catch {
      return reply(res, 503, { error: 'temporarily_unavailable' });
    }
  };
}

module.exports = makeHandler();
module.exports.makeHandler = makeHandler;
module.exports.businessWorkerRuntime = businessWorkerRuntime;
