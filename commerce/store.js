const { randomUUID } = require('node:crypto');
const { sql } = require('drizzle-orm');
const { CommerceError } = require('./config');

function purchaseStore(db) {
  return {
    async ensure(p) {
      await db.execute(sql`insert into commerce_purchases (session_id, mode, release_id, payment_intent, email)
        values (${p.sessionId}, ${p.mode}, ${p.releaseId}, ${p.paymentIntent}, ${p.email})
        on conflict (session_id, mode) do nothing`);
      const { rows } = await db.execute(sql`select release_id, payment_intent, email from commerce_purchases
        where session_id = ${p.sessionId} and mode = ${p.mode}`);
      if (rows.length !== 1 || rows[0].release_id !== p.releaseId ||
          rows[0].payment_intent !== p.paymentIntent || rows[0].email !== p.email) {
        throw new CommerceError('purchase_record_conflict');
      }
    },
    async claim(id, mode) {
      const lease = randomUUID();
      const { rows } = await db.execute(sql`update commerce_purchases
        set mail_state = 'sending', mail_lease = ${lease}, mail_started_at = now(), mail_attempts = mail_attempts + 1
        where session_id = ${id} and mode = ${mode} and mail_state = 'pending' and mail_attempts < 5
        returning session_id`);
      if (rows.length) return lease;
      const existing = await db.execute(sql`select mail_state from commerce_purchases
        where session_id = ${id} and mode = ${mode}`);
      if (existing.rows[0]?.mail_state !== 'sent') throw new CommerceError('delivery_needs_review');
      return null;
    },
    async mailResult(id, mode, lease, result) {
      const state = result === 'accepted' ? 'sent' : result === 'rejected' ? 'pending' : 'uncertain';
      const { rows } = await db.execute(sql`update commerce_purchases set mail_state = ${state}, mail_lease = null
        where session_id = ${id} and mode = ${mode} and mail_lease = ${lease} and mail_state = 'sending'
        returning session_id`);
      if (rows.length !== 1) throw new CommerceError('delivery_needs_review');
    },
  };
}
module.exports = { purchaseStore };
