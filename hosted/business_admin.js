// Dark assisted-pilot administrator proof. The business account and exact
// contact are operator-approved records; a matching email domain, employee
// purchase, or this short-lived session cannot grant content recovery.
const { createHash, randomBytes } = require('node:crypto');

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const EMAIL = /^[^\s<>@\r\n]+@[^\s<>@\r\n]+\.[^\s<>@\r\n]+$/;
const CHALLENGE = /^hvae1_[A-Za-z0-9_-]{43}$/;
const SESSION = /^hva1_[A-Za-z0-9_-]{43}$/;
const ISSUE_SQL = `SELECT hosted.issue_business_admin_challenge(
  $1::uuid, $2::text) AS contact`;
const DELIVERY_SQL = `SELECT hosted.record_business_admin_challenge_delivery(
  $1::text, $2::text) AS recorded`;
const CLAIM_SQL = `SELECT hosted.claim_business_admin_session(
  $1::uuid, $2::text, $3::text) AS account_id`;
const RESOLVE_SQL = `SELECT account_id FROM hosted.business_admin_sessions
  WHERE token_hash = $1 AND revoked_at IS NULL
    AND expires_at > clock_timestamp()`;

class BusinessAdminError extends Error {
  constructor() { super('business_admin_unavailable'); }
}

function digest(domain, token, pattern) {
  if (typeof token !== 'string' || !pattern.test(token)) {
    throw new BusinessAdminError();
  }
  return createHash('sha256').update(domain).update('\0').update(token)
    .digest('hex');
}

function challengeHash(token) {
  return digest('codex-backup-business-admin-challenge-v1', token, CHALLENGE);
}

function sessionHash(token) {
  return digest('codex-backup-business-admin-session-v1', token, SESSION);
}

function mint(prefix) { return `${prefix}${randomBytes(32).toString('base64url')}`; }

async function beginBusinessAdminAccess({ accountId, query, sendChallenge }) {
  if (!UUID.test(accountId) || typeof query !== 'function' ||
      typeof sendChallenge !== 'function') throw new BusinessAdminError();
  try {
    const challenge = mint('hvae1_');
    const hash = challengeHash(challenge);
    const issued = await query(ISSUE_SQL, [accountId, hash]);
    const contact = issued?.rows?.[0]?.contact;
    if (issued?.rows?.length !== 1 || typeof contact !== 'string' ||
        contact.length > 254 || !EMAIL.test(contact)) {
      throw new BusinessAdminError();
    }
    let delivery;
    try {
      delivery = await sendChallenge({ to: contact, code: challenge,
        purpose: 'business-admin-sandbox' });
    } catch { delivery = 'uncertain'; }
    const state = delivery === 'accepted' ? 'sent' :
      delivery === 'rejected' ? 'rejected' : 'uncertain';
    const recorded = await query(DELIVERY_SQL, [hash, state]);
    if (recorded?.rows?.[0]?.recorded !== true || state !== 'sent') {
      throw new BusinessAdminError();
    }
    // Neither the contact address nor the code returns to the caller.
    return Object.freeze({ status: 'sent' });
  } catch { throw new BusinessAdminError(); }
}

async function claimBusinessAdminAccess({ accountId, code, query }) {
  if (!UUID.test(accountId) || typeof query !== 'function') {
    throw new BusinessAdminError();
  }
  try {
    const challenge = challengeHash(code);
    const token = mint('hva1_');
    const result = await query(CLAIM_SQL,
      [accountId, challenge, sessionHash(token)]);
    if (result?.rows?.length !== 1 ||
        result.rows[0]?.account_id !== accountId) {
      throw new BusinessAdminError();
    }
    return Object.freeze({ accountId, sessionToken: token });
  } catch { throw new BusinessAdminError(); }
}

async function resolveBusinessAdmin({ sessionToken, query }) {
  if (typeof query !== 'function') throw new BusinessAdminError();
  try {
    const result = await query(RESOLVE_SQL, [sessionHash(sessionToken)]);
    const accountId = result?.rows?.[0]?.account_id;
    if (result?.rows?.length !== 1 || !UUID.test(accountId)) {
      throw new BusinessAdminError();
    }
    return Object.freeze({ accountId });
  } catch { throw new BusinessAdminError(); }
}

module.exports = { BusinessAdminError, beginBusinessAdminAccess,
  claimBusinessAdminAccess, resolveBusinessAdmin, challengeHash, sessionHash };
