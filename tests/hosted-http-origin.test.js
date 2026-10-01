const test = require('node:test');
const assert = require('node:assert/strict');
const { allowedBrowserOrigin } = require('../hosted/http_origin');

test('hosted API keeps native requests and both owned browser origins', () => {
  assert.equal(allowedBrowserOrigin(undefined), true);
  assert.equal(allowedBrowserOrigin('https://codexbackup.segeren.com'), true);
  assert.equal(allowedBrowserOrigin('https://migrate.segeren.com'), true);
});

test('hosted API rejects other and downgraded browser origins', () => {
  for (const origin of [null, '', 'null', 'http://codexbackup.segeren.com',
    'https://codexbackup.segeren.com.evil.example',
    'https://codexbackup.segeren.com/', 'https://other.example']) {
    assert.equal(allowedBrowserOrigin(origin), false);
  }
});
