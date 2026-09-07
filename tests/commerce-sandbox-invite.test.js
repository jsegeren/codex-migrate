const test = require('node:test');
const assert = require('node:assert/strict');
const { invite } = require('../ops/commerce-sandbox-invite');
const env = { VERCEL_ENV: 'preview', VERCEL_URL: 'codex-migrate-fixture-joshuas-projects-d3a5c48d.vercel.app',
  COMMERCE_MODE: 'sandbox', COMMERCE_CHECKOUT_PROVIDER: 'stripe', COMMERCE_CHECKOUT_OPEN: 'yes',
  COMMERCE_STRIPE_ACCOUNT: 'acct_1Rkc6nQwGK6ZgBcK', COMMERCE_RELEASE: 'sandbox-delivery-2026-09-05',
  COMMERCE_SANDBOX_EMAIL: 'joshua@segeren.com', LAUNCH_FROM_EMAIL: 'joshua@segeren.com',
  COMMERCE_STRIPE_KEY: 'rk_test_fixture', SENDGRID_API_KEY: 'fixture-mail-secret',
  COMMERCE_SANDBOX_OPERATOR_TOKEN: 'a'.repeat(64), COMMERCE_SANDBOX_INVITE: 'yes',
  COMMERCE_SANDBOX_INVITE_ID: 'c0e53f8b-0fe1-461a-b46a-6b096b97e9a3' };
const checkoutUrl = 'https://checkout.stripe.com/c/pay/cs_test_fixture#private';
test('sandbox invite does nothing by default', async () => {
  assert.deepEqual(await invite({}, () => assert.fail('provider called')), { skipped: true });
});
for (const [key, value] of Object.entries({ VERCEL_ENV: 'production', COMMERCE_MODE: 'live',
  COMMERCE_STRIPE_ACCOUNT: 'acct_other', COMMERCE_CHECKOUT_PROVIDER: 'managed',
  COMMERCE_RELEASE: 'another-release', COMMERCE_CHECKOUT_OPEN: 'no',
  COMMERCE_SANDBOX_EMAIL: 'customer@example.com', LAUNCH_FROM_EMAIL: 'other@example.com',
  COMMERCE_STRIPE_KEY: 'rk_live_fixture', COMMERCE_SANDBOX_INVITE_ID: 'invalid',
  COMMERCE_SANDBOX_OPERATOR_TOKEN: '', SENDGRID_API_KEY: '' })) {
  test(`sandbox invite rejects ${key} before provider access`, async () => {
    await assert.rejects(invite({ ...env, [key]: value }, () => assert.fail('provider called')),
      error => error.message === 'sandbox_invite_failed' && error.stage === 'configuration');
  });
}
test('sandbox invite uses existing handler, sends only to owner and returns no credentials', async () => {
  let sends = 0;
  const result = await invite(env, async () => ({
    handler: async (req, res) => {
      assert.equal(req.headers.authorization, `Bearer ${env.COMMERCE_SANDBOX_OPERATOR_TOKEN}`);
      assert.deepEqual(req.body, { requestId: env.COMMERCE_SANDBOX_INVITE_ID });
      res.statusCode = 200; res.end(JSON.stringify({ url: checkoutUrl }));
    }, request: async (url, options) => {
      sends++; assert.equal(url, 'https://api.sendgrid.com/v3/mail/send');
      const body = JSON.parse(options.body);
      assert.deepEqual(body.personalizations, [{ to: [{ email: 'joshua@segeren.com' }] }]);
      assert.equal(body.tracking_settings.click_tracking.enable, false);
      assert.ok(body.content[0].value.includes(checkoutUrl));
      assert.ok(!options.body.includes(env.COMMERCE_SANDBOX_OPERATOR_TOKEN));
      return { status: 202 };
    },
  }));
  assert.equal(sends, 1); assert.equal(result.paymentAttempted, false);
  assert.equal(result.hostedCheckoutRequestTested, false);
  assert.ok(!JSON.stringify(result).includes('private'));
});
for (const url of ['https://checkout.stripe.com/c/pay/cs_live_fixture', 'https://evil.invalid/c/pay/cs_test_fixture']) {
  test(`rejects non-test checkout before email: ${url}`, async () => {
    await assert.rejects(invite(env, async () => ({ handler: async (req, res) => {
      res.statusCode = 200; res.end(JSON.stringify({ url }));
    }, request: () => assert.fail('mail sent') })), { message: 'sandbox_invite_failed' });
  });
}
test('uncertain mail is not retried and private provider errors are withheld', async () => {
  let sends = 0;
  await assert.rejects(invite(env, async () => ({ handler: async (req, res) => {
    res.statusCode = 200; res.end(JSON.stringify({ url: checkoutUrl }));
  }, request: async () => { sends++; throw Error('private provider payload'); } })),
  error => error.message === 'sandbox_invite_failed' && error.stage === 'test-invite-mail');
  assert.equal(sends, 1);
});
