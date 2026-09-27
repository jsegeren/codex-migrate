const test = require('node:test');
const assert = require('node:assert/strict');
const { migrationTarget } = require('../ops/hosted-migrate');

const hosts = { sandbox: 'ep-square-queen-av5us6bx.c-11.us-east-1.aws.neon.tech',
  live: 'ep-holy-surf-av4n95ee.c-11.us-east-1.aws.neon.tech' };
const target = mode => ({ HOSTED_MODE: mode,
  HOSTED_MIGRATION_CONFIRM: `codex-migrate-hosted-${mode}`,
  COMMERCE_DATABASE_URL_UNPOOLED:
    `postgresql://fixture:fixture@${hosts[mode]}/neondb?sslmode=require` });

test('hosted migration accepts only the exact direct connection and confirmation', () => {
  for (const mode of ['sandbox', 'live']) {
    assert.equal(migrationTarget(target(mode)).hostname, hosts[mode]);
  }
});

test('hosted migration rejects wrong environment, pooler, path and absent consent', () => {
  const valid = target('sandbox');
  for (const invalid of [
    {},
    { ...valid, HOSTED_MIGRATION_CONFIRM: undefined },
    { ...valid, HOSTED_MODE: 'live' },
    { ...valid, COMMERCE_DATABASE_URL_UNPOOLED: valid.COMMERCE_DATABASE_URL_UNPOOLED.replace(
      'queen-av5us6bx.', 'queen-av5us6bx-pooler.') },
    { ...valid, COMMERCE_DATABASE_URL_UNPOOLED: valid.COMMERCE_DATABASE_URL_UNPOOLED.replace(
      '/neondb', '/other') },
  ]) {
    assert.throws(() => migrationTarget(invalid), /confirmation required/);
  }
});
