const test = require('node:test');
const assert = require('node:assert/strict');
const { bootstrap, main, guardStatement } = require('../ops/hosted-sandbox-bootstrap');
const env = { HOSTED_SANDBOX_BOOTSTRAP: 'empty-schema-only', HOSTED_MODE: 'sandbox',
  COMMERCE_MODE: 'sandbox', COMMERCE_CHECKOUT_OPEN: 'no', VERCEL_ENV: 'preview',
  VERCEL_URL: 'codex-migrate-fixture-joshuas-projects-d3a5c48d.vercel.app',
  COMMERCE_DATABASE_URL: 'postgresql://fixture:fixture@ep-square-queen-av5us6bx.c-11.us-east-1.aws.neon.tech/neondb' };
const migrations = () => [{ folderMillis: 123, hash: 'a'.repeat(64),
  sql: ['CREATE SCHEMA hosted', 'CREATE TABLE hosted.fixture (id integer)'] }];
function fixture({ mode = 'sandbox', hosted = false, ledger = true,
  transactionError = false } = {}) {
  const calls = []; let transactions = 0;
  const open = () => ({ query: async (sql, params) => {
    calls.push({ sql, params });
    assert.match(sql, /^SELECT /);
    return { rows: sql.includes('commerce_environment') ? [{ mode }] :
      [{ hosted_present: hosted, ledger_present: ledger }] };
  }, transaction: async (build, options) => {
    transactions++;
    assert.equal(options.isolationLevel, 'Serializable');
    assert(options.fetchOptions.signal instanceof AbortSignal);
    const statements = build({ query: (sql, params) => ({ sql, params }) });
    calls.push(...statements);
    if (transactionError) throw Error('PRIVATE postgres://secret');
  } });
  return { open, calls, get transactions() { return transactions; } };
}
test('ordinary builds skip before reading files or opening a database', async () => {
  const refuse = () => { throw Error('must not call'); };
  assert.deepEqual(await bootstrap({}, refuse, refuse), { skipped: true });
});
for (const change of [{ VERCEL_ENV: 'production' }, { HOSTED_MODE: 'live' },
  { COMMERCE_MODE: 'live' }, { COMMERCE_CHECKOUT_OPEN: 'yes' },
  { VERCEL_URL: 'other.vercel.app' },
  { COMMERCE_DATABASE_URL: env.COMMERCE_DATABASE_URL.replace('square-queen-av5us6bx', 'holy-surf-av4n95ee') }]) {
  test(`unsafe ${Object.keys(change)[0]} never opens database`, async () => {
    let opens = 0;
    await assert.rejects(bootstrap({ ...env, ...change }, () => { opens++; }, migrations));
    assert.equal(opens, 0);
  });
}
test('existing schema, absent ledger or wrong database identity never submits a transaction', async () => {
  for (const options of [{ mode: 'live' }, { hosted: true }, { ledger: false }]) {
    const f = fixture(options);
    await assert.rejects(bootstrap(env, f.open, migrations));
    assert.equal(f.transactions, 0);
  }
});
test('inspection mode proves the empty schema without submitting a transaction', async () => {
  const f = fixture();
  assert.deepEqual(await bootstrap({ ...env, HOSTED_SANDBOX_BOOTSTRAP: 'inspect' }, f.open, migrations),
    { sandbox: true, emptyHostedSchemaVerified: true, ledgerPresent: true,
      note: 'Read-only inspection; no migration submitted.' });
  assert.equal(f.transactions, 0);
  assert.equal(f.calls.length, 2);
});
test('DDL and exact receipts share one guarded transaction', async () => {
  const f = fixture();
  const result = await bootstrap(env, f.open, migrations);
  assert.equal(f.transactions, 1);
  assert.equal(result.migrationsCommitted, 1);
  assert.match(f.calls[2].sql, /pg_advisory_xact_lock/);
  const guard = f.calls[3].sql;
  assert.match(guard, /mode = 'sandbox'/);
  assert.match(guard, /to_regnamespace\('hosted'\) IS NOT NULL/);
  assert.match(guard, /created_at BETWEEN 123 AND 123/);
  assert.match(guard, /RAISE EXCEPTION/);
  assert.equal(f.calls[4].sql, 'CREATE SCHEMA hosted');
  assert.match(f.calls.at(-1).sql, /^INSERT INTO drizzle\.__drizzle_migrations/);
  assert.deepEqual(f.calls.at(-1).params, ['a'.repeat(64), 123]);
});
test('malformed migration metadata is rejected before SQL interpolation', () => {
  for (const rows of [[{ folderMillis: NaN, hash: 'a'.repeat(64) }],
    [{ folderMillis: 123, hash: "private'" }], [migrations()[0], migrations()[0]]]) {
    assert.throws(() => guardStatement(rows));
  }
});
test('uncertain transaction is not retried and diagnostics contain no provider text', async () => {
  const f = fixture({ transactionError: true }); const output = [];
  assert.equal(await main(env, f.open, x => output.push(JSON.parse(x)), migrations), 1);
  assert.equal(f.transactions, 1);
  assert.equal(output[0].stage, 'atomic-bootstrap');
  assert.match(output[0].next, /read-only preflight/);
  assert(!JSON.stringify(output).includes('PRIVATE'));
});
