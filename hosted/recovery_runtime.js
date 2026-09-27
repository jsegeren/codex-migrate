// Sandbox-only runtime for the dark recovery API. Never open the live database
// or ship a signing secret to a native client. Activation is a separate gate.
const { neon } = require('@neondatabase/serverless');
const { decodeSecret } = require('./object_capability');

const SANDBOX_HOST = 'ep-square-queen-av5us6bx.c-11.us-east-1.aws.neon.tech';
const SANDBOX_POOLER_HOST = 'ep-square-queen-av5us6bx-pooler.c-11.us-east-1.aws.neon.tech';

class HostedRecoveryRuntimeError extends Error {
  constructor() { super('hosted_recovery_unavailable'); }
}

function recoveryConfiguration(env) {
  if (env.HOSTED_MODE !== 'sandbox' ||
      env.HOSTED_SANDBOX_RECOVERY_OPEN !== 'yes') {
    throw new HostedRecoveryRuntimeError();
  }
  return storageConfiguration(env);
}

function storageConfiguration(env) {
  if (env.HOSTED_MODE !== 'sandbox') throw new HostedRecoveryRuntimeError();
  let worker;
  let secret;
  try {
    worker = new URL(env.HOSTED_R2_ORIGIN);
    secret = decodeSecret(env.HOSTED_CAPABILITY_SIGNING_KEY);
  } catch { throw new HostedRecoveryRuntimeError(); }
  if (worker.protocol !== 'https:' || !worker.hostname ||
      worker.username || worker.password || worker.pathname !== '/' ||
      worker.search || worker.hash) throw new HostedRecoveryRuntimeError();
  return Object.freeze({ databaseUrl: sandboxDatabaseUrl(env),
    workerOrigin: worker.origin, secret });
}

function sandboxDatabaseUrl(env) {
  if (env.HOSTED_MODE !== 'sandbox') throw new HostedRecoveryRuntimeError();
  let database;
  try {
    database = new URL(env.COMMERCE_DATABASE_URL);
  } catch { throw new HostedRecoveryRuntimeError(); }
  if (!['postgres:', 'postgresql:'].includes(database.protocol) ||
      ![SANDBOX_HOST, SANDBOX_POOLER_HOST].includes(database.hostname) ||
      database.pathname !== '/neondb' ||
      database.username === '' || database.password === '') {
    throw new HostedRecoveryRuntimeError();
  }
  return database.toString();
}

async function sandboxDatabaseRuntime(env = process.env) {
  const databaseUrl = sandboxDatabaseUrl(env);
  try {
    const sql = neon(databaseUrl);
    const query = (text, params) => sql.query(text, params, {
      fullResults: true,
      fetchOptions: { signal: AbortSignal.timeout(15_000) },
    });
    const identity = await query(`SELECT mode FROM commerce_environment
      WHERE name = 'codex-migrate-commerce'`, []);
    if (identity?.rows?.length !== 1 || identity.rows[0].mode !== 'sandbox') {
      throw new HostedRecoveryRuntimeError();
    }
    return query;
  } catch { throw new HostedRecoveryRuntimeError(); }
}

async function recoveryRuntime(env = process.env) {
  const config = recoveryConfiguration(env);
  const query = await sandboxDatabaseRuntime(env);
  return Object.freeze({ query, workerOrigin: config.workerOrigin,
    secret: config.secret });
}

module.exports = { HostedRecoveryRuntimeError, recoveryConfiguration,
  recoveryRuntime, storageConfiguration, sandboxDatabaseUrl,
  sandboxDatabaseRuntime };
