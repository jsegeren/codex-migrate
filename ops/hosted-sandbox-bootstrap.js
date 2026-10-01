// One-off operator bootstrap, never a public route or ordinary deployment task.
// Refuse existing hosted state; all schema changes and receipts commit together.
const { neon } = require('@neondatabase/serverless');
const { sandboxDatabaseUrl } = require('../hosted/recovery_runtime');
const { validateEnvironment, expectedMigrations } = require('./hosted-preflight');

function requireCheck(value) { if (!value) throw Error('hosted_bootstrap_refused'); }

function guardStatement(migrations) {
  const times = migrations.map(row => row.folderMillis);
  requireCheck(times.every(Number.isSafeInteger) && new Set(times).size === times.length);
  requireCheck(migrations.every(row => /^[a-f0-9]{64}$/.test(row.hash)));
  return `DO $$ BEGIN
    IF (SELECT count(*) FROM commerce_environment
        WHERE name = 'codex-migrate-commerce') <> 1 OR
       NOT EXISTS (SELECT 1 FROM commerce_environment
        WHERE name = 'codex-migrate-commerce' AND mode = 'sandbox') OR
       to_regnamespace('hosted') IS NOT NULL OR
       EXISTS (SELECT 1 FROM drizzle.__drizzle_migrations
        WHERE created_at BETWEEN ${Math.min(...times)} AND ${Math.max(...times)}) THEN
      RAISE EXCEPTION 'hosted_bootstrap_refused';
    END IF;
  END $$`;
}

async function bootstrap(env = process.env, open = neon, migrations = expectedMigrations) {
  if (!['inspect', 'empty-schema-only'].includes(env.HOSTED_SANDBOX_BOOTSTRAP)) return { skipped: true };
  let stage = 'configuration';
  try {
    validateEnvironment(env);
    const expected = migrations();
    requireCheck(expected.length > 0 && expected.length <= 128);
    const guard = guardStatement(expected);
    const sql = open(sandboxDatabaseUrl(env));
    stage = 'sandbox-identity';
    const identity = await sql.query(`SELECT mode FROM commerce_environment
      WHERE name = 'codex-migrate-commerce'`, [], {
      fullResults: true, fetchOptions: { signal: AbortSignal.timeout(15000) } });
    requireCheck(identity?.rows?.length === 1 && identity.rows[0].mode === 'sandbox');
    stage = 'empty-schema';
    const presence = await sql.query(`SELECT to_regnamespace('hosted') IS NOT NULL AS hosted_present,
      to_regclass('drizzle.__drizzle_migrations') IS NOT NULL AS ledger_present`, [], {
      fullResults: true, fetchOptions: { signal: AbortSignal.timeout(15000) } });
    requireCheck(presence?.rows?.length === 1 && presence.rows[0].hosted_present === false &&
      presence.rows[0].ledger_present === true);
    if (env.HOSTED_SANDBOX_BOOTSTRAP === 'inspect') {
      return { sandbox: true, emptyHostedSchemaVerified: true, ledgerPresent: true,
        note: 'Read-only inspection; no migration submitted.' };
    }
    stage = 'atomic-bootstrap';
    await sql.transaction(tx => {
      const statements = [tx.query('SELECT pg_advisory_xact_lock(63547638)', []),
        tx.query(guard, [])];
      for (const migration of expected) {
        for (const statement of migration.sql) {
          if (statement.trim()) statements.push(tx.query(statement, []));
        }
        statements.push(tx.query(`INSERT INTO drizzle.__drizzle_migrations (hash, created_at)
          VALUES ($1, $2)`, [migration.hash, migration.folderMillis]));
      }
      return statements;
    }, { isolationLevel: 'Serializable', fullResults: true,
      fetchOptions: { signal: AbortSignal.timeout(60000) } });
    return { sandbox: true, migrationsCommitted: expected.length,
      note: 'Schema bootstrap only; hosted publication and recovery remain unproven.' };
  } catch {
    const error = Error('hosted_bootstrap_failed'); error.stage = stage; throw error;
  }
}

async function main(env = process.env, open = neon, report = console.log,
  migrations = expectedMigrations) {
  try { report(JSON.stringify(await bootstrap(env, open, migrations))); return 0; }
  catch (error) {
    report(JSON.stringify({ code: 'hosted_bootstrap_failed', stage: error.stage,
      ...(error.stage === 'atomic-bootstrap' ? {
        next: 'Run read-only preflight before any retry; transaction delivery may be uncertain.' } : {}) }));
    return 1;
  }
}

module.exports = { main, bootstrap, guardStatement };
if (require.main === module) main().then(code => { process.exitCode = code; });
