const { test, beforeEach } = require('node:test');
const assert = require('node:assert/strict');
const handler = require('../api/signup');
const originalFetch = global.fetch;
const { after } = require('node:test');
after(() => { global.fetch = originalFetch; });
let sent;
beforeEach(() => {
  process.env.SENDGRID_API_KEY = 'test-only';
  process.env.LAUNCH_FROM_EMAIL = 'sender@example.com';
  process.env.LAUNCH_NOTIFY_EMAIL = 'maintainer@example.com';
  sent = [];
  global.fetch = async (url, options) => {
    sent.push({ url, options });
    return { status: 202 };
  };
});
async function submit(overrides = {}) {
  const req = { method: 'POST', headers: { origin: 'https://migrate.segeren.com', 'content-type': 'application/x-www-form-urlencoded' }, body: { email: 'reader@example.net', consent: 'yes', website: '' }, ...overrides };
  const res = { headers: {}, setHeader(name, value) { this.headers[name] = value; }, end(body) { this.body = body; } };
  await handler(req, res);
  return res;
}
test('valid request sends consent to fixed maintainer, not visitor', async () => {
  const res = await submit();
  assert.equal(res.statusCode, 200);
  assert.equal(sent.length, 1);
  const payload = JSON.parse(sent[0].options.body);
  assert.deepEqual(payload.personalizations, [{ to: [{ email: 'maintainer@example.com' }] }]);
  assert.deepEqual(payload.reply_to, { email: 'reader@example.net' });
  assert.match(payload.content[0].value, /not verified/);
  assert.match(payload.content[0].value, /Consent:/);
  assert.equal(payload.tracking_settings.open_tracking.enable, false);
  assert.equal(res.headers['Cache-Control'], 'no-store');
  assert.equal(res.headers['X-Robots-Tag'], 'noindex');
  assert.doesNotMatch(res.body, /reader@example/);
  assert.match(res.body, /data-analytics-event="generate_lead"/);
  assert.match(res.body, /src="\/analytics\.js\?v=20260904"/);
});
test('supports urlencoded body and alias origin', async () => {
  assert.equal((await submit({ body: 'email=reader%40example.net&consent=yes&website=', headers: { origin: 'https://codex-migrate.vercel.app', 'content-type': 'application/x-www-form-urlencoded; charset=UTF-8' } })).statusCode, 200);
});
test('rejects GET without sending', async () => {
  assert.equal((await submit({ method: 'GET' })).statusCode, 405);
  assert.equal(sent.length, 0);
});
test('rejects foreign and absent origins', async () => {
  for (const origin of ['https://attacker.example', 'https://migrate.segeren.com.attacker.example', undefined]) {
    assert.equal((await submit({ headers: { origin, 'content-type': 'application/x-www-form-urlencoded' } })).statusCode, 403);
  }
  assert.equal(sent.length, 0);
});
test('requires explicit consent and a valid single email', async () => {
  for (const body of [{ email: 'reader@example.net' }, { email: 'a@b\r\nBcc: victim@example.com', consent: 'yes' }, { email: '<script>@example.com', consent: 'yes' }, { email: ['a@example.com'], consent: 'yes' }, { email: 'a'.repeat(65)+'@example.com', consent: 'yes' }]) {
    assert.equal((await submit({ body })).statusCode, 400);
  }
  assert.equal(sent.length, 0);
});
test('rejects honeypot and arbitrary fields rather than relaying them', async () => {
  for (const body of [{ email: 'a@example.com', consent: 'yes', website: 'spam' }, { email: 'a@example.com', consent: 'yes', message: 'unwanted content' }]) {
    assert.equal((await submit({ body })).statusCode, 400);
  }
  assert.equal(sent.length, 0);
});
test('rejects duplicate form fields and oversized or unsupported bodies', async () => {
  assert.equal((await submit({ body: 'email=a%40example.com&email=b%40example.com&consent=yes' })).statusCode, 400);
  assert.equal((await submit({ body: 'x'.repeat(2049) })).statusCode, 413);
  assert.equal((await submit({ headers: { origin: 'https://migrate.segeren.com', 'content-type': 'application/json' } })).statusCode, 415);
  assert.equal(sent.length, 0);
});
test('missing config fails closed without claiming success', async () => {
  delete process.env.SENDGRID_API_KEY;
  const res = await submit();
  assert.equal(res.statusCode, 503);
  assert.match(res.body, /has not been saved/);
  assert.equal(sent.length, 0);
});
test('provider failure never returns signup success or exposes provider detail', async () => {
  global.fetch = async () => ({ status: 403 });
  const res = await submit();
  assert.equal(res.statusCode, 503);
  assert.doesNotMatch(res.body, /Launch request sent/);
  assert.doesNotMatch(res.body, /data-analytics-event=/);
});
test('timeout does not retry or falsely confirm delivery', async () => {
  let calls = 0;
  global.fetch = async () => { calls++; throw Error('secret provider diagnostic'); };
  const res = await submit();
  assert.equal(res.statusCode, 503);
  assert.equal(calls, 1);
  assert.doesNotMatch(res.body, /secret provider diagnostic/);
});
