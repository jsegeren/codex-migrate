// Dark first-device pairing for an already approved business seat. The
// worker's exact mailbox must be proven; neither pairing nor the resulting
// metadata session is a backup, billing, or recovery entitlement.
const { createHash, randomBytes } = require('node:crypto');
const { sessionHash } = require('./business_admin');

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const DIGEST = /^[0-9a-f]{64}$/;
const EMAIL = /^[^\s<>@\r\n]+@[^\s<>@\r\n]+\.[^\s<>@\r\n]+$/;
const CHALLENGE = /^hvwe1_[A-Za-z0-9_-]{43}$/;
const DEVICE = /^hvb1_[A-Za-z0-9_-]{43}$/;
const ISSUE_SQL = `SELECT hosted.issue_business_worker_challenge(
  $1::text, $2::uuid, $3::uuid, $4::text) AS contact`;
const DELIVERY_SQL = `SELECT hosted.record_business_worker_challenge_delivery(
  $1::text, $2::text) AS recorded`;
const CLAIM_SQL = `SELECT hosted.claim_business_first_device(
  $1::uuid, $2::uuid, $3::text, $4::uuid, $5::uuid, $6::text) AS vault_id`;
const RESOLVE_SQL = `SELECT d.account_id, d.seat_id, d.vault_id, d.device_id,
    d.access_purpose
  FROM hosted.business_device_sessions AS d
  JOIN hosted.business_seats AS s
    ON s.account_id = d.account_id AND s.seat_id = d.seat_id
  WHERE d.token_hash = $1 AND d.device_id = $2 AND d.revoked_at IS NULL
    AND d.expires_at > clock_timestamp() AND s.revoked_at IS NULL`;
const ROTATE_SQL = `SELECT account_id, seat_id, vault_id
  FROM hosted.rotate_business_worker_device($1::text, $2::uuid,
    $3::text, $4::uuid)`;

class BusinessWorkerError extends Error {
  constructor() { super('business_worker_unavailable'); }
}

function digest(domain, token, pattern) {
  if (typeof token !== 'string' || !pattern.test(token)) {
    throw new BusinessWorkerError();
  }
  return createHash('sha256').update(domain).update('\0').update(token)
    .digest('hex');
}

function challengeHash(token) {
  return digest('codex-backup-business-worker-challenge-v1', token, CHALLENGE);
}

function businessDeviceTokenHash(token) {
  return digest('codex-backup-business-device-v1', token, DEVICE);
}

async function beginBusinessWorkerPairing({ adminSessionToken, accountId,
  seatId, query, sendChallenge }) {
  if (!UUID.test(accountId) || !UUID.test(seatId) ||
      typeof query !== 'function' || typeof sendChallenge !== 'function') {
    throw new BusinessWorkerError();
  }
  try {
    const code = `hvwe1_${randomBytes(32).toString('base64url')}`;
    const hash = challengeHash(code);
    const result = await query(ISSUE_SQL,
      [sessionHash(adminSessionToken), accountId, seatId, hash]);
    const contact = result?.rows?.[0]?.contact;
    if (result?.rows?.length !== 1 || typeof contact !== 'string' ||
        contact.length > 254 || !EMAIL.test(contact)) {
      throw new BusinessWorkerError();
    }
    let delivery;
    try {
      delivery = await sendChallenge({ to: contact, code,
        purpose: 'business-worker-sandbox' });
    } catch { delivery = 'uncertain'; }
    const state = delivery === 'accepted' ? 'sent' :
      delivery === 'rejected' ? 'rejected' : 'uncertain';
    const recorded = await query(DELIVERY_SQL, [hash, state]);
    if (recorded?.rows?.[0]?.recorded !== true || state !== 'sent') {
      throw new BusinessWorkerError();
    }
    return Object.freeze({ status: 'sent' });
  } catch { throw new BusinessWorkerError(); }
}

async function claimBusinessFirstDevice({ accountId, seatId, code, vaultId,
  deviceId, deviceTokenHash, query }) {
  if (!UUID.test(accountId) || !UUID.test(seatId) || !UUID.test(vaultId) ||
      !UUID.test(deviceId) || typeof deviceTokenHash !== 'string' ||
      !DIGEST.test(deviceTokenHash) || typeof query !== 'function') {
    throw new BusinessWorkerError();
  }
  try {
    const result = await query(CLAIM_SQL, [accountId, seatId,
      challengeHash(code), vaultId, deviceId, deviceTokenHash]);
    if (result?.rows?.length !== 1 || result.rows[0]?.vault_id !== vaultId) {
      throw new BusinessWorkerError();
    }
    // The client saved the matching secret in device-only Keychain before
    // making this request. A lost reply can resolve that same secret.
    return Object.freeze({ accountId, seatId, vaultId, deviceId });
  } catch { throw new BusinessWorkerError(); }
}

async function resolveBusinessFirstDevice({ deviceToken, deviceId, query }) {
  if (!UUID.test(deviceId) || typeof query !== 'function') {
    throw new BusinessWorkerError();
  }
  try {
    const result = await query(RESOLVE_SQL,
      [businessDeviceTokenHash(deviceToken), deviceId]);
    const row = result?.rows?.[0];
    if (result?.rows?.length !== 1 ||
        ![row?.account_id, row?.seat_id, row?.vault_id, row?.device_id]
          .every(value => typeof value === 'string' && UUID.test(value)) ||
        row.device_id !== deviceId ||
        !['worker', 'recovery'].includes(row.access_purpose)) {
      throw new BusinessWorkerError();
    }
    return Object.freeze({ accountId: row.account_id, seatId: row.seat_id,
      vaultId: row.vault_id, deviceId,
      accessPurpose: row.access_purpose });
  } catch { throw new BusinessWorkerError(); }
}

async function rotateBusinessWorkerDevice({ oldDeviceToken, oldDeviceId,
  newDeviceId, newDeviceTokenHash, query }) {
  if (!UUID.test(oldDeviceId) || !UUID.test(newDeviceId) ||
      oldDeviceId === newDeviceId || typeof newDeviceTokenHash !== 'string' ||
      !DIGEST.test(newDeviceTokenHash) || typeof query !== 'function') {
    throw new BusinessWorkerError();
  }
  try {
    const result = await query(ROTATE_SQL, [
      businessDeviceTokenHash(oldDeviceToken), oldDeviceId,
      newDeviceTokenHash, newDeviceId]);
    const row = result?.rows?.[0];
    if (result?.rows?.length !== 1 ||
        ![row?.account_id, row?.seat_id, row?.vault_id]
          .every(value => typeof value === 'string' && UUID.test(value))) {
      throw new BusinessWorkerError();
    }
    return Object.freeze({ accountId: row.account_id, seatId: row.seat_id,
      vaultId: row.vault_id, deviceId: newDeviceId });
  } catch { throw new BusinessWorkerError(); }
}

module.exports = { BusinessWorkerError, beginBusinessWorkerPairing,
  claimBusinessFirstDevice, resolveBusinessFirstDevice,
  rotateBusinessWorkerDevice,
  challengeHash, businessDeviceTokenHash };
