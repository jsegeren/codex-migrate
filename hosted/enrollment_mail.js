// The message is transactional proof of the paid buyer's email, not marketing.
// Sandbox can send only to the configured operator sink.
async function enrollmentMail({ to, code, live }, env = process.env,
  request = fetch) {
  const from = env.LAUNCH_FROM_EMAIL;
  if (typeof live !== 'boolean' || typeof code !== 'string' ||
      !/^hve1_[A-Za-z0-9_-]{43}$/.test(code) ||
      typeof to !== 'string' || to.length > 254 ||
      !/^[^\s<>@\r\n]+@[^\s<>@\r\n]+\.[^\s<>@\r\n]+$/.test(to) ||
      !/^[^\s<>@\r\n]+@[^\s<>@\r\n]+\.[^\s<>@\r\n]+$/.test(from || '') ||
      !env.SENDGRID_API_KEY || (!live && to !== env.COMMERCE_SANDBOX_EMAIL)) {
    return 'rejected';
  }
  try {
    const response = await request('https://api.sendgrid.com/v3/mail/send', {
      method: 'POST', redirect: 'error', signal: AbortSignal.timeout(8000),
      headers: { Authorization: `Bearer ${env.SENDGRID_API_KEY}`,
        'Content-Type': 'application/json' },
      body: JSON.stringify({
        from: { email: from, name: 'Codex Migrate' },
        reply_to: { email: 'joshua@segeren.com', name: 'Joshua Segeren' },
        personalizations: [{ to: [{ email: to }],
          subject: live ? 'Confirm your Codex Vault backup setup' :
            'TEST ONLY — Codex Vault backup setup' }],
        content: [{ type: 'text/plain', value: [
          live ? 'Use this one-time code to confirm hosted Codex Vault setup:' :
            'Sandbox test only. No hosted backup is active.',
          code,
          'The code expires in 10 minutes. Enter it only in the Codex Migrate setup you opened. We will not ask you to send it by email.',
          'This confirms your email only. Hosting does not begin until you separately choose a plan and see its terms.',
          'If you did not request this, ignore the message. For help, reply to joshua@segeren.com.',
        ].join('\n\n') }],
        tracking_settings: { click_tracking: { enable: false, enable_text: false },
          open_tracking: { enable: false } },
      }),
    });
    if (response.status === 202) return 'accepted';
    return response.status >= 400 && response.status < 500 ? 'rejected' : 'uncertain';
  } catch { return 'uncertain'; }
}

module.exports = { enrollmentMail };
