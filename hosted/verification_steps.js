// One bounded provider-verification step. The client sees only progress, never
// a complete receipt or a claim that a staged snapshot is protected.
const { consumeAuthorizedScope } = require('./access');

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const HEX = /^[0-9a-f]{64}$/;
const PAGE_SIZE = 128;
const SCOPE_SQL = `SELECT staged_count, staged_bytes, declared_count,
    declared_bytes, state, expires_at > clock_timestamp() AS lease_valid
  FROM hosted.upload_reservations
  WHERE account_id = $1::uuid AND vault_id = $2::uuid
    AND reservation_id = $3::uuid AND staged_snapshot_id = $4::uuid`;
const NEXT_SQL = `SELECT so.object_key, so.object_bytes, so.sha256
  FROM hosted.staged_receipt_objects AS so
  LEFT JOIN hosted.verified_receipt_objects AS verified
    ON verified.reservation_id = so.reservation_id
      AND verified.object_key = so.object_key
  WHERE so.reservation_id = $1::uuid
    AND (verified.object_key IS NULL OR
      verified.verified_at < clock_timestamp() - interval '24 hours')
  ORDER BY so.object_key LIMIT 128`;
const RECORD_SQL = `SELECT hosted.record_verified_receipt_page_current(
  $1::uuid, $2::uuid, $3::uuid, $4::uuid, $5::jsonb, $6::bigint
) AS accepted`;

class HostedVerificationStepError extends Error {
  constructor() { super('hosted_verification_step_failed'); }
}

async function verifyNextPage({ scope, reservationId, snapshotId,
  verifyBatch, query }) {
  if (!consumeAuthorizedScope(scope) || !UUID.test(reservationId) ||
      !UUID.test(snapshotId) || typeof verifyBatch !== 'function' ||
      typeof query !== 'function') throw new HostedVerificationStepError();
  try {
    const summary = await query(SCOPE_SQL, [scope.accountId, scope.vaultId,
      reservationId, snapshotId]);
    const row = summary?.rows?.[0];
    const count = Number(row?.staged_count);
    const bytes = Number(row?.staged_bytes);
    if (summary?.rows?.length !== 1 || row.state !== 'active' ||
        row.lease_valid !== true || !Number.isSafeInteger(count) ||
        count < 3 || count > 1_000_000 ||
        !Number.isSafeInteger(bytes) || bytes < count ||
        bytes > scope.allowanceBytes ||
        Number(row.declared_count) !== count ||
        Number(row.declared_bytes) !== bytes) {
      throw new HostedVerificationStepError();
    }
    const next = await query(NEXT_SQL, [reservationId]);
    const rows = next?.rows;
    if (!Array.isArray(rows) || rows.length > PAGE_SIZE) {
      throw new HostedVerificationStepError();
    }
    if (rows.length === 0) return Object.freeze({ verifiedObjects: 0, ready: true });
    const prefix = `accounts/${scope.accountId}/vaults/${scope.vaultId}/`;
    const keys = new Set();
    const batch = rows.map(item => {
      const size = Number(item.object_bytes);
      if (typeof item.object_key !== 'string' ||
          !item.object_key.startsWith(prefix) || keys.has(item.object_key) ||
          !Number.isSafeInteger(size) || size < 1 || size > 100_000_000 ||
          typeof item.sha256 !== 'string' || !HEX.test(item.sha256)) {
        throw new HostedVerificationStepError();
      }
      keys.add(item.object_key);
      return Object.freeze({ key: item.object_key, bytes: size,
        sha256: item.sha256 });
    });
    if (await verifyBatch(batch) !== true) throw new HostedVerificationStepError();
    const recorded = await query(RECORD_SQL, [scope.accountId, scope.vaultId,
      reservationId, snapshotId, JSON.stringify(batch), scope.allowanceBytes]);
    if (recorded?.rows?.length !== 1 ||
        Number(recorded.rows[0].accepted) !== batch.length) {
      throw new HostedVerificationStepError();
    }
    return Object.freeze({ verifiedObjects: batch.length, ready: false });
  } catch {
    // Do not leak database, object, subscription or Worker details to a caller.
    throw new HostedVerificationStepError();
  }
}

module.exports = { HostedVerificationStepError, verifyNextPage };
