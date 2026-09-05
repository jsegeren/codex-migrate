// Private operator maintenance. Reports counts only, never buyer addresses or
// link credentials. Stripe's webhook retry remains the normal delivery path.
const { database } = require('../commerce/database');
const { sql } = require('drizzle-orm');
const { runtime } = require('../commerce/runtime');
async function main() {
  const args = process.argv.slice(2);
  if (args.length > 1 || (args[0] && args[0] !== '--retry-pending')) throw Error('Invalid arguments');
  const db = database(process.env.COMMERCE_DATABASE_URL);
  const identity = await db.execute(sql`select mode from commerce_environment where name = 'codex-migrate-commerce'`);
  const mode = process.env.COMMERCE_MODE;
  if (!['sandbox', 'live'].includes(mode) || identity.rows.length !== 1 || identity.rows[0].mode !== mode) throw Error('Wrong environment');
  const counts = await db.execute(sql`select mail_state, count(*)::int as count from commerce_purchases where mode = ${mode} group by mail_state`);
  console.log(JSON.stringify({ mode, deliveryStates: counts.rows }));
  if (args[0] !== '--retry-pending') return;
  const { service } = await runtime();
  const pending = await db.execute(sql`select session_id from commerce_purchases where mode = ${mode} and mail_state = 'pending' and mail_attempts < 5 order by created_at limit 10`);
  let completed = 0, needsReview = 0;
  for (const row of pending.rows) {
    try { await service.fulfill(row.session_id); completed++; } catch { needsReview++; }
  }
  console.log(JSON.stringify({ completed, needsReview }));
}
if (require.main === module) main().catch(() => { console.error('Delivery check failed; inspect private provider dashboards.'); process.exitCode = 1; });
