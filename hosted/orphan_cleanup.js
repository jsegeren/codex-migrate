// Operator-only, deliberately not exposed by an HTTP route. The database
// claims an expired orphan before this signs one exact DELETE. A 204 from the
// Worker means R2 HEAD proved absence after deletion (or it was already
// absent); only then may the server record absence for later quota release.
const { signObjectCapability, validItem } = require('./object_capability');

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const CLAIM_SQL = `SELECT object_bytes, object_sha256, issued_at
  FROM hosted.issue_cleanup_delete_grant($1::uuid, $2::uuid, $3::uuid, $4::text)`;
const ABSENT_SQL = `SELECT hosted.record_cleanup_object_absent(
  $1::uuid, $2::uuid, $3::uuid, $4::text, $5::bigint, $6::text
) AS allowed`;
const RELEASE_SQL = `SELECT hosted.release_cleaned_upload_reservation(
  $1::uuid, $2::uuid, $3::uuid
) AS allowed`;

class HostedOrphanCleanupError extends Error {
  constructor() { super('hosted_orphan_cleanup_failed'); }
}

function validScope(accountId, vaultId, reservationId) {
  return [accountId, vaultId, reservationId].every(value =>
    typeof value === 'string' && UUID.test(value));
}

function createOperatorCleanupDeleter({ origin, secret, query,
  fetchImpl = fetch, now = Date.now, allowLoopbackHttp = false }) {
  let parsed;
  try { parsed = new URL(origin); }
  catch { throw new HostedOrphanCleanupError(); }
  if (parsed.username || parsed.password || parsed.pathname !== '/' ||
      parsed.search || parsed.hash || !parsed.hostname ||
      (parsed.protocol !== 'https:' && !(allowLoopbackHttp &&
        parsed.protocol === 'http:' &&
        ['127.0.0.1', '[::1]'].includes(parsed.hostname))) ||
      !(secret instanceof Uint8Array) || secret.byteLength !== 32 ||
      typeof query !== 'function' || typeof fetchImpl !== 'function' ||
      typeof now !== 'function') throw new HostedOrphanCleanupError();

  return async ({ accountId, vaultId, reservationId, key }) => {
    if (!validScope(accountId, vaultId, reservationId) ||
      typeof key !== 'string' ||
      !key.startsWith(`accounts/${accountId}/vaults/${vaultId}/`)) {
      throw new HostedOrphanCleanupError();
    }
    try {
      const claim = await query(CLAIM_SQL, [accountId, vaultId,
        reservationId, key]);
      if (claim?.rows?.length !== 1) throw new HostedOrphanCleanupError();
      const row = claim.rows[0];
      const item = { key, bytes: Number(row.object_bytes),
        sha256: row.object_sha256 };
      if (!validItem(item) || String(item.bytes) !== String(row.object_bytes)) {
        throw new HostedOrphanCleanupError();
      }
      const issued = row.issued_at instanceof Date ? row.issued_at.getTime() :
        Date.parse(row.issued_at);
      const current = now();
      // Sign with the database's issue time, not a new wall-clock value. A
      // delayed response cannot mint a fresh token after the claim is freed.
      if (!Number.isSafeInteger(issued) || !Number.isSafeInteger(current) ||
          issued > current + 10_000 || current - issued > 10_000) {
        throw new HostedOrphanCleanupError();
      }
      const token = await signObjectCapability('DELETE', item, secret,
        issued, 30_000);
      const response = await fetchImpl(
        `${parsed.origin}/v1/object/${key}`, { method: 'DELETE',
          redirect: 'error', cache: 'no-store',
          headers: { Authorization: `Bearer ${token}` },
          signal: AbortSignal.timeout(30_000) });
      if (response?.status !== 204) throw new HostedOrphanCleanupError();
      const recorded = await query(ABSENT_SQL, [accountId, vaultId,
        reservationId, key, item.bytes, item.sha256]);
      if (recorded?.rows?.length !== 1 ||
          recorded.rows[0].allowed !== true) throw new HostedOrphanCleanupError();
      return Object.freeze({ objectAbsent: true });
    } catch { throw new HostedOrphanCleanupError(); }
  };
}

// Separate from object deletion. PostgreSQL releases capacity only after
// every grant is published or has a sufficiently old provider-absence record.
function createOperatorCleanupReleaser({ query }) {
  if (typeof query !== 'function') throw new HostedOrphanCleanupError();
  return async ({ accountId, vaultId, reservationId }) => {
    if (!validScope(accountId, vaultId, reservationId)) {
      throw new HostedOrphanCleanupError();
    }
    try {
      const result = await query(RELEASE_SQL,
        [accountId, vaultId, reservationId]);
      if (result?.rows?.length !== 1 || result.rows[0].allowed !== true) {
        throw new HostedOrphanCleanupError();
      }
      return Object.freeze({ quotaReleased: true });
    } catch { throw new HostedOrphanCleanupError(); }
  };
}

module.exports = { HostedOrphanCleanupError,
  createOperatorCleanupDeleter, createOperatorCleanupReleaser };
