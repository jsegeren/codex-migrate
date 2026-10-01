const test = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const { main, preflight, expectedMigrations, TABLES } = require('../ops/hosted-preflight');
const env = { HOSTED_PREFLIGHT: 'yes', HOSTED_MODE: 'sandbox', COMMERCE_MODE: 'sandbox',
  VERCEL_ENV: 'preview', COMMERCE_CHECKOUT_OPEN: 'no',
  VERCEL_URL: 'codex-migrate-fixture-joshuas-projects-d3a5c48d.vercel.app',
  COMMERCE_DATABASE_URL: 'postgresql://fixture:fixture@ep-square-queen-av5us6bx.c-11.us-east-1.aws.neon.tech/neondb' };
const migrations = () => [{ folderMillis: 123, hash: 'a'.repeat(64) }];
function database({ presence = [{ present: true }], ledger = [{ created_at: '123', hash: 'a'.repeat(64) }],
  tables = TABLES.map(name => ({ name, present: true })) } = {}) {
  return async () => async (sql, params) => {
    assert.match(sql.trim(), /^SELECT /);
    if (sql.includes("to_regclass('drizzle.")) {
      assert.deepEqual(params, []); return { rows: presence };
    }
    if (sql.includes('__drizzle_migrations')) {
      assert.deepEqual(params, []); return { rows: ledger };
    }
    assert.deepEqual(params, [TABLES]); return { rows: tables };
  };
}
test('ordinary builds do not contact providers or read migration files', async () => {
  const refuse = () => { throw Error('must not call'); };
  assert.deepEqual(await preflight({}, refuse, refuse), { skipped: true });
});
test('build hook and upload allowlist include the opt-in operator check', () => {
  const root = path.join(__dirname, '..');
  assert.match(require('../vercel.json').buildCommand, /node ops\/hosted-preflight\.js/);
  assert.match(readFileSync(path.join(root, '.vercelignore'), 'utf8'),
    /^!ops\/hosted-preflight\.js$/m);
});
test('sandbox identity, exact receipts and required tables produce bounded evidence', async () => {
  const result = await preflight(env, database(), migrations);
  assert.equal(result.sandboxIdentityVerified, true);
  assert.equal(result.migrationReceiptsVerified, 1);
  assert.equal(result.requiredTablesPresent, true);
  assert.match(result.note, /not schema-drift, hosted backup or recovery acceptance/);
  const committed = expectedMigrations();
  assert.equal(committed.length, 42);
  assert(committed.every(row => /^[a-f0-9]{64}$/.test(row.hash)));
});
for (const change of [{ VERCEL_ENV: 'production' }, { HOSTED_MODE: 'live' },
  { COMMERCE_MODE: 'live' }, { COMMERCE_CHECKOUT_OPEN: 'yes' },
  { COMMERCE_CHECKOUT_OPEN: undefined }, { VERCEL_URL: 'other.vercel.app' },
  { COMMERCE_DATABASE_URL: env.COMMERCE_DATABASE_URL.replace('square-queen-av5us6bx', 'holy-surf-av4n95ee') }]) {
  test(`rejects unsafe configuration ${Object.keys(change)[0]}`, async () => {
    let calls = 0;
    await assert.rejects(preflight({ ...env, ...change }, () => { calls++; }, migrations));
    assert.equal(calls, 0);
  });
}
for (const ledger of [[], [{ created_at: 123, hash: 'b'.repeat(64) }],
  [{ created_at: 124, hash: 'a'.repeat(64) }],
  Array(2).fill({ created_at: 123, hash: 'a'.repeat(64) }),
  Array(512).fill({ created_at: 123, hash: 'a'.repeat(64) })]) {
  test('missing, changed, duplicate or unbounded ledger fails closed', async () => {
    await assert.rejects(preflight(env, database({ ledger }), migrations));
  });
}
test('missing or duplicated required table fails closed', async () => {
  for (const tables of [[], TABLES.map(name => ({ name, present: false })),
    TABLES.map(() => ({ name: TABLES[0], present: true }))]) {
    await assert.rejects(preflight(env, database({ tables }), migrations));
  }
});
test('provider details never enter diagnostic output', async () => {
  const output = [];
  const code = await main(env, async () => { throw Error('postgres://SECRET private-customer'); },
    value => output.push(JSON.parse(value)), migrations);
  assert.equal(code, 1);
  assert.deepEqual(output, [{ configured: false, code: 'hosted_preflight_failed', stage: 'sandbox-identity' }]);
});
test('absent ledger stops before reading migration rows', async () => {
  const output = [];
  assert.equal(await main(env, database({ presence: [{ present: false }] }),
    value => output.push(JSON.parse(value)), migrations), 1);
  assert.deepEqual(output, [{ configured: false, code: 'hosted_preflight_failed',
    stage: 'migration-ledger-presence' }]);
});
test('incomplete receipts report counts only, not ledger hashes or private identifiers', async () => {
  const output = [];
  assert.equal(await main(env, database({ ledger: [{ created_at: 123, hash: 'PRIVATE' }] }),
    value => output.push(JSON.parse(value)), migrations), 1);
  assert.deepEqual(output, [{ configured: false, code: 'hosted_preflight_failed',
    stage: 'migration-receipts', expectedMigrationReceipts: 1, matchedMigrationReceipts: 0 }]);
});
