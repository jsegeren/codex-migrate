// Explicit operator action only. Do not migrate hosted state on an HTTP path.
const { neon } = require('@neondatabase/serverless');
const { drizzle } = require('drizzle-orm/neon-http');
const { migrate } = require('drizzle-orm/neon-http/migrator');
const path = require('node:path');

function migrationTarget(env) {
  const hosts = { sandbox: 'ep-square-queen-av5us6bx.c-11.us-east-1.aws.neon.tech',
    live: 'ep-holy-surf-av4n95ee.c-11.us-east-1.aws.neon.tech' };
  const mode = env.HOSTED_MODE;
  if (!Object.hasOwn(hosts, mode) ||
      env.HOSTED_MIGRATION_CONFIRM !== `codex-migrate-hosted-${mode}`) {
    throw new Error('Explicit hosted database confirmation required');
  }
  let url;
  try { url = new URL(env.COMMERCE_DATABASE_URL_UNPOOLED || ''); }
  catch { throw new Error('Explicit hosted database confirmation required'); }
  if (!['postgres:', 'postgresql:'].includes(url.protocol) ||
      url.hostname !== hosts[mode] || url.hostname.includes('-pooler') ||
      url.pathname !== '/neondb') {
    throw new Error('Explicit hosted database confirmation required');
  }
  return url;
}

async function main(env = process.env) {
  const url = migrationTarget(env);
  const db = drizzle(neon(url.toString()));
  await migrate(db, { migrationsFolder: path.join(__dirname, '../hosted/migrations') });
  console.log('Hosted schema migration complete');
}

module.exports = { migrationTarget, main };
if (require.main === module) main().catch(() => {
  console.error('Hosted migration failed; no credentials printed.');
  process.exitCode = 1;
});
