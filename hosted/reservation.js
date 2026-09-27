// Server-only reservation boundary. The caller must freshly authorize the
// device, app purchase, and subscription for *each* create or renewal. Never
// trust an account, Vault, or allowance sent by a device.
const { randomUUID } = require('node:crypto');
const { consumeAuthorizedScope } = require('./access');

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const LEASE_MS = 55 * 60 * 1000;
const CREATE_SQL = `SELECT hosted.reserve_upload_current(
  $1::uuid, $2::uuid, $3::uuid, $4::bigint, $5::timestamptz, $6::bigint
) AS allowed`;
const RENEW_SQL = `SELECT hosted.renew_upload_reservation_current(
  $1::uuid, $2::uuid, $3::uuid, $4::timestamptz, $5::bigint
) AS allowed`;

class HostedReservationError extends Error {
  constructor() { super('hosted_reservation_denied'); }
}

async function createUploadReservation({ scope, bytes, query }) {
  if (!consumeAuthorizedScope(scope) || !Number.isSafeInteger(bytes) ||
      bytes < 1 || bytes > scope.allowanceBytes || typeof query !== 'function') {
    throw new HostedReservationError();
  }
  const reservationId = randomUUID();
  const expiresAt = new Date(Date.now() + LEASE_MS).toISOString();
  try {
    const result = await query(CREATE_SQL, [scope.accountId, scope.vaultId,
      reservationId, bytes, expiresAt, scope.allowanceBytes]);
    if (result?.rows?.length !== 1 || result.rows[0].allowed !== true) {
      throw new HostedReservationError();
    }
    return Object.freeze({ reservationId, expiresAt });
  } catch { throw new HostedReservationError(); }
}

async function renewUploadReservation({ scope, reservationId, query }) {
  if (!consumeAuthorizedScope(scope) || !UUID.test(reservationId) ||
      typeof query !== 'function') throw new HostedReservationError();
  const expiresAt = new Date(Date.now() + LEASE_MS).toISOString();
  try {
    const result = await query(RENEW_SQL, [scope.accountId, scope.vaultId,
      reservationId, expiresAt, scope.allowanceBytes]);
    if (result?.rows?.length !== 1 || result.rows[0].allowed !== true) {
      throw new HostedReservationError();
    }
    return Object.freeze({ reservationId, expiresAt });
  } catch { throw new HostedReservationError(); }
}

module.exports = { HostedReservationError, createUploadReservation,
  renewUploadReservation };
