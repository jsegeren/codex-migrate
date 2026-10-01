// Sandbox sink only: worker pairing emails are not sent to real employees.
async function businessWorkerMail({ to, code, purpose }, env = process.env,
  request = fetch) {
  const email = /^[^\s<>@\r\n]+@[^\s<>@\r\n]+\.[^\s<>@\r\n]+$/;
  if (purpose !== 'business-worker-sandbox' ||
      typeof code !== 'string' ||
      !/^hvwe1_[A-Za-z0-9_-]{43}$/.test(code) ||
      typeof to !== 'string' || to !== env.COMMERCE_SANDBOX_EMAIL ||
      !email.test(to) || !email.test(env.LAUNCH_FROM_EMAIL || '') ||
      !env.SENDGRID_API_KEY) return 'rejected';
  try {
    const response = await request('https://api.sendgrid.com/v3/mail/send', {
      method: 'POST', redirect: 'error', signal: AbortSignal.timeout(8000),
      headers: { Authorization: `Bearer ${env.SENDGRID_API_KEY}`,
        'Content-Type': 'application/json' },
      body: JSON.stringify({
        from: { email: env.LAUNCH_FROM_EMAIL, name: 'Codex Backup' },
        personalizations: [{ to: [{ email: to }],
          subject: 'TEST ONLY — Codex Backup worker pairing' }],
        content: [{ type: 'text/plain', value: [
          'Sandbox test only. No company backup service is active.',
          code,
          'This code expires in 10 minutes. It pairs only a test device and does not start or authorize a backup.',
          'If you did not request this, ignore the message.',
        ].join('\n\n') }],
        tracking_settings: { click_tracking: { enable: false, enable_text: false },
          open_tracking: { enable: false } },
      }),
    });
    if (response.status === 202) return 'accepted';
    return response.status >= 400 && response.status < 500 ? 'rejected' : 'uncertain';
  } catch { return 'uncertain'; }
}

module.exports = { businessWorkerMail };
