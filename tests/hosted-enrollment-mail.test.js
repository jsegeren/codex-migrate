const test = require('node:test');
const assert = require('node:assert/strict');
const { enrollmentMail } = require('../hosted/enrollment_mail');

const code = `hve1_${'a'.repeat(43)}`;
const env = { LAUNCH_FROM_EMAIL: 'mail@example.test',
  SENDGRID_API_KEY: 'fixture-only', COMMERCE_SANDBOX_EMAIL: 'operator@example.test' };

test('transactional proof mail is one recipient with no tracking or storage claim', async () => {
  let sent;
  const result = await enrollmentMail({ to: 'buyer@example.test', code, live: true },
    env, async (url, options) => {
      assert.equal(url, 'https://api.sendgrid.com/v3/mail/send');
      sent = JSON.parse(options.body);
      return { status: 202 };
    });
  assert.equal(result, 'accepted');
  assert.deepEqual(sent.personalizations[0].to, [{ email: 'buyer@example.test' }]);
  assert.equal(sent.personalizations.length, 1);
  assert.match(sent.content[0].value, /expires in 10 minutes/);
  assert.match(sent.content[0].value, /Hosting does not begin/);
  assert.equal(sent.tracking_settings.click_tracking.enable, false);
  assert.equal(sent.tracking_settings.open_tracking.enable, false);
});

test('recovery mail distinguishes device pairing from decrypting a backup', async () => {
  let sent;
  const result = await enrollmentMail({ to: 'buyer@example.test', code,
    live: true, purpose: 'recovery' }, env, async (_url, options) => {
    sent = JSON.parse(options.body);
    return { status: 202 };
  });
  assert.equal(result, 'accepted');
  assert.equal(sent.personalizations[0].subject,
    'Recover access to your Codex Vault backup');
  assert.match(sent.content[0].value, /new Mac/);
  assert.match(sent.content[0].value, /recovery key/);
  assert.doesNotMatch(sent.content[0].value, /Hosting does not begin/);
});

test('sandbox is sink-only and invalid input fails before any mail request', async () => {
  let calls = 0;
  const request = async () => { calls++; return { status: 202 }; };
  for (const input of [
    { to: 'buyer@example.test', code, live: false },
    { to: 'operator@example.test', code: 'short', live: false },
    { to: 'operator@example.test', code, live: undefined },
    { to: 'operator@example.test', code, live: false, purpose: 'anything' },
  ]) {
    assert.equal(await enrollmentMail(input, env, request), 'rejected');
  }
  assert.equal(calls, 0);
  assert.equal(await enrollmentMail({ to: env.COMMERCE_SANDBOX_EMAIL,
    code, live: false }, env, request), 'accepted');
  assert.equal(calls, 1);
});

test('uncertain delivery is never reported as sent', async () => {
  assert.equal(await enrollmentMail({ to: 'buyer@example.test', code, live: true },
    env, async () => { throw Error('private mail detail'); }), 'uncertain');
  assert.equal(await enrollmentMail({ to: 'buyer@example.test', code, live: true },
    env, async () => ({ status: 500 })), 'uncertain');
});
