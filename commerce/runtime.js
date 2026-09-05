const Stripe = require('stripe');
const { database } = require('./database');
const { sql } = require('drizzle-orm');
const { configuration, CommerceError } = require('./config');
const { purchaseStore } = require('./store');
const { service } = require('./service');
const { privateDownloads } = require('./artifacts');

async function deliveryMail({ to, link, release, live }, env = process.env, request = fetch) {
  const from = env.LAUNCH_FROM_EMAIL;
  if (!env.SENDGRID_API_KEY || !/^[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+$/.test(from || '')) return 'rejected';
  // An explicitly configured sink prevents sandbox fixtures mailing customers.
  if (!live && to !== env.COMMERCE_SANDBOX_EMAIL) return 'rejected';
  try {
    const response = await request('https://api.sendgrid.com/v3/mail/send', {
      method: 'POST', redirect: 'error', signal: AbortSignal.timeout(8000),
      headers: { Authorization: `Bearer ${env.SENDGRID_API_KEY}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        from: { email: from, name: 'Codex Migrate' },
        reply_to: { email: 'joshua@segeren.com', name: 'Joshua Segeren' },
        personalizations: [{ to: [{ email: to }] }],
        subject: live ? 'Your Codex Migrate download' : 'TEST ONLY — Codex Migrate delivery check',
        content: [{ type: 'text/plain', value: [
          live ? 'Thank you for purchasing Codex Migrate.' : 'Sandbox test only. No real purchase or app is delivered.',
          `Open your download: ${link}`,
          `Release: ${release.id}`, `Archive SHA-256: ${release.sha256}`,
          'Keep this email to recover your download. Treat this link as private.',
          'Need help? Reply to joshua@segeren.com. Please do not send credentials or workspace contents.',
          'This is a purchase-delivery message, not a marketing subscription.',
        ].join('\n\n') }],
        tracking_settings: { click_tracking: { enable: false, enable_text: false }, open_tracking: { enable: false } },
      }),
    });
    if (response.status === 202) return 'accepted';
    // 4xx explicitly rejected the send. 5xx/timeout is ambiguous; do not guess.
    return response.status >= 400 && response.status < 500 ? 'rejected' : 'uncertain';
  } catch { return 'uncertain'; }
}
async function runtime(env = process.env) {
  const config = configuration(env);
  let url;
  try { url = new URL(env.COMMERCE_DATABASE_URL); } catch { throw new CommerceError('database_unavailable'); }
  if (!['postgres:', 'postgresql:'].includes(url.protocol) || !url.hostname.endsWith('.neon.tech')) {
    throw new CommerceError('database_unavailable');
  }
  const db = database(url.toString());
  const identity = await db.execute(sql`select mode from commerce_environment where name = 'codex-migrate-commerce'`);
  if (identity.rows.length !== 1 || identity.rows[0].mode !== config.mode) throw new CommerceError('database_environment_mismatch');
  const stripe = new Stripe(config.key, { apiVersion: '2025-03-31.basil', maxNetworkRetries: 0, timeout: 10000 });
  const store = purchaseStore(db);
  return { config, stripe, service: service({ config, stripe, store,
    signDownload: privateDownloads(config, env), sendMail: value => deliveryMail(value, env) }) };
}
module.exports = { runtime, deliveryMail };
