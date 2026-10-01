// Explicit sandbox operator trigger; no production cron or customer mail is
// enabled until the 30-minute scheduling and recovery gates are certified.
const { timingSafeEqual } = require('node:crypto');
const { reply } = require('../commerce/http');
const { sandboxDatabaseUrl,
  sandboxDatabaseRuntime } = require('../hosted/recovery_runtime');
const { scanBusinessBackupAlerts,
  businessBackupAlertMail } = require('../hosted/business_backup_alerts');

function authorized(value, secret) {
  if (typeof secret !== 'string' || secret.length < 32 ||
      typeof value !== 'string' || !value.startsWith('Bearer ')) return false;
  const supplied = Buffer.from(value.slice(7));
  const expected = Buffer.from(secret);
  return supplied.length === expected.length &&
    timingSafeEqual(supplied, expected);
}

async function alertRuntime(env) {
  sandboxDatabaseUrl(env);
  return Object.freeze({ query: await sandboxDatabaseRuntime(env),
    sendAlert: value => businessBackupAlertMail(value, env) });
}

function makeHandler(load = alertRuntime, env = process.env) {
  return async (req, res) => {
    if (env.HOSTED_MODE !== 'sandbox' ||
        env.HOSTED_BUSINESS_ALERT_SANDBOX_OPEN !== 'yes') {
      return reply(res, 404, { error: 'not_found' });
    }
    if (req.method !== 'GET') {
      res.setHeader('Allow', 'GET');
      return reply(res, 405, { error: 'get_required' });
    }
    if (!authorized(req.headers.authorization,
      env.HOSTED_BUSINESS_ALERT_SCAN_SECRET)) {
      return reply(res, 403, { error: 'access_denied' });
    }
    res.setHeader('Cache-Control', 'no-store');
    try {
      const { query, sendAlert } = await load(env);
      return reply(res, 200, await scanBusinessBackupAlerts({
        query, sendAlert,
      }));
    } catch {
      return reply(res, 503, { error: 'temporarily_unavailable' });
    }
  };
}

module.exports = makeHandler();
module.exports.makeHandler = makeHandler;
module.exports.alertRuntime = alertRuntime;
