const test = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const { join } = require('node:path');

test('browser download check fails closed without explicit sandbox opt-in', () => {
  const env = { ...process.env };
  for (const name of Object.keys(env)) {
    if (name.startsWith('COMMERCE_') || name === 'BLOB_READ_WRITE_TOKEN' || name === 'NODE_PATH') {
      delete env[name];
    }
  }
  const script = join(__dirname, '..', 'ops', 'commerce-browser-download-check.js');
  const result = spawnSync(process.execPath, [script], { env, encoding: 'utf8' });
  assert.notEqual(result.status, 0);
  assert.equal(result.stdout, '');
  assert.equal(result.stderr.trim(),
    '{"ok":false,"code":"browser_download_check_failed","stage":"preflight"}');
  assert.equal(result.stderr.includes('http'), false);
});
