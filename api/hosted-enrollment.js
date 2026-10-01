// Sandbox-only enrollment and scoped device rotation. Pairing proves an
// existing purchase and email, but grants zero upload capacity. Neither
// action starts a hosted trial, subscription, or backup.
const { reply } = require('../commerce/http');
const { allowedBrowserOrigin } = require('../hosted/http_origin');
const { runtime: commerceRuntime } = require('../commerce/runtime');
const { sandboxDatabaseUrl,
  sandboxDatabaseRuntime } = require('../hosted/recovery_runtime');
const { enrollmentMail } = require('../hosted/enrollment_mail');
const { beginEnrollment, claimEnrollment,
  resolveFirstDevice, rotateDeviceSession, beginRecovery, listRecoveryVaults,
  claimRecoveryVault } = require('../hosted/enrollment');

const BEARER = /^Bearer (hv1_[A-Za-z0-9_-]{43})$/;
const MAX_BODY = 700;

function requestBody(req) {
  if (!allowedBrowserOrigin(req.headers.origin)) {
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
  const expected = ['begin', 'begin_recovery'].includes(data.action) ?
    'action,purchaseToken' :
    data.action === 'claim' ?
      'action,code,deviceId,deviceTokenHash,purchaseToken' :
    data.action === 'list_recovery_vaults' ?
      'action,code,purchaseToken' :
    data.action === 'claim_recovery' ?
      'action,code,deviceId,deviceTokenHash,purchaseToken,vaultId' :
    data.action === 'resolve' ? 'action,deviceId' :
    data.action === 'rotate' ?
      'action,newDeviceId,newDeviceTokenHash,oldDeviceId' : null;
  if (keys !== expected ||
      (!['resolve', 'rotate'].includes(data.action) &&
        (typeof data.purchaseToken !== 'string' ||
         data.purchaseToken.length > 330)) ||
      (['claim', 'claim_recovery'].includes(data.action) &&
        (typeof data.code !== 'string' || typeof data.deviceId !== 'string' ||
         typeof data.deviceTokenHash !== 'string')) ||
      (data.action === 'list_recovery_vaults' &&
        typeof data.code !== 'string') ||
      (data.action === 'claim_recovery' &&
        typeof data.vaultId !== 'string') ||
      (data.action === 'resolve' && typeof data.deviceId !== 'string') ||
      (data.action === 'rotate' &&
        (typeof data.oldDeviceId !== 'string' ||
         typeof data.newDeviceId !== 'string' ||
         typeof data.newDeviceTokenHash !== 'string'))) {
    throw Error('invalid_request');
  }
  return data;
}

async function enrollmentRuntime(env) {
  // Refuse an accidental live-commerce configuration before either runtime
  // opens a database or contacts Stripe.
  if (env.COMMERCE_MODE !== 'sandbox') throw Error('hosted_enrollment_unavailable');
  sandboxDatabaseUrl(env);
  const [query, commerce] = await Promise.all([
    sandboxDatabaseRuntime(env), commerceRuntime(env),
  ]);
  if (commerce.config.mode !== 'sandbox' || commerce.config.live !== false) {
    throw Error('hosted_enrollment_unavailable');
  }
  return Object.freeze({ query,
    verifyPurchaseToken: commerce.service.verifyForHostedEnrollment,
    verifyPurchaseSession: commerce.service.verifyForHostedAuthorization,
    sendChallenge: value => enrollmentMail(value, env) });
}

function makeHandler(load = enrollmentRuntime, env = process.env) {
  return async (req, res) => {
    if (env.HOSTED_MODE !== 'sandbox' ||
        env.HOSTED_SANDBOX_ENROLLMENT_OPEN !== 'yes') {
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
    if (['resolve', 'rotate'].includes(data.action) && !token) {
      return reply(res, 403, { error: 'access_denied' });
    }
    try {
      const { query, verifyPurchaseToken, verifyPurchaseSession,
        sendChallenge } = await load(env);
      if (data.action === 'begin') {
        return reply(res, 200, await beginEnrollment({
          purchaseToken: data.purchaseToken,
          verifyPurchase: verifyPurchaseToken, query, sendChallenge,
        }));
      }
      if (data.action === 'begin_recovery') {
        return reply(res, 200, await beginRecovery({
          purchaseToken: data.purchaseToken,
          verifyPurchase: verifyPurchaseToken, query, sendChallenge,
        }));
      }
      if (data.action === 'claim') {
        return reply(res, 200, await claimEnrollment({
          purchaseToken: data.purchaseToken, code: data.code,
          deviceId: data.deviceId, deviceTokenHash: data.deviceTokenHash,
          verifyPurchase: verifyPurchaseToken, query,
        }));
      }
      if (data.action === 'list_recovery_vaults') {
        return reply(res, 200, await listRecoveryVaults({
          purchaseToken: data.purchaseToken, code: data.code,
          verifyPurchase: verifyPurchaseToken, query,
        }));
      }
      if (data.action === 'claim_recovery') {
        return reply(res, 200, await claimRecoveryVault({
          purchaseToken: data.purchaseToken, code: data.code,
          vaultId: data.vaultId, deviceId: data.deviceId,
          deviceTokenHash: data.deviceTokenHash,
          verifyPurchase: verifyPurchaseToken, query,
        }));
      }
      if (data.action === 'rotate') {
        return reply(res, 200, await rotateDeviceSession({
          oldDeviceToken: token, oldDeviceId: data.oldDeviceId,
          newDeviceId: data.newDeviceId,
          newDeviceTokenHash: data.newDeviceTokenHash,
          verifyPurchase: verifyPurchaseSession, query,
        }));
      }
      return reply(res, 200, await resolveFirstDevice({
        deviceToken: token, deviceId: data.deviceId,
        verifyPurchase: verifyPurchaseSession, query,
      }));
    } catch {
      // Never return purchase, email, code, bearer, SQL, or Stripe details.
      return reply(res, 503, { error: 'temporarily_unavailable' });
    }
  };
}

module.exports = makeHandler();
module.exports.makeHandler = makeHandler;
module.exports.enrollmentRuntime = enrollmentRuntime;
