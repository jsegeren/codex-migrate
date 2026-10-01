// A sandbox sink is deliberately the only delivery target. A live company
// recovery notification needs its own approved identity and incident process.
async function businessRecoveryMail({ to, code, purpose, requestId },
  env = process.env, request = fetch) {
  const email = /^[^\s<>@\r\n]+@[^\s<>@\r\n]+\.[^\s<>@\r\n]+$/;
  if (purpose !== 'business-recovery-sandbox' ||
      typeof code !== 'string' ||
      !/^hvcr1_[A-Za-z0-9_-]{43}$/.test(code) ||
      typeof requestId !== 'string' ||
      !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(requestId) ||
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
          subject: 'TEST ONLY — Codex Backup company recovery approval' }],
        content: [{ type: 'text/plain', value: [
          'Sandbox test only. No company backup service is active.',
          `Request: ${requestId}`,
          code,
          'This code expires in 10 minutes. It permits a two-hour, read-only copy of one encrypted company Vault on a replacement device. It does not decrypt a backup; the company-held recovery kit is required.',
          'If you did not request this, report it to your company administrator.',
        ].join('\n\n') }],
        tracking_settings: { click_tracking: { enable: false, enable_text: false },
          open_tracking: { enable: false } },
      }),
    });
    if (response.status === 202) return 'accepted';
    return response.status >= 400 && response.status < 500 ? 'rejected' : 'uncertain';
  } catch { return 'uncertain'; }
}

module.exports = { businessRecoveryMail };
