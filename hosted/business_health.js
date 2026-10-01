// Dark business backup-health metadata. A worker's check-in is never a
// recovery certificate; only the publication ledger proves object receipt.
const { businessDeviceTokenHash } = require('./business_worker');
const { sessionHash } = require('./business_admin');

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const STATES = new Set(['verified', 'unchanged', 'needs_attention', 'failed']);
const REPORT_SQL = `SELECT account_id, seat_id, vault_id, checked_at
  FROM hosted.record_business_backup_check($1::text, $2::uuid,
    $3::text, $4::uuid)`;
const LIST_SQL = `SELECT s.seat_id, sv.vault_id, s.revoked_at,
    c.reported_state, c.reported_snapshot_id, c.checked_at,
    v.last_good_snapshot_id, latest.published_at, latest.source_coverage
  FROM hosted.business_admin_sessions AS admin
  JOIN hosted.business_seats AS s ON s.account_id = admin.account_id
  LEFT JOIN hosted.business_seat_vaults AS sv
    ON sv.account_id = s.account_id AND sv.seat_id = s.seat_id
  LEFT JOIN hosted.vaults AS v
    ON v.account_id = sv.account_id AND v.vault_id = sv.vault_id
  LEFT JOIN hosted.snapshots AS latest
    ON latest.account_id = v.account_id AND latest.vault_id = v.vault_id
      AND latest.snapshot_id = v.last_good_snapshot_id
  LEFT JOIN hosted.business_backup_checks AS c
    ON c.account_id = sv.account_id AND c.vault_id = sv.vault_id
  WHERE admin.token_hash = $1 AND admin.revoked_at IS NULL
    AND admin.expires_at > clock_timestamp()
  ORDER BY s.seat_id LIMIT 501`;

class BusinessHealthError extends Error {
  constructor() { super('business_health_unavailable'); }
}

function timestamp(value) {
  if (value === null) return null;
  const result = value instanceof Date ? value.toISOString() : value;
  if (typeof result !== 'string' || !Number.isFinite(Date.parse(result))) {
    throw new BusinessHealthError();
  }
  return result;
}

async function reportBusinessCheck({ deviceToken, deviceId, reportedState,
  snapshotId, query }) {
  if (!UUID.test(deviceId) || !STATES.has(reportedState) ||
      (reportedState === 'failed' ? snapshotId !== null : !UUID.test(snapshotId)) ||
      typeof query !== 'function') throw new BusinessHealthError();
  try {
    const result = await query(REPORT_SQL, [businessDeviceTokenHash(deviceToken),
      deviceId, reportedState, snapshotId]);
    const row = result?.rows?.[0];
    if (result?.rows?.length !== 1 ||
        ![row?.account_id, row?.seat_id, row?.vault_id].every(id =>
          typeof id === 'string' && UUID.test(id))) {
      throw new BusinessHealthError();
    }
    return Object.freeze({ accountId: row.account_id, seatId: row.seat_id,
      vaultId: row.vault_id, checkedAt: timestamp(row.checked_at) });
  } catch { throw new BusinessHealthError(); }
}

async function listBusinessHealth({ adminToken, query, now = new Date() }) {
  if (typeof query !== 'function' || !(now instanceof Date) ||
      !Number.isFinite(now.getTime())) throw new BusinessHealthError();
  try {
    const result = await query(LIST_SQL, [sessionHash(adminToken)]);
    // An empty result cannot distinguish no seats from invalid authority.
    // A pilot administrator must have at least one approved seat.
    if (!Array.isArray(result?.rows) || result.rows.length === 0 ||
        result.rows.length > 500) throw new BusinessHealthError();
    const seats = result.rows.map(row => {
      if (!UUID.test(row.seat_id) ||
          (row.vault_id !== null && !UUID.test(row.vault_id)) ||
          (row.reported_snapshot_id !== null &&
            !UUID.test(row.reported_snapshot_id)) ||
          (row.last_good_snapshot_id !== null &&
            !UUID.test(row.last_good_snapshot_id)) ||
          (row.reported_state !== null && !STATES.has(row.reported_state)) ||
          (row.source_coverage !== null && !['unknown', 'complete',
            'needs_attention'].includes(row.source_coverage))) {
        throw new BusinessHealthError();
      }
      const checkedAt = timestamp(row.checked_at);
      const publishedAt = timestamp(row.published_at);
      const revoked = row.revoked_at !== null;
      const stale = !checkedAt ||
        now.getTime() - Date.parse(checkedAt) > 90 * 60 * 1000 ||
        Date.parse(checkedAt) > now.getTime() + 60 * 1000;
      return Object.freeze({ seatId: row.seat_id, vaultId: row.vault_id,
        revoked, lastReportedState: row.reported_state,
        lastReportedCheckAt: checkedAt,
        lastReportedSnapshotId: row.reported_snapshot_id,
        lastPublishedSnapshotId: row.last_good_snapshot_id,
        lastPublishedAt: publishedAt,
        lastPublishedSourceCoverage: row.source_coverage,
        needsAttention: !revoked &&
          (stale || !['verified', 'unchanged'].includes(row.reported_state) ||
            row.reported_snapshot_id !== row.last_good_snapshot_id ||
            row.source_coverage !== 'complete'),
        // Neither a recent check nor a published snapshot proves a company
        // recovery kit was saved and tested on a clean Mac.
        companyRecoveryVerified: false });
    });
    return Object.freeze({ seats });
  } catch { throw new BusinessHealthError(); }
}

module.exports = { BusinessHealthError, reportBusinessCheck,
  listBusinessHealth };
