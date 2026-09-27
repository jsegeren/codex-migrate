// Dark, server-only buyer enrollment. A download token locates a purchase but
// never grants storage access: the buyer must also prove control of the email
// on a freshly verified, unrefunded Stripe purchase. No HTTP route uses this
// module yet, and an enrolled account starts with zero upload allowance.
const { createHash, randomBytes, randomUUID } = require('node:crypto');

const CHALLENGE = /^hve1_[A-Za-z0-9_-]{43}$/;
const SESSION = /^cs_(?:test|live)_[A-Za-z0-9]+$/;
const ISSUE_SQL = `SELECT hosted.issue_enrollment_challenge(
  $1::text, $2::text, $3::text
) AS issued`;
const DELIVERY_SQL = `SELECT hosted.record_enrollment_challenge_delivery(
  $1::text, $2::text
) AS recorded`;
const CLAIM_SQL = `SELECT hosted.claim_purchase_enrollment(
  $1::text, $2::text, $3::text, $4::uuid
) AS account_id`;

class HostedEnrollmentError extends Error {
  constructor() { super('hosted_enrollment_unavailable'); }
}

function challengeHash(token) {
  if (typeof token !== 'string' || !CHALLENGE.test(token)) {
    throw new HostedEnrollmentError();
  }
  return createHash('sha256').update('codex-vault-hosted-enrollment-v1\0')
    .update(token).digest('hex');
}

function mintChallenge() {
  const token = `hve1_${randomBytes(32).toString('base64url')}`;
  return Object.freeze({ token, hash: challengeHash(token) });
}

function purchaseEvidence(value) {
  return value && typeof value.sessionId === 'string' &&
    SESSION.test(value.sessionId) &&
    value.mode === (value.sessionId.startsWith('cs_live_') ? 'live' : 'sandbox') &&
    typeof value.email === 'string' && value.email.length <= 254 &&
    /^[^\s<>@\r\n]+@[^\s<>@\r\n]+\.[^\s<>@\r\n]+$/.test(value.email);
}

async function beginEnrollment({ purchaseToken, verifyPurchase, query,
  sendChallenge }) {
  if (typeof verifyPurchase !== 'function' || typeof query !== 'function' ||
      typeof sendChallenge !== 'function') throw new HostedEnrollmentError();
  try {
    // verifyPurchase must be the commerce service's live Stripe recheck,
    // which also records the purchase before the database challenge call.
    const purchase = await verifyPurchase(purchaseToken);
    if (!purchaseEvidence(purchase)) throw new HostedEnrollmentError();
    const challenge = mintChallenge();
    const issued = await query(ISSUE_SQL,
      [purchase.sessionId, purchase.mode, challenge.hash]);
    if (issued?.rows?.[0]?.issued !== true) throw new HostedEnrollmentError();

    let delivery;
    try {
      delivery = await sendChallenge({ to: purchase.email, code: challenge.token,
        live: purchase.mode === 'live' });
    } catch { delivery = 'uncertain'; }
    const state = delivery === 'accepted' ? 'sent' :
      delivery === 'rejected' ? 'rejected' : 'uncertain';
    const recorded = await query(DELIVERY_SQL, [challenge.hash, state]);
    if (recorded?.rows?.[0]?.recorded !== true || state !== 'sent') {
      throw new HostedEnrollmentError();
    }
    return Object.freeze({ status: 'sent' });
  } catch {
    // Do not expose purchase, email, Stripe, mail, or database details.
    throw new HostedEnrollmentError();
  }
}

async function claimEnrollment({ purchaseToken, code, verifyPurchase, query }) {
  if (typeof verifyPurchase !== 'function' || typeof query !== 'function') {
    throw new HostedEnrollmentError();
  }
  try {
    const hash = challengeHash(code);
    const purchase = await verifyPurchase(purchaseToken);
    if (!purchaseEvidence(purchase)) throw new HostedEnrollmentError();
    const proposedAccount = randomUUID();
    const claimed = await query(CLAIM_SQL, [hash, purchase.sessionId,
      purchase.mode, proposedAccount]);
    if (claimed?.rows?.[0]?.account_id !== proposedAccount) {
      throw new HostedEnrollmentError();
    }
    // This is only a server-side account identifier. It is not an authenticated
    // browser session, device token, trial, or upload capability.
    return Object.freeze({ accountId: proposedAccount });
  } catch { throw new HostedEnrollmentError(); }
}

module.exports = { HostedEnrollmentError, beginEnrollment, claimEnrollment };
