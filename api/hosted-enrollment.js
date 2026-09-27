// Sandbox-only first-device enrollment. This proves ownership of an existing
// app purchase and its email, but grants zero upload capacity. It does not
// start a hosted trial, subscription, or backup.
const { reply } = require('../commerce/http');
const { runtime: commerceRuntime } = require('../commerce/runtime');
const { sandboxDatabaseUrl,
  sandboxDatabaseRuntime } = require('../hosted/recovery_runtime');
const { enrollmentMail } = require('../hosted/enrollment_mail');
const { beginEnrollment, claimEnrollment,
  resolveFirstDevice } = require('../hosted/enrollment');

const BEARER = /^Bearer (hv1_[A-Za-z0-9_-]{43})$/;
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
  const expected = data.action === 'begin' ? 'action,purchaseToken' :
    data.action === 'claim' ?
      'action,code,deviceId,deviceTokenHash,purchaseToken' :
    data.action === 'resolve' ? 'action,deviceId' : null;
  if (keys !== expected ||
      (data.action !== 'resolve' &&
        (typeof data.purchaseToken !== 'string' ||
         data.purchaseToken.length > 330)) ||
      (data.action === 'claim' &&
        (typeof data.code !== 'string' || typeof data.deviceId !== 'string' ||
         typeof data.deviceTokenHash !== 'string')) ||
      (data.action === 'resolve' && typeof data.deviceId !== 'string')) {
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
    if (data.action === 'resolve' && !token) {
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
      if (data.action === 'claim') {
        return reply(res, 200, await claimEnrollment({
          purchaseToken: data.purchaseToken, code: data.code,
          deviceId: data.deviceId, deviceTokenHash: data.deviceTokenHash,
          verifyPurchase: verifyPurchaseToken, query,
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
