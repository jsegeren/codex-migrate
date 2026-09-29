// A short-lived, reservation-bound authorization envelope for the dark native
// upload client. It amortizes Stripe checks across object requests, but each
// request still proves the live device session and each object remains subject
// to its exact reservation/quota check. Never persist this token on the Mac.
const { createHmac, timingSafeEqual } = require('node:crypto');

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const DIGEST = /^[0-9a-f]{64}$/;
const B64 = /^[A-Za-z0-9_-]+$/;
const MAX_AGE_MS = 60_000;
const DOMAIN = 'codex-hosted-upload-lease-v1\0';
const RESERVATION_SQL = `SELECT 1 AS active FROM hosted.upload_reservations
  WHERE account_id = $1::uuid AND vault_id = $2::uuid
    AND reservation_id = $3::uuid AND state = 'active'
    AND expires_at > clock_timestamp() + interval '1 minute'`;

class HostedUploadLeaseError extends Error {
  constructor() { super('hosted_upload_lease_denied'); }
}

function secretBytes(secret) {
  if (!(secret instanceof Uint8Array) || secret.byteLength !== 32) {
    throw new HostedUploadLeaseError();
  }
  return Buffer.from(secret);
}

function encode(value) { return Buffer.from(value).toString('base64url'); }

function decode(value) {
  if (typeof value !== 'string' || !B64.test(value) || value.length > 600) {
    throw new HostedUploadLeaseError();
  }
  const bytes = Buffer.from(value, 'base64url');
  if (encode(bytes) !== value) throw new HostedUploadLeaseError();
  return bytes;
}

function mintUploadLease({ accountId, vaultId, reservationId, deviceHash,
  allowanceBytes, secret, now = Date.now() }) {
  if (!UUID.test(accountId) || !UUID.test(vaultId) ||
      !UUID.test(reservationId) || !DIGEST.test(deviceHash) ||
      !Number.isSafeInteger(allowanceBytes) || allowanceBytes < 1 ||
      allowanceBytes > 1_000_000_000_000 || !Number.isSafeInteger(now)) {
    throw new HostedUploadLeaseError();
  }
  const key = secretBytes(secret);
  const payload = encode(JSON.stringify({ v: 1, a: accountId, t: vaultId,
    r: reservationId, d: deviceHash, b: allowanceBytes, i: now,
    e: now + MAX_AGE_MS }));
  const signature = createHmac('sha256', key).update(DOMAIN)
    .update(payload).digest('base64url');
  return `${payload}.${signature}`;
}

function verifyUploadLease(token, secret, now = Date.now()) {
  try {
    if (typeof token !== 'string' || token.length > 750 ||
        !Number.isSafeInteger(now)) throw new HostedUploadLeaseError();
    const parts = token.split('.');
    if (parts.length !== 2) throw new HostedUploadLeaseError();
    const payload = decode(parts[0]);
    const signature = decode(parts[1]);
    const expected = createHmac('sha256', secretBytes(secret))
      .update(DOMAIN).update(parts[0]).digest();
    if (signature.length !== expected.length ||
        !timingSafeEqual(signature, expected)) throw new HostedUploadLeaseError();
    const value = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(payload));
    if (!value || typeof value !== 'object' || Array.isArray(value) ||
        Object.keys(value).sort().join(',') !== 'a,b,d,e,i,r,t,v' ||
        value.v !== 1 || !UUID.test(value.a) || !UUID.test(value.t) ||
        !UUID.test(value.r) || !DIGEST.test(value.d) ||
        !Number.isSafeInteger(value.b) || value.b < 1 ||
        value.b > 1_000_000_000_000 || !Number.isSafeInteger(value.i) ||
        !Number.isSafeInteger(value.e) ||
        value.e - value.i !== MAX_AGE_MS || value.i > now ||
        value.e <= now) throw new HostedUploadLeaseError();
    return Object.freeze({ accountId: value.a, vaultId: value.t,
      reservationId: value.r, deviceHash: value.d,
      allowanceBytes: value.b });
  } catch { throw new HostedUploadLeaseError(); }
}

async function requireActiveReservation({ accountId, vaultId, reservationId,
  query }) {
  if (!UUID.test(accountId) || !UUID.test(vaultId) ||
      !UUID.test(reservationId) || typeof query !== 'function') {
    throw new HostedUploadLeaseError();
  }
  try {
    const result = await query(RESERVATION_SQL,
      [accountId, vaultId, reservationId]);
    if (result?.rows?.length !== 1 || result.rows[0]?.active !== 1) {
      throw new HostedUploadLeaseError();
    }
  } catch { throw new HostedUploadLeaseError(); }
}

module.exports = { HostedUploadLeaseError, mintUploadLease, verifyUploadLease,
  requireActiveReservation };
