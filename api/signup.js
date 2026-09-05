// Email-only intake: fixed maintainer recipient, no visitor autoresponder,
// no arbitrary content, no secrets or addresses in application logs.
const ORIGINS = new Set(['https://migrate.segeren.com', 'https://codex-migrate.vercel.app']);
const EMAIL = /^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$/;

function reply(res, status, heading, message, analyticsEvent = '') {
  res.statusCode = status;
  res.setHeader('Content-Type', 'text/html; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('X-Robots-Tag', 'noindex');
  // Only static messages enter this template. Never reflect submitted content.
  const eventAttribute = analyticsEvent ? ` data-analytics-event="${analyticsEvent}"` : '';
  res.end(`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex"><title>${heading} — Codex Migrate</title><link rel="stylesheet" href="/styles.css?v=20260904-analytics"><script src="/analytics.js?v=20260904" defer></script></head><body${eventAttribute}><header class="site-header"><a class="brand" href="/">Codex Migrate</a></header><main class="legal shell"><h1>${heading}</h1><p role="status">${message}</p><p><a class="button button-primary" href="/#launch-email">Back to Codex Migrate</a></p><p>Need help? <a href="mailto:joshua@segeren.com?subject=Codex%20Migrate%20launch%20request">Email Josh</a>.</p></main></body></html>`);
}

async function handler(req, res) {
  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST');
    return reply(res, 405, 'Use the signup form', 'Launch requests must be submitted through the form.');
  }
  if (!ORIGINS.has(req.headers.origin)) {
    return reply(res, 403, 'Please use our website', 'Open the signup form on Codex Migrate and try again.');
  }
  const type = (req.headers['content-type'] || '').split(';')[0].trim();
  if (type !== 'application/x-www-form-urlencoded') {
    return reply(res, 415, 'Unsupported request', 'Please use the email form on our website.');
  }
  if (Number(req.headers['content-length']) > 2048) {
    return reply(res, 413, 'Request too large', 'The form only needs your email address and consent.');
  }
  let data = req.body;
  if (typeof data === 'string') {
    if (Buffer.byteLength(data) > 2048) return reply(res, 413, 'Request too large', 'Please use the email form.');
    const params = new URLSearchParams(data);
    if ([...params.keys()].some(key => params.getAll(key).length !== 1)) {
      return reply(res, 400, 'Check your request', 'Please submit one email address.');
    }
    data = Object.fromEntries(params);
  }
  if (!data || typeof data !== 'object' || Array.isArray(data) ||
      Object.keys(data).some(key => !['email', 'consent', 'website'].includes(key)) ||
      Object.values(data).some(value => typeof value !== 'string' || value.length > 254)) {
    return reply(res, 400, 'Check your request', 'Please use the email form and try again.');
  }
  const email = (data.email || '').trim();
  if (data.website || data.consent !== 'yes' || !EMAIL.test(email) || email.length > 254 || email.split('@')[0].length > 64) {
    return reply(res, 400, 'Check your email and consent', 'Enter a valid email address and confirm that you want a launch email.');
  }
  const key = process.env.SENDGRID_API_KEY;
  const from = process.env.LAUNCH_FROM_EMAIL;
  const to = process.env.LAUNCH_NOTIFY_EMAIL;
  if (!key || !EMAIL.test(from || '') || !EMAIL.test(to || '')) {
    return reply(res, 503, 'Email signup is unavailable', 'Your request has not been saved. Please email Josh instead, or try again later.');
  }
  try {
    const response = await fetch('https://api.sendgrid.com/v3/mail/send', {
      method: 'POST',
      headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' },
      signal: AbortSignal.timeout(8000),
      body: JSON.stringify({
        personalizations: [{ to: [{ email: to }] }],
        from: { email: from, name: 'Codex Migrate' },
        reply_to: { email },
        subject: '[Codex Migrate] Launch email request',
        content: [{ type: 'text/plain', value: [
          'A visitor requested a Codex Migrate launch email.',
          `Email: ${email}`,
          'Consent: Please email me when the Mac app is available.',
          `Received: ${new Date().toISOString()}`,
          `Source: ${req.headers.origin}`,
          'No purchase, preorder, or broader marketing consent.',
          'This address is not verified. Confirm ownership before sending launch mail; deduplicate requests and honor removal requests.',
        ].join('\n') }],
        tracking_settings: { click_tracking: { enable: false, enable_text: false }, open_tracking: { enable: false } },
      }),
    });
    if (response.status !== 202) throw new Error('Mail not accepted');
    return reply(res, 200, 'Launch request sent', 'Our email provider accepted your request for delivery to Josh. He manages launch requests personally; this is not a purchase or a preorder. No confirmation email is sent automatically.', 'generate_lead');
  } catch {
    // Do not retry automatically: a timed-out request may already be accepted.
    return reply(res, 503, 'We could not confirm your request', 'There was a problem sending your request. It may not have reached Josh. Please email him instead; you have not been charged.');
  }
}

module.exports = handler;
