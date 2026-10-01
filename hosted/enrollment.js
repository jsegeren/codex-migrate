// Dark, server-only buyer enrollment. A download token locates a purchase but
// never grants storage access: the buyer must also prove control of the email
// on a freshly verified, unrefunded Stripe purchase. Only a sandbox-only,
// explicitly gated HTTP route uses this module; an enrolled account starts
// with zero upload allowance.
const { createHash, randomBytes, randomUUID } = require('node:crypto');
const { tokenHash } = require('./access');

const CHALLENGE = /^hve1_[A-Za-z0-9_-]{43}$/;
const SESSION = /^cs_(?:test|live)_[A-Za-z0-9]+$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const DIGEST = /^[0-9a-f]{64}$/;
const ISSUE_SQL = `SELECT hosted.issue_enrollment_challenge(
  $1::text, $2::text, $3::text
) AS issued`;
const DELIVERY_SQL = `SELECT hosted.record_enrollment_challenge_delivery(
  $1::text, $2::text
) AS recorded`;
const CLAIM_SQL = `SELECT hosted.claim_and_pair_first_device(
  $1::text, $2::text, $3::text, $4::uuid, $5::uuid, $6::uuid, $7::text
) AS account_id`;
const RESOLVE_SQL = `SELECT sessions.account_id, sessions.vault_id,
    sessions.device_id, purchases.purchase_session_id, purchases.purchase_mode
  FROM hosted.device_sessions AS sessions
  JOIN hosted.purchase_enrollments AS purchases
    ON purchases.account_id = sessions.account_id
  WHERE sessions.token_hash = $1 AND sessions.device_id = $2
    AND sessions.revoked_at IS NULL
    AND sessions.expires_at > clock_timestamp()`;
const RECOVERY_ISSUE_SQL = `SELECT hosted.issue_recovery_challenge(
  $1::text, $2::text, $3::text
) AS issued`;
const RECOVERY_DELIVERY_SQL = `SELECT hosted.record_recovery_challenge_delivery(
  $1::text, $2::text
) AS recorded`;
const RECOVERY_LIST_SQL = `SELECT vault_id, published_at
  FROM hosted.list_recovery_vaults($1::text, $2::text, $3::text)`;
const RECOVERY_CLAIM_SQL = `SELECT hosted.claim_recovery_vault_device(
  $1::text, $2::text, $3::text, $4::uuid, $5::uuid, $6::text
) AS account_id`;
const ROTATE_SQL = `SELECT account_id, vault_id FROM hosted.rotate_device_session(
  $1::text, $2::uuid, $3::text, $4::uuid
)`;

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
  return beginChallenge({ purchaseToken, verifyPurchase, query, sendChallenge,
    issueSql: ISSUE_SQL, deliverySql: DELIVERY_SQL, purpose: 'setup' });
}

async function beginRecovery({ purchaseToken, verifyPurchase, query,
  sendChallenge }) {
  return beginChallenge({ purchaseToken, verifyPurchase, query, sendChallenge,
    issueSql: RECOVERY_ISSUE_SQL, deliverySql: RECOVERY_DELIVERY_SQL,
    purpose: 'recovery' });
}

async function beginChallenge({ purchaseToken, verifyPurchase, query,
  sendChallenge, issueSql, deliverySql, purpose }) {
  if (typeof verifyPurchase !== 'function' || typeof query !== 'function' ||
      typeof sendChallenge !== 'function') throw new HostedEnrollmentError();
  try {
    // verifyPurchase must be the commerce service's live Stripe recheck,
    // which also records the purchase before the database challenge call.
    const purchase = await verifyPurchase(purchaseToken);
    if (!purchaseEvidence(purchase)) throw new HostedEnrollmentError();
    const challenge = mintChallenge();
    const issued = await query(issueSql,
      [purchase.sessionId, purchase.mode, challenge.hash]);
    if (issued?.rows?.[0]?.issued !== true) throw new HostedEnrollmentError();

    let delivery;
    try {
      delivery = await sendChallenge({ to: purchase.email, code: challenge.token,
        live: purchase.mode === 'live', purpose });
    } catch { delivery = 'uncertain'; }
    const state = delivery === 'accepted' ? 'sent' :
      delivery === 'rejected' ? 'rejected' : 'uncertain';
    const recorded = await query(deliverySql, [challenge.hash, state]);
    if (recorded?.rows?.[0]?.recorded !== true || state !== 'sent') {
      throw new HostedEnrollmentError();
    }
    return Object.freeze({ status: 'sent' });
  } catch {
    // Do not expose purchase, email, Stripe, mail, or database details.
    throw new HostedEnrollmentError();
  }
}

async function listRecoveryVaults({ purchaseToken, code, verifyPurchase, query }) {
  if (typeof verifyPurchase !== 'function' || typeof query !== 'function') {
    throw new HostedEnrollmentError();
  }
  try {
    const hash = challengeHash(code);
    const purchase = await verifyPurchase(purchaseToken);
    if (!purchaseEvidence(purchase)) throw new HostedEnrollmentError();
    const result = await query(RECOVERY_LIST_SQL,
      [hash, purchase.sessionId, purchase.mode]);
    if (!Array.isArray(result?.rows) || !result.rows.length ||
        result.rows.length > 64) throw new HostedEnrollmentError();
    const seen = new Set();
    const vaults = result.rows.map(row => {
      if (!UUID.test(row?.vault_id) || seen.has(row.vault_id)) {
        throw new HostedEnrollmentError();
      }
      seen.add(row.vault_id);
      const date = row.published_at == null ? null : new Date(row.published_at);
      if (date && !Number.isFinite(date.getTime())) {
        throw new HostedEnrollmentError();
      }
      return Object.freeze({ vaultId: row.vault_id,
        lastGoodAt: date ? date.toISOString() : null });
    });
    return Object.freeze({ vaults });
  } catch { throw new HostedEnrollmentError(); }
}

