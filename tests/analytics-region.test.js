const { test } = require('node:test');
const assert = require('node:assert/strict');
const handler = require('../api/analytics-region');

function request(country, method = 'GET') {
  const req = { method, headers: {} };
  if (country !== undefined) req.headers['x-vercel-ip-country'] = country;
  const res = {
    headers: {},
    setHeader(name, value) { this.headers[name] = value; },
    end(body = '') { this.body = body; },
  };
  handler(req, res);
  return res;
}

test('defaults to full analytics outside consent-required markets', () => {
  for (const country of ['US', 'CA', 'AU', 'JP']) {
    const res = request(country);
    assert.equal(res.statusCode, 200);
    assert.deepEqual(JSON.parse(res.body), { mode: 'default' });
    assert.equal(res.headers['Cache-Control'], 'private, no-store');
    assert.equal(res.headers.Vary, 'X-Vercel-IP-Country');
  }
});

test('requires consent in the EEA, United Kingdom, and Switzerland', () => {
  for (const country of ['AT', 'DE', 'FR', 'IS', 'LI', 'NO', 'GB', 'CH']) {
    assert.deepEqual(JSON.parse(request(country).body), { mode: 'consent' });
  }
});

test('fails closed when Vercel does not provide a country', () => {
  assert.deepEqual(JSON.parse(request(undefined).body), { mode: 'consent' });
  assert.deepEqual(JSON.parse(request('  ').body), { mode: 'consent' });
});

test('HEAD has no body and unsupported methods are rejected', () => {
  const head = request('US', 'HEAD');
  assert.equal(head.statusCode, 200);
  assert.equal(head.body, '');
  const post = request('US', 'POST');
  assert.equal(post.statusCode, 405);
  assert.equal(post.headers.Allow, 'GET, HEAD');
});
