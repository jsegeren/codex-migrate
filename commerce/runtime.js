const Stripe = require('stripe');
const { database } = require('./database');
const { sql } = require('drizzle-orm');
const { configuration, CommerceError, PRICE_CENTS } = require('./config');
const { purchaseStore, checkoutRecoveryStore } = require('./store');
const { service, checkoutRecovery } = require('./service');
const { privateDownloads } = require('./artifacts');

const PURCHASE_NOTIFY_EMAILS = ['segerej@gmail.com', 'joshua@segeren.com'];

function usd(cents) {
  return Number.isSafeInteger(cents) ? `$${(cents / 100).toFixed(2)} USD` : `$${(PRICE_CENTS / 100).toFixed(2)} USD`;
}

async function deliveryMail({ to, link, release, live, sessionId, paymentIntent, amountTotal }, env = process.env, request = fetch) {
  const from = env.LAUNCH_FROM_EMAIL;
  if (!env.SENDGRID_API_KEY || !/^[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+$/.test(from || '')) return 'rejected';
  // An explicitly configured sink prevents sandbox fixtures mailing customers.
  if (!live && to !== env.COMMERCE_SANDBOX_EMAIL) return 'rejected';
  const buyer = {
    to: [{ email: to }],
    subject: live ? 'Your Codex Migrate download' : 'TEST ONLY — Codex Migrate delivery check',
    substitutions: {
      '%intro%': live ? 'Thank you for purchasing Codex Migrate.' :
        release.testingOnly === true && release.kind === 'signed-notarized'
          ? 'Sandbox test only. No real payment was charged. This delivers the signed app candidate for operator testing, not a publicly released product.'
          : 'Sandbox test only. No real purchase or app is delivered.',
      '%details%': `Open your download: ${link}`,
      '%closing%': 'Keep this email to recover your download. Treat this link as private.\n\nNeed help? Reply to joshua@segeren.com. Please do not send credentials or workspace contents.\n\nThis is a purchase-delivery message, not a marketing subscription.',
    },
  };
  // One accepted SendGrid request delivers the buyer copy and both operator
  // alerts. The store's unique purchase claim therefore suppresses duplicate
  // alerts when Stripe retries the same webhook.
  const personalizations = [buyer];
  if (live) {
    const operatorDetails = [
      `Buyer: ${to}`,
      `Amount: ${usd(amountTotal)}`,
      `Stripe session: ${sessionId || 'unavailable'}`,
      `Payment intent: ${paymentIntent || 'unavailable'}`,
    ].join('\n');
    // SendGrid rejects a recipient repeated anywhere in one Mail Send request.
    // If the buyer uses one of the operator addresses, that inbox already gets
    // the buyer delivery, while the other operator still receives its alert.
    for (const email of PURCHASE_NOTIFY_EMAILS.filter(email => email.toLowerCase() !== to.toLowerCase())) {
      personalizations.push({
        to: [{ email }],
        subject: `[Codex Migrate] New purchase — ${usd(amountTotal)}`,
        substitutions: {
          '%intro%': 'A live Codex Migrate purchase was verified and fulfilled.',
          '%details%': operatorDetails,
          '%closing%': paymentIntent
            ? `Open in Stripe: https://dashboard.stripe.com/payments/${paymentIntent}`
            : 'Open the Stripe Dashboard to review the purchase.',
        },
      });
    }
  }
  try {
    const response = await request('https://api.sendgrid.com/v3/mail/send', {
      method: 'POST', redirect: 'error', signal: AbortSignal.timeout(8000),
      headers: { Authorization: `Bearer ${env.SENDGRID_API_KEY}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        from: { email: from, name: 'Codex Migrate' },
        reply_to: { email: 'joshua@segeren.com', name: 'Joshua Segeren' },
        personalizations,
        content: [{ type: 'text/plain', value: [
          '%intro%',
          '%details%',
          `Release: ${release.id}`, `Archive SHA-256: ${release.sha256}`,
          ...(release.channel === 'beta' ? ['This is the signed, notarized beta for Apple silicon Macs. Native accessibility, permissions and physical network-interruption testing are ongoing. Keep your old Mac and an independent backup. Details: https://migrate.segeren.com/#founding-edition'] : []),
          '%closing%',
        ].join('\n\n') }],
        tracking_settings: { click_tracking: { enable: false, enable_text: false }, open_tracking: { enable: false } },
      }),
    });
    if (response.status === 202) return 'accepted';
    // 4xx explicitly rejected the send. 5xx/timeout is ambiguous; do not guess.
    return response.status >= 400 && response.status < 500 ? 'rejected' : 'uncertain';
  } catch { return 'uncertain'; }
}
async function recoveryMail({ to, link, release, live }, env = process.env, request = fetch) {
  const from = env.LAUNCH_FROM_EMAIL;
  if (!env.SENDGRID_API_KEY || !/^[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+$/.test(from || '')) return 'rejected';
  if (!live && to !== env.COMMERCE_SANDBOX_EMAIL) return 'rejected';
  try {
    const response = await request('https://api.sendgrid.com/v3/mail/send', {
      method: 'POST', redirect: 'error', signal: AbortSignal.timeout(8000),
      headers: { Authorization: `Bearer ${env.SENDGRID_API_KEY}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        from: { email: from, name: 'Codex Migrate' },
        reply_to: { email: 'joshua@segeren.com', name: 'Joshua Segeren' },
        personalizations: [{ to: [{ email: to }],
          subject: live ? 'Finish your Codex Migrate purchase' : 'TEST ONLY — Codex Migrate checkout recovery' }],
        content: [{ type: 'text/plain', value: [
          live ? 'You started a Codex Migrate purchase but did not finish checkout.' :
            'Sandbox test only. No real payment was charged.',
          `Continue securely through Stripe: ${link}`,
          `Release: ${release.id}`,
          'Codex Migrate moves local Codex work directly between Macs. The signed and Apple-notarized Apple-silicon beta is $49 once, with best-effort support and a 30-day refund policy.',
          'This is one checkout reminder because you opted in on Stripe Checkout. You are not being added to a marketing list, and we will not send another reminder for this checkout.',
          'Questions? Reply to joshua@segeren.com.',
        ].join('\n\n') }],
        tracking_settings: { click_tracking: { enable: false, enable_text: false }, open_tracking: { enable: false } },
      }),
    });
    if (response.status === 202) return 'accepted';
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
  return { config, stripe,
    service: service({ config, stripe, store,
      signDownload: privateDownloads(config, env), sendMail: value => deliveryMail(value, env) }),
    recovery: checkoutRecovery({ config, stripe, store: checkoutRecoveryStore(db),
      sendMail: value => recoveryMail(value, env) }) };
}
module.exports = { runtime, deliveryMail, recoveryMail, PURCHASE_NOTIFY_EMAILS };
