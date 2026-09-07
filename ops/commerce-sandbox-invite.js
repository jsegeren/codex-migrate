// Explicit operator-only acceptance step; no public route and no real payment.
// Invoke once with a recorded UUID. If mail acceptance is uncertain, inspect
// the provider rather than rebuilding/retrying to obtain another message.
const { commerceSite, validRelease } = require('../commerce/config');
const releases = require('../commerce/releases.json');
const ACCOUNT = 'acct_1Rkc6nQwGK6ZgBcK';
const EMAIL = 'joshua@segeren.com';

async function dependencies(env) {
  const { makeHandler } = require('../api/checkout');
  return { handler: makeHandler(undefined, env), request: fetch };
}

async function invite(env = process.env, load = dependencies) {
  if (env.COMMERCE_SANDBOX_INVITE !== 'yes') return { skipped: true };
  let stage = 'configuration';
  try {
    const release = releases[env.COMMERCE_RELEASE];
    if (env.VERCEL_ENV !== 'preview' || env.COMMERCE_MODE !== 'sandbox' ||
        env.COMMERCE_STRIPE_ACCOUNT !== ACCOUNT || env.COMMERCE_CHECKOUT_PROVIDER !== 'stripe' ||
        !validRelease(release, false) ||
        env.COMMERCE_CHECKOUT_OPEN !== 'yes' || env.COMMERCE_SANDBOX_EMAIL !== EMAIL ||
        env.LAUNCH_FROM_EMAIL !== EMAIL || !env.SENDGRID_API_KEY ||
        !/^(rk|sk)_test_[A-Za-z0-9]+$/.test(env.COMMERCE_STRIPE_KEY || '') ||
        !/^[a-f0-9]{64}$/.test(env.COMMERCE_SANDBOX_OPERATOR_TOKEN || '') ||
        !/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/.test(env.COMMERCE_SANDBOX_INVITE_ID || '')) {
      throw Error('invalid_configuration');
    }
    const site = commerceSite(env);
    const deps = await load(env);
    stage = 'checkout-handler';
    let result;
    const res = { statusCode: 0, setHeader() {}, end(value) { result = JSON.parse(value); } };
    await deps.handler({ method: 'POST', headers: { origin: site,
      'content-type': 'application/json', authorization: `Bearer ${env.COMMERCE_SANDBOX_OPERATOR_TOKEN}` },
      body: { requestId: env.COMMERCE_SANDBOX_INVITE_ID } }, res);
    if (res.statusCode !== 200) throw Error('checkout_failed');
    const url = new URL(result.url);
    const match = url.pathname.match(/^\/c\/pay\/(cs_test_[A-Za-z0-9]+)$/);
    if (url.origin !== 'https://checkout.stripe.com' || url.username || url.password || !match) {
      throw Error('invalid_checkout_url');
    }
    stage = 'test-invite-mail';
    const response = await deps.request('https://api.sendgrid.com/v3/mail/send', {
      method: 'POST', redirect: 'error', signal: AbortSignal.timeout(8000),
      headers: { Authorization: `Bearer ${env.SENDGRID_API_KEY}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ from: { email: EMAIL, name: 'Codex Migrate test' },
        personalizations: [{ to: [{ email: EMAIL }] }],
        subject: 'TEST ONLY — ordinary Stripe Checkout acceptance',
        content: [{ type: 'text/plain', value: [
          'Operator acceptance test only. This is Stripe test mode, not a real purchase.',
          release.testingOnly === true
            ? 'Use synthetic test payment details only. This delivers the actual signed app candidate for operator acceptance, not a publicly released product.'
            : 'Use synthetic test payment details only. The download is the harmless delivery fixture, not the app.',
          `Artifact: ${release.filename}`,
          `Open test checkout: ${url.toString()}`,
          `Test reference: ${env.COMMERCE_SANDBOX_INVITE_ID}`,
          'This link was created by the current checkout handler. Hosted webhook, buyer-page and email delivery still need verification.',
        ].join('\n\n') }],
        tracking_settings: { click_tracking: { enable: false, enable_text: false }, open_tracking: { enable: false } },
      }),
    });
    if (response.status !== 202) throw Error('invite_not_accepted');
    return { sandbox: true, session: match[1], mailAccepted: true,
      paymentAttempted: false, hostedCheckoutRequestTested: false };
  } catch {
    const error = new Error('sandbox_invite_failed'); error.stage = stage; throw error;
  }
}
module.exports = { invite };
if (require.main === module) invite().then(value => console.log(JSON.stringify(value))).catch(error => {
  console.error(JSON.stringify({ code: 'sandbox_invite_failed', stage: error.stage }));
  process.exitCode = 1;
});
