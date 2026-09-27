// Server-only reservation boundary. The caller must freshly authorize the
// device, app purchase, and subscription for *each* create or renewal. Never
// trust an account, Vault, or allowance sent by a device.
const { randomUUID } = require('node:crypto');
const { consumeAuthorizedScope, consumeAuthorizedReadScope } = require('./access');

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const LEASE_MS = 55 * 60 * 1000;
const CREATE_SQL = `SELECT hosted.reserve_upload_current(
  $1::uuid, $2::uuid, $3::uuid, $4::bigint, $5::timestamptz, $6::bigint
) AS allowed`;
const RENEW_SQL = `SELECT hosted.renew_upload_reservation_current(
  $1::uuid, $2::uuid, $3::uuid, $4::timestamptz, $5::bigint
) AS allowed`;
const ABANDON_SQL = `SELECT hosted.abandon_upload_reservation(
  $1::uuid, $2::uuid, $3::uuid
) AS allowed`;
const STATUS_SQL = `SELECT state FROM hosted.upload_reservations
  WHERE account_id = $1::uuid AND vault_id = $2::uuid
    AND reservation_id = $3::uuid`;
const STATES = new Set(['active', 'cleanup_pending', 'released', 'published']);

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

async function abandonUploadReservation({ scope, reservationId, query }) {
  // A lapsed subscription may stop a pending upload. Device ownership is
  // still required, but no paid entitlement or customer-supplied account ID.
  if (!consumeAuthorizedReadScope(scope) || !UUID.test(reservationId) ||
      typeof query !== 'function') throw new HostedReservationError();
  try {
    const result = await query(ABANDON_SQL, [scope.accountId, scope.vaultId,
      reservationId]);
    if (result?.rows?.length !== 1 || result.rows[0].allowed !== true) {
      throw new HostedReservationError();
    }
    return Object.freeze({ cleanupPending: true });
  } catch { throw new HostedReservationError(); }
}

async function readUploadReservationStatus({ scope, reservationId, query }) {
  // Only the owning device may inspect this exact account/Vault reservation.
  // Reading remains available after a subscription lapses so customers can
  // distinguish quarantine from proven cleanup and released quota.
  if (!consumeAuthorizedReadScope(scope) || !UUID.test(reservationId) ||
      typeof query !== 'function') throw new HostedReservationError();
  try {
    const result = await query(STATUS_SQL, [scope.accountId, scope.vaultId,
      reservationId]);
    const state = result?.rows?.[0]?.state;
    if (result?.rows?.length !== 1 || !STATES.has(state)) {
      throw new HostedReservationError();
    }
    return Object.freeze({ state });
  } catch { throw new HostedReservationError(); }
}

module.exports = { HostedReservationError, createUploadReservation,
  renewUploadReservation, abandonUploadReservation,
  readUploadReservationStatus };