async function claimRecoveryVault({ purchaseToken, code, vaultId, deviceId,
  deviceTokenHash, verifyPurchase, query }) {
  if (typeof verifyPurchase !== 'function' || typeof query !== 'function') {
    throw new HostedEnrollmentError();
  }
  try {
    if (!UUID.test(vaultId) || !UUID.test(deviceId) ||
        !DIGEST.test(deviceTokenHash)) throw new HostedEnrollmentError();
    const hash = challengeHash(code);
    const purchase = await verifyPurchase(purchaseToken);
    if (!purchaseEvidence(purchase)) throw new HostedEnrollmentError();
    const result = await query(RECOVERY_CLAIM_SQL, [hash, purchase.sessionId,
      purchase.mode, vaultId, deviceId, deviceTokenHash]);
    const accountId = result?.rows?.[0]?.account_id;
    if (result?.rows?.length !== 1 || !UUID.test(accountId)) {
      throw new HostedEnrollmentError();
    }
    // The caller generated the Keychain-held bearer before this request.
    // A lost response is reconciled by resolveFirstDevice with that bearer.
    return Object.freeze({ accountId, vaultId, deviceId });
  } catch { throw new HostedEnrollmentError(); }
}

async function claimEnrollment({ purchaseToken, code, deviceId,
  deviceTokenHash, verifyPurchase, query }) {
  if (typeof verifyPurchase !== 'function' || typeof query !== 'function') {
    throw new HostedEnrollmentError();
  }
  try {
    if (!UUID.test(deviceId) || !DIGEST.test(deviceTokenHash)) {
      throw new HostedEnrollmentError();
    }
    const hash = challengeHash(code);
    const purchase = await verifyPurchase(purchaseToken);
    if (!purchaseEvidence(purchase)) throw new HostedEnrollmentError();
    const proposedAccount = randomUUID();
    const vaultId = randomUUID();
    const claimed = await query(CLAIM_SQL, [hash, purchase.sessionId,
      purchase.mode, proposedAccount, vaultId, deviceId, deviceTokenHash]);
    if (claimed?.rows?.[0]?.account_id !== proposedAccount) {
      throw new HostedEnrollmentError();
    }
    // The native helper generated and saved the bearer secret before this
    // call. Losing this response is recoverable by resolving that same device.
    // This is not a trial or an upload capability: allowance remains zero.
    return Object.freeze({ accountId: proposedAccount, vaultId, deviceId });
  } catch { throw new HostedEnrollmentError(); }
}

async function resolveFirstDevice({ deviceToken, deviceId, query,
  verifyPurchase }) {
  if (typeof query !== 'function' || typeof verifyPurchase !== 'function' ||
      !UUID.test(deviceId)) throw new HostedEnrollmentError();
  try {
    const digest = tokenHash(deviceToken);
    const result = await query(RESOLVE_SQL, [digest, deviceId]);
    const row = result?.rows?.[0];
    if (result?.rows?.length !== 1 || row.device_id !== deviceId ||
        !UUID.test(row.account_id) || !UUID.test(row.vault_id)) {
      throw new HostedEnrollmentError();
    }
    const purchase = await verifyPurchase(row.purchase_session_id,
      row.purchase_mode);
    if (purchase?.sessionId !== row.purchase_session_id ||
        purchase?.mode !== row.purchase_mode) throw new HostedEnrollmentError();
    return Object.freeze({ accountId: row.account_id, vaultId: row.vault_id,
      deviceId });
  } catch { throw new HostedEnrollmentError(); }
}

async function rotateDeviceSession({ oldDeviceToken, oldDeviceId, newDeviceId,
  newDeviceTokenHash, query, verifyPurchase }) {
  if (typeof query !== 'function' || typeof verifyPurchase !== 'function' ||
      !UUID.test(oldDeviceId) || !UUID.test(newDeviceId) ||
      oldDeviceId === newDeviceId || !DIGEST.test(newDeviceTokenHash)) {
    throw new HostedEnrollmentError();
  }
  try {
    // The existing session and its current purchase are checked first. The
    // database then atomically consumes that exact active bearer; a concurrent
    // replay, expired bearer, or conflicting replacement receives no row.
    const old = await resolveFirstDevice({ deviceToken: oldDeviceToken,
      deviceId: oldDeviceId, query, verifyPurchase });
    const result = await query(ROTATE_SQL, [tokenHash(oldDeviceToken),
      oldDeviceId, newDeviceTokenHash, newDeviceId]);
    const row = result?.rows?.[0];
    if (result?.rows?.length !== 1 || row.account_id !== old.accountId ||
        row.vault_id !== old.vaultId) throw new HostedEnrollmentError();
    return Object.freeze({ accountId: old.accountId, vaultId: old.vaultId,
      deviceId: newDeviceId });
  } catch { throw new HostedEnrollmentError(); }
}

module.exports = { HostedEnrollmentError, beginEnrollment, claimEnrollment,
  resolveFirstDevice, rotateDeviceSession, beginRecovery, listRecoveryVaults,
  claimRecoveryVault };
