// Dark, read-only replacement-device approval. The company keeps the CVB1
// recovery kit; this service never receives a decryption credential.
const { createHash, randomBytes, randomUUID } = require('node:crypto');
const { sessionHash } = require('./business_admin');

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const DIGEST = /^[0-9a-f]{64}$/;
const CODE = /^hvcr1_[A-Za-z0-9_-]{43}$/;
const PURPOSE = /^.{12,250}$/s;
const EMAIL = /^[^\s<>@\r\n]+@[^\s<>@\r\n]+\.[^\s<>@\r\n]+$/;
const ISSUE_SQL = `SELECT hosted.issue_business_recovery_request(
  $1::text, $2::uuid, $3::uuid, $4::uuid, $5::uuid, $6::text,
  $7::text) AS contact`;
const DELIVERY_SQL = `SELECT hosted.record_business_recovery_delivery(
  $1::text, $2::text) AS recorded`;
const CLAIM_SQL = `SELECT hosted.claim_business_recovery_device(
  $1::uuid, $2::uuid, $3::uuid, $4::uuid, $5::text, $6::uuid,
  $7::text) AS vault_id`;

class BusinessRecoveryError extends Error {
  constructor() { super('business_recovery_unavailable'); }
}

function challengeHash(code) {
  if (typeof code !== 'string' || !CODE.test(code)) {
    throw new BusinessRecoveryError();
  }
  return createHash('sha256')
    .update('codex-backup-business-recovery-challenge-v1\0')
    .update(code).digest('hex');
}

function validPurpose(purpose) {
  return typeof purpose === 'string' && PURPOSE.test(purpose) &&
    purpose === purpose.trim() && !/[\r\n\u0000-\u001f\u007f]/.test(purpose);
}

async function beginBusinessRecovery({ adminSessionToken, accountId, seatId,
  vaultId, purpose, query, sendChallenge }) {
  if (![accountId, seatId, vaultId].every(value => UUID.test(value)) ||
      !validPurpose(purpose) || typeof query !== 'function' ||
      typeof sendChallenge !== 'function') throw new BusinessRecoveryError();
  try {
    const requestId = randomUUID();
    const code = `hvcr1_${randomBytes(32).toString('base64url')}`;
    const hash = challengeHash(code);
    const issued = await query(ISSUE_SQL, [sessionHash(adminSessionToken),
      accountId, seatId, vaultId, requestId, purpose, hash]);
    const contact = issued?.rows?.[0]?.contact;
    if (issued?.rows?.length !== 1 || typeof contact !== 'string' ||
        contact.length > 254 || !EMAIL.test(contact)) {
      throw new BusinessRecoveryError();
    }
    let delivery;
    try {
      delivery = await sendChallenge({ to: contact, code,
        purpose: 'business-recovery-sandbox', requestId });
    } catch { delivery = 'uncertain'; }
    const state = delivery === 'accepted' ? 'sent' :
      delivery === 'rejected' ? 'rejected' : 'uncertain';
    const recorded = await query(DELIVERY_SQL, [hash, state]);
    if (recorded?.rows?.[0]?.recorded !== true || state !== 'sent') {
      throw new BusinessRecoveryError();
    }
    return Object.freeze({ requestId, status: 'sent' });
  } catch { throw new BusinessRecoveryError(); }
}

async function claimBusinessRecovery({ accountId, seatId, vaultId, requestId,
  code, deviceId, deviceTokenHash, query }) {
  if (![accountId, seatId, vaultId, requestId, deviceId]
    .every(value => UUID.test(value)) ||
      typeof deviceTokenHash !== 'string' || !DIGEST.test(deviceTokenHash) ||
      typeof query !== 'function') throw new BusinessRecoveryError();
  try {
    const result = await query(CLAIM_SQL, [accountId, seatId, vaultId,
      requestId, challengeHash(code), deviceId, deviceTokenHash]);
    if (result?.rows?.length !== 1 || result.rows[0]?.vault_id !== vaultId) {
      throw new BusinessRecoveryError();
    }
    return Object.freeze({ accountId, seatId, vaultId, deviceId });
  } catch { throw new BusinessRecoveryError(); }
}

module.exports = { BusinessRecoveryError, beginBusinessRecovery,
  claimBusinessRecovery, challengeHash, validPurpose };
