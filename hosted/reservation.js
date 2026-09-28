// Server-only reservation boundary. The caller must freshly authorize the
// device, app purchase, and subscription for *each* create or renewal. Never
// trust an account, Vault, or allowance sent by a device.
const { randomUUID } = require('node:crypto');
const { consumeAuthorizedScope, consumeAuthorizedReadScope } = require('./access');

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const LEASE_MS = 55 * 60 * 1000;
const CREATE_SQL = `SELECT allowed, base_snapshot_id, expires_at
  FROM hosted.reserve_upload_idempotent_current(
  $1::uuid, $2::uuid, $3::uuid, $4::bigint, $5::timestamptz, $6::bigint
)`;
const RENEW_SQL = `SELECT hosted.renew_upload_reservation_current(
  $1::uuid, $2::uuid, $3::uuid, $4::timestamptz, $5::bigint
) AS allowed`;
const ABANDON_SQL = `SELECT hosted.abandon_upload_reservation(
  $1::uuid, $2::uuid, $3::uuid
) AS allowed`;
const STATUS_SQL = `SELECT reservation.state, snapshot.snapshot_id,
    snapshot.verified_object_count FROM hosted.upload_reservations AS reservation
  LEFT JOIN hosted.snapshots AS snapshot
    ON snapshot.reservation_id = reservation.reservation_id
   AND snapshot.account_id = reservation.account_id
   AND snapshot.vault_id = reservation.vault_id
  WHERE reservation.account_id = $1::uuid AND reservation.vault_id = $2::uuid
    AND reservation.reservation_id = $3::uuid`;
const STATES = new Set(['active', 'cleanup_pending', 'released', 'published']);

class HostedReservationError extends Error {
  constructor() { super('hosted_reservation_denied'); }
}

async function createUploadReservation({ scope, bytes, reservationId, query }) {
  if (!consumeAuthorizedScope(scope) || !Number.isSafeInteger(bytes) ||
      bytes < 1 || bytes > scope.allowanceBytes ||
      (reservationId !== undefined && !UUID.test(reservationId)) ||
      typeof query !== 'function') {
    throw new HostedReservationError();
  }
  reservationId ??= randomUUID();
  const expiresAt = new Date(Date.now() + LEASE_MS).toISOString();
  try {
    const result = await query(CREATE_SQL, [scope.accountId, scope.vaultId,
      reservationId, bytes, expiresAt, scope.allowanceBytes]);
    const row = result?.rows?.[0];
    const expiry = new Date(row?.expires_at);
    if (result?.rows?.length !== 1 || row.allowed !== true ||
        (row.base_snapshot_id !== null && !UUID.test(row.base_snapshot_id)) ||
        !Number.isFinite(expiry.getTime()) || expiry.getTime() <= Date.now() ||
        expiry.getTime() > Date.now() + LEASE_MS + 1000) {
      throw new HostedReservationError();
    }
    return Object.freeze({ reservationId, expiresAt: expiry.toISOString(),
      baseSnapshotId: row.base_snapshot_id });
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
    const row = result?.rows?.[0];
    const state = row?.state;
    if (result?.rows?.length !== 1 || !STATES.has(state) ||
        (state === 'published' ?
          (!UUID.test(row.snapshot_id) ||
           !Number.isSafeInteger(row.verified_object_count) ||
           row.verified_object_count < 3) :
          (row.snapshot_id != null || row.verified_object_count != null))) {
      throw new HostedReservationError();
    }
    return Object.freeze(state === 'published' ?
      { state, snapshotId: row.snapshot_id,
        verifiedObjectCount: row.verified_object_count } : { state });
  } catch { throw new HostedReservationError(); }
}

module.exports = { HostedReservationError, createUploadReservation,
  renewUploadReservation, abandonUploadReservation,
  readUploadReservationStatus };
