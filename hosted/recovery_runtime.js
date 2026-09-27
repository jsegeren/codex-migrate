// Sandbox-only runtime for the dark recovery API. Never open the live database
// or ship a signing secret to a native client. Activation is a separate gate.
const { neon } = require('@neondatabase/serverless');
const { decodeSecret } = require('./object_capability');

const SANDBOX_HOST = 'ep-square-queen-av5us6bx.c-11.us-east-1.aws.neon.tech';

class HostedRecoveryRuntimeError extends Error {
  constructor() { super('hosted_recovery_unavailable'); }
}

function recoveryConfiguration(env) {
  if (env.HOSTED_MODE !== 'sandbox' ||
      env.HOSTED_SANDBOX_RECOVERY_OPEN !== 'yes') {
    throw new HostedRecoveryRuntimeError();
  }
  let database;
  let worker;
  let secret;
  try {
    database = new URL(env.COMMERCE_DATABASE_URL);
    worker = new URL(env.HOSTED_R2_ORIGIN);
    secret = decodeSecret(env.HOSTED_CAPABILITY_SIGNING_KEY);
  } catch { throw new HostedRecoveryRuntimeError(); }
  if (!['postgres:', 'postgresql:'].includes(database.protocol) ||
      database.hostname !== SANDBOX_HOST || database.pathname !== '/neondb' ||
      database.username === '' || database.password === '' ||
      worker.protocol !== 'https:' || !worker.hostname ||
      worker.username || worker.password || worker.pathname !== '/' ||
      worker.search || worker.hash) throw new HostedRecoveryRuntimeError();
  return Object.freeze({ databaseUrl: database.toString(),
    workerOrigin: worker.origin, secret });
}

async function recoveryRuntime(env = process.env) {
  const config = recoveryConfiguration(env);
  try {
    const sql = neon(config.databaseUrl);
    const query = (text, params) => sql.query(text, params, {
      fullResults: true,
      fetchOptions: { signal: AbortSignal.timeout(15_000) },
    });
    const identity = await query(`SELECT mode FROM commerce_environment
      WHERE name = 'codex-migrate-commerce'`, []);
    if (identity?.rows?.length !== 1 || identity.rows[0].mode !== 'sandbox') {
      throw new HostedRecoveryRuntimeError();
    }
    return Object.freeze({ query, workerOrigin: config.workerOrigin,
      secret: config.secret });
  } catch { throw new HostedRecoveryRuntimeError(); }
}

module.exports = { HostedRecoveryRuntimeError, recoveryConfiguration,
  recoveryRuntime };
