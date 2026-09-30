const test = require('node:test');
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { makeHandler } = require('../api/hosted-business-alert-scan');
const { scanBusinessBackupAlerts, businessBackupAlertMail } =
  require('../hosted/business_backup_alerts');

function response() {
  return { headers: {}, setHeader(key, value) { this.headers[key] = value; },
    end(value) { this.body = JSON.parse(value); } };
}

test('dark scan rejects requests before loading database or mail', async () => {
  const env = { HOSTED_MODE: 'sandbox',
    HOSTED_BUSINESS_ALERT_SANDBOX_OPEN: 'yes',
    HOSTED_BUSINESS_ALERT_SCAN_SECRET: 'a'.repeat(32) };
  let loads = 0;
  const handler = makeHandler(async () => { loads++; return {}; }, env);
  const req = { method: 'GET', headers: { authorization:
    `Bearer ${'a'.repeat(32)}` } };
  async function send() { const res = response(); await handler(req, res);
    return res; }
  env.HOSTED_BUSINESS_ALERT_SANDBOX_OPEN = 'no';
  assert.equal((await send()).statusCode, 404);
  env.HOSTED_BUSINESS_ALERT_SANDBOX_OPEN = 'yes';
  env.HOSTED_MODE = 'live';
  assert.equal((await send()).statusCode, 404);
  env.HOSTED_MODE = 'sandbox';
  req.method = 'POST';
  assert.equal((await send()).statusCode, 405);
  req.method = 'GET';
  req.headers.authorization = `Bearer ${'b'.repeat(32)}`;
  assert.equal((await send()).statusCode, 403);
  req.headers.authorization = `Bearer ${'a'.repeat(31)}`;
  assert.equal((await send()).statusCode, 403);
  assert.equal(loads, 0);
});

test('a claimed alert is sent once and its delivery result is recorded', async () => {
  const alertId = randomUUID();
  const seatId = randomUUID();
  const env = { HOSTED_MODE: 'sandbox',
    HOSTED_BUSINESS_ALERT_SANDBOX_OPEN: 'yes',
    HOSTED_BUSINESS_ALERT_SCAN_SECRET: 'a'.repeat(32) };
  let claimed = false;
  let sent;
  let recorded;
  const handler = makeHandler(async () => ({
    query: async (sql, values) => {
      if (sql.includes('claim_business_backup_alerts')) {
        assert.deepEqual(values, []);
        if (claimed) return { rows: [] };
        claimed = true;
        return { rows: [{ alert_id: alertId,
          admin_contact_email: 'admin@example.test', seat_id: seatId,
          reason: 'overdue' }] };
      }
      if (sql.includes('operator_review')) {
        assert.deepEqual(values, []);
        return { rows: [{ operator_review: 0 }] };
      }
      assert.match(sql, /record_business_backup_alert_delivery/);
      assert.deepEqual(values, [alertId, 'accepted']);
      recorded = true;
      return { rows: [{ recorded: true }] };
    },
    sendAlert: async value => { sent = value; return 'accepted'; },
  }), env);
  const req = { method: 'GET', headers: { authorization:
    `Bearer ${'a'.repeat(32)}` } };
  const res = response();
  await handler(req, res);
  assert.equal(res.statusCode, 200);
  assert.deepEqual(res.body, { claimed: 1, accepted: 1,
    rejected: 0, uncertain: 0, operatorReview: 0 });
  assert.equal(sent.alertId, alertId);
  assert.equal(sent.reason, 'overdue');
  assert.equal(sent.purpose, 'business-backup-alert-sandbox');
  assert.equal(recorded, true);
  assert.equal(res.headers['Cache-Control'], 'no-store');
  const again = response();
  await handler(req, again);
  assert.deepEqual(again.body, { claimed: 0, accepted: 0,
    rejected: 0, uncertain: 0, operatorReview: 0 });
});

test('ambiguous delivery is recorded uncertain, never treated as accepted', async () => {
  const alertId = randomUUID();
  const seatId = randomUUID();
  const writes = [];
  const result = await scanBusinessBackupAlerts({
    query: async (sql, values) => {
      if (sql.includes('claim_business_backup_alerts')) {
        return { rows: [{ alert_id: alertId,
          admin_contact_email: 'admin@example.test', seat_id: seatId,
          reason: 'failed_run' }] };
      }
      if (sql.includes('operator_review')) {
        return { rows: [{ operator_review: 1 }] };
      }
      writes.push(values);
      return { rows: [{ recorded: true }] };
    },
    sendAlert: async () => { throw Error('timeout after send'); },
  });
  assert.deepEqual(result, { claimed: 1, accepted: 0,
    rejected: 0, uncertain: 1, operatorReview: 1 });
  assert.deepEqual(writes, [[alertId, 'uncertain']]);
});

test('sandbox mail has a unique reference, no tracking, no content, and fails shut', async () => {
  const env = { COMMERCE_SANDBOX_EMAIL: 'admin@example.test',
    LAUNCH_FROM_EMAIL: 'sender@example.test', SENDGRID_API_KEY: 'fixture' };
  const input = { alertId: randomUUID(), seatId: randomUUID(),
    to: 'admin@example.test', reason: 'overdue',
    purpose: 'business-backup-alert-sandbox' };
  let body;
  const request = async (_url, options) => {
    body = JSON.parse(options.body);
    return { status: 202 };
  };
  assert.equal(await businessBackupAlertMail(input, env, request), 'accepted');
  assert.match(body.content[0].value, new RegExp(input.alertId));
  assert.equal(body.tracking_settings.open_tracking.enable, false);
  assert.equal(JSON.stringify(body).includes('conversation text'), false);
  assert.equal(await businessBackupAlertMail({ ...input,
    to: 'other@example.test' }, env, request), 'rejected');
  assert.equal(await businessBackupAlertMail(input, env,
    async () => { throw Error('network'); }), 'uncertain');
});
