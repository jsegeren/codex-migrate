// Dark, metadata-only seat health. Never exposes conversation content or a
// customer-facing protection claim; no route is open without two sandbox flags.
const { reply } = require('../commerce/http');
const { allowedBrowserOrigin } = require('../hosted/http_origin');
const { sandboxDatabaseUrl,
  sandboxDatabaseRuntime } = require('../hosted/recovery_runtime');
const { reportBusinessCheck, listBusinessHealth } =
  require('../hosted/business_health');

const WORKER = /^Bearer (hvb1_[A-Za-z0-9_-]{43})$/;
const ADMIN = /^Bearer (hva1_[A-Za-z0-9_-]{43})$/;

function body(req) {
  if (!allowedBrowserOrigin(req.headers.origin) ||
      (req.headers['content-type'] || '').split(';')[0] !== 'application/json' ||
      Number(req.headers['content-length']) > 256 ||
      !req.body || typeof req.body !== 'object' || Array.isArray(req.body) ||
      Buffer.byteLength(JSON.stringify(req.body)) > 256) {
    throw Error('invalid_request');
  }
  const data = req.body;
  const keys = Object.keys(data).sort().join(',');
  if (data.action === 'list' && keys === 'action') return data;
  if (data.action === 'report' &&
      keys === 'action,deviceId,reportedState,snapshotId' &&
      typeof data.deviceId === 'string' &&
      typeof data.reportedState === 'string' &&
      (data.snapshotId === null || typeof data.snapshotId === 'string')) {
    return data;
  }
  throw Error('invalid_request');
}

async function businessHealthRuntime(env) {
  sandboxDatabaseUrl(env);
  return Object.freeze({ query: await sandboxDatabaseRuntime(env) });
}

function makeHandler(load = businessHealthRuntime, env = process.env) {
  return async (req, res) => {
    if (env.HOSTED_MODE !== 'sandbox' ||
        env.HOSTED_BUSINESS_HEALTH_SANDBOX_OPEN !== 'yes') {
      return reply(res, 404, { error: 'not_found' });
    }
    if (req.method !== 'POST') {
      res.setHeader('Allow', 'POST');
      return reply(res, 405, { error: 'post_required' });
    }
    let data;
    try { data = body(req); }
    catch { return reply(res, 400, { error: 'invalid_request' }); }
    const authorization = req.headers.authorization || '';
    const token = (data.action === 'report' ? WORKER : ADMIN)
      .exec(authorization)?.[1];
    if (!token) return reply(res, 403, { error: 'access_denied' });
    res.setHeader('Cache-Control', 'no-store');
    try {
      const { query } = await load(env);
      if (data.action === 'report') {
        return reply(res, 200, await reportBusinessCheck({
          deviceToken: token, deviceId: data.deviceId,
          reportedState: data.reportedState,
          snapshotId: data.snapshotId, query,
        }));
      }
      return reply(res, 200, await listBusinessHealth({
        adminToken: token, query,
      }));
    } catch {
      return reply(res, 503, { error: 'temporarily_unavailable' });
    }
  };
}

module.exports = makeHandler();
module.exports.makeHandler = makeHandler;
module.exports.businessHealthRuntime = businessHealthRuntime;
