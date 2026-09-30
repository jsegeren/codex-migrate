// Sandbox-only, metadata-only business alert delivery. Claimed rows are never
// automatically retried: a crash or ambiguous mail response needs an operator
// to reconcile the provider before any resend is authorized.
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const EMAIL = /^[^\s<>@\r\n]+@[^\s<>@\r\n]+\.[^\s<>@\r\n]+$/;
const REASONS = new Set(['not_enrolled', 'no_published_backup',
  'no_check', 'failed_run', 'overdue', 'worker_attention',
  'snapshot_mismatch', 'incomplete_sources']);
const CLAIM_SQL = 'SELECT * FROM hosted.claim_business_backup_alerts()';
const RECORD_SQL = `SELECT hosted.record_business_backup_alert_delivery(
  $1::uuid, $2::text) AS recorded`;
const REVIEW_SQL = `SELECT count(*)::integer AS operator_review
  FROM hosted.business_backup_alerts
  WHERE resolved_at IS NULL AND
    (delivery_state IN ('rejected', 'uncertain') OR
      (delivery_state = 'claimed' AND
       claimed_at < clock_timestamp() - interval '10 minutes'))`;

class BusinessAlertError extends Error {
  constructor() { super('business_alert_unavailable'); }
}

async function scanBusinessBackupAlerts({ query, sendAlert }) {
  if (typeof query !== 'function' || typeof sendAlert !== 'function') {
    throw new BusinessAlertError();
  }
  try {
    const result = await query(CLAIM_SQL, []);
    if (!Array.isArray(result?.rows) || result.rows.length > 3) {
      throw new BusinessAlertError();
    }
    let accepted = 0;
    let uncertain = 0;
    let rejected = 0;
    for (const row of result.rows) {
      if (!UUID.test(row.alert_id) || !UUID.test(row.seat_id) ||
          !EMAIL.test(row.admin_contact_email) ||
          !REASONS.has(row.reason)) throw new BusinessAlertError();
      let outcome;
      try {
        outcome = await sendAlert({ alertId: row.alert_id,
          to: row.admin_contact_email, seatId: row.seat_id,
          reason: row.reason, purpose: 'business-backup-alert-sandbox' });
      } catch { outcome = 'uncertain'; }
      const state = outcome === 'accepted' ? 'accepted' :
        outcome === 'rejected' ? 'rejected' : 'uncertain';
      const recorded = await query(RECORD_SQL, [row.alert_id, state]);
      if (recorded?.rows?.length !== 1 ||
          recorded.rows[0]?.recorded !== true) throw new BusinessAlertError();
      if (state === 'accepted') accepted++;
      else if (state === 'rejected') rejected++;
      else uncertain++;
    }
    const review = await query(REVIEW_SQL, []);
    const operatorReview = review?.rows?.[0]?.operator_review;
    if (review?.rows?.length !== 1 ||
        !Number.isSafeInteger(operatorReview) || operatorReview < 0) {
      throw new BusinessAlertError();
    }
    return Object.freeze({ claimed: result.rows.length, accepted,
      rejected, uncertain, operatorReview });
  } catch { throw new BusinessAlertError(); }
}

async function businessBackupAlertMail({ alertId, to, seatId, reason, purpose },
  env = process.env, request = fetch) {
  if (purpose !== 'business-backup-alert-sandbox' || !UUID.test(alertId) ||
      !UUID.test(seatId) || !REASONS.has(reason) ||
      typeof to !== 'string' || to !== env.COMMERCE_SANDBOX_EMAIL ||
      !EMAIL.test(to) || !EMAIL.test(env.LAUNCH_FROM_EMAIL || '') ||
      !env.SENDGRID_API_KEY) return 'rejected';
  try {
    const response = await request('https://api.sendgrid.com/v3/mail/send', {
      method: 'POST', redirect: 'error', signal: AbortSignal.timeout(8000),
      headers: { Authorization: `Bearer ${env.SENDGRID_API_KEY}`,
        'Content-Type': 'application/json' },
      body: JSON.stringify({
        from: { email: env.LAUNCH_FROM_EMAIL, name: 'Codex Backup' },
        personalizations: [{ to: [{ email: to }],
          subject: 'TEST ONLY — Codex Backup seat needs attention' }],
        content: [{ type: 'text/plain', value: [
          'Sandbox test only. No company backup service is active.',
          'A seat backup needs attention. Check the service health receipt; do not assume this seat is protected.',
          `Seat reference: ${seatId}`,
          `Reason: ${reason}`,
          `Alert reference: ${alertId}`,
          'This message contains no Codex conversation content or recovery key.',
        ].join('\n\n') }],
        tracking_settings: { click_tracking: { enable: false, enable_text: false },
          open_tracking: { enable: false } },
      }),
    });
    if (response.status === 202) return 'accepted';
    return response.status >= 400 && response.status < 500 ?
      'rejected' : 'uncertain';
  } catch { return 'uncertain'; }
}

module.exports = { BusinessAlertError, scanBusinessBackupAlerts,
  businessBackupAlertMail };
