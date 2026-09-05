// Explicit operator action only. Never run schema migrations on HTTP requests.
const { neon } = require('@neondatabase/serverless');
const { drizzle } = require('drizzle-orm/neon-http');
const { migrate } = require('drizzle-orm/neon-http/migrator');
const { sql } = require('drizzle-orm');
const path = require('node:path');
async function main() {
  const url = new URL(process.env.COMMERCE_DATABASE_URL_UNPOOLED || '');
  const hosts = { sandbox: 'ep-square-queen-av5us6bx.c-11.us-east-1.aws.neon.tech',
    live: 'ep-holy-surf-av4n95ee.c-11.us-east-1.aws.neon.tech' };
  if (!['postgres:', 'postgresql:'].includes(url.protocol) ||
      !url.hostname.endsWith('.neon.tech') || url.hostname.includes('-pooler') ||
      url.pathname !== '/neondb' || process.env.COMMERCE_MIGRATION_CONFIRM !== 'codex-migrate-commerce' ||
      url.hostname !== hosts[process.env.COMMERCE_MODE]) {
    throw new Error('Explicit isolated commerce database confirmation required');
  }
  const db = drizzle(neon(url.toString()));
  await migrate(db, { migrationsFolder: path.join(__dirname, '../commerce/migrations') });
  await db.execute(sql`insert into commerce_environment (name, mode) values ('codex-migrate-commerce', ${process.env.COMMERCE_MODE}) on conflict do nothing`);
  const result = await db.execute(sql`select mode from commerce_environment where name = 'codex-migrate-commerce'`);
  if (result.rows[0]?.mode !== process.env.COMMERCE_MODE) throw new Error('Commerce environment mismatch');
  console.log('Commerce schema migration complete');
}
module.exports = { main };
if (require.main === module) main().catch(() => { console.error('Commerce migration failed; no credentials printed.'); process.exitCode = 1; });
