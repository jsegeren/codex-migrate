const test = require('node:test');
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { database } = require('../commerce/database');
const { sql } = require('drizzle-orm');
const { purchaseStore } = require('../commerce/store');

test('real sandbox database grants and claims atomically across concurrent connections', {
  skip: !process.env.COMMERCE_TEST_DATABASE_URL, timeout: 60000,
}, async () => {
  const url = new URL(process.env.COMMERCE_TEST_DATABASE_URL);
  // This acceptance runner is deliberately pinned to the disposable branch,
  // never a caller-supplied production database or You.one store.
  assert.equal(url.hostname, 'ep-square-queen-av5us6bx-pooler.c-11.us-east-1.aws.neon.tech');
  const db = database(url.toString());
  const identity = await db.execute(sql`select mode from commerce_environment where name = 'codex-migrate-commerce'`);
  assert.equal(identity.rows[0]?.mode, 'sandbox');
  const id = randomUUID().replaceAll('-', '');
  const p = { sessionId: `cs_test_store${id}`, mode: 'sandbox', releaseId: 'fixture-1',
    paymentIntent: `pi_store${id}`, email: 'fixture@example.invalid' };
  const store = purchaseStore(db);
  await Promise.all(Array.from({ length: 8 }, () => store.ensure(p)));
  const results = await Promise.allSettled(Array.from({ length: 8 }, () => store.claim(p.sessionId, p.mode)));
  const claims = results.filter(r => r.status === 'fulfilled' && r.value).map(r => r.value);
  assert.equal(claims.length, 1);
  await store.mailResult(p.sessionId, p.mode, claims[0], 'accepted');
  assert.equal(await store.claim(p.sessionId, p.mode), null);
  await assert.rejects(store.ensure({ ...p, releaseId: 'changed' }), /conflict/);
  const row = await db.execute(sql`select count(*)::int as count from commerce_purchases where session_id = ${p.sessionId} and mode = 'sandbox'`);
  assert.equal(row.rows[0].count, 1);

  const q = { ...p, sessionId: `cs_test_uncertain${id}`, paymentIntent: `pi_uncertain${id}` };
  await store.ensure(q); const lease = await store.claim(q.sessionId, q.mode);
  await store.mailResult(q.sessionId, q.mode, lease, 'uncertain');
  await assert.rejects(store.claim(q.sessionId, q.mode), /review/);
  // Retain two clearly synthetic records as acceptance evidence; no customer
  // data is inserted, selected or removed by this runner.
});
