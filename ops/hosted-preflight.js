// Opt-in, read-only Preview build check. Secrets stay in Vercel; no public
// diagnostic route, schema mutation, subscription, upload or email is created.
const path = require('node:path');
const { readMigrationFiles } = require('drizzle-orm/migrator');
const { sandboxDatabaseUrl, sandboxDatabaseRuntime } = require('../hosted/recovery_runtime');

const TABLES = Object.freeze(['accounts', 'vaults', 'upload_reservations',
  'snapshots', 'snapshot_objects', 'subscription_enrollments']);

function requireCheck(value) {
  if (!value) throw new Error('hosted_preflight_failed');
}

function validateEnvironment(env) {
  requireCheck(env.VERCEL_ENV === 'preview' && env.HOSTED_MODE === 'sandbox' &&
    env.COMMERCE_MODE === 'sandbox' && env.COMMERCE_CHECKOUT_OPEN === 'no');
  requireCheck(/^codex-migrate-[a-z0-9]+-joshuas-projects-d3a5c48d\.vercel\.app$/.test(
    env.VERCEL_URL || ''));
  sandboxDatabaseUrl(env); // Exact sandbox host, credentials and database.
}

function expectedMigrations() {
  return readMigrationFiles({ migrationsFolder: path.join(__dirname, '../hosted/migrations') });
}

async function preflight(env = process.env, openDatabase = sandboxDatabaseRuntime,
  migrations = expectedMigrations) {
  if (env.HOSTED_PREFLIGHT !== 'yes') return { skipped: true };
  let stage = 'configuration';
  try {
    validateEnvironment(env);
    const expected = migrations();
    requireCheck(expected.length > 0);
    stage = 'sandbox-identity';
    const query = await openDatabase(env);
    stage = 'migration-ledger';
    const ledger = await query(`SELECT hash, created_at
      FROM drizzle.__drizzle_migrations ORDER BY created_at LIMIT 512`, []);
    requireCheck(Array.isArray(ledger?.rows) && ledger.rows.length < 512);
    for (const migration of expected) {
      const matches = ledger.rows.filter(row => Number(row.created_at) === migration.folderMillis);
      requireCheck(matches.length === 1 && matches[0].hash === migration.hash);
    }
    stage = 'schema-presence';
    const tables = await query(`SELECT name, to_regclass('hosted.' || name) IS NOT NULL AS present
      FROM unnest($1::text[]) AS name`, [TABLES]);
    requireCheck(tables?.rows?.length === TABLES.length && TABLES.every(name =>
      tables.rows.filter(row => row.name === name && row.present === true).length === 1));
    return { sandboxIdentityVerified: true, migrationReceiptsVerified: expected.length,
      requiredTablesPresent: true,
      note: 'Read-only provisioning evidence, not schema-drift, hosted backup or recovery acceptance.' };
  } catch {
    const error = new Error('hosted_preflight_failed'); error.stage = stage; throw error;
  }
}

async function main(env = process.env, openDatabase = sandboxDatabaseRuntime,
  report = console.log, migrations = expectedMigrations) {
  try { report(JSON.stringify(await preflight(env, openDatabase, migrations))); return 0; }
  catch (error) {
    // Database errors may contain credentials or private identifiers.
    report(JSON.stringify({ configured: false, code: 'hosted_preflight_failed', stage: error.stage }));
    return 1;
  }
}

module.exports = { main, preflight, validateEnvironment, expectedMigrations, TABLES };
if (require.main === module) main().then(code => { process.exitCode = code; });
