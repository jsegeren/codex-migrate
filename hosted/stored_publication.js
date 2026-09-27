// Assemble admitted receipt pages inside the service. No complete receipt
// arrives over a web request. Every object is still independently checked
// against R2 before the staged-set-matching publication transaction runs.
const { isAuthorizedScope } = require('./access');
const { publishStagedReceipt } = require('./publication');

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const HEX = /^[0-9a-f]{64}$/;
const MAX_OBJECTS = 1_000_000;
const LOAD_SQL = `SELECT r.staged_snapshot_id, r.staged_count, r.staged_bytes,
    r.declared_count, r.declared_bytes,
    so.object_key, so.object_bytes, so.sha256
  FROM hosted.upload_reservations AS r
  JOIN hosted.staged_receipt_objects AS so
    ON so.reservation_id = r.reservation_id
  WHERE r.account_id = $1::uuid AND r.vault_id = $2::uuid
    AND r.reservation_id = $3::uuid AND r.staged_snapshot_id = $4::uuid
    AND r.state IN ('active', 'published')
  ORDER BY so.object_key`;

class HostedStoredPublicationError extends Error {
  constructor() { super('hosted_stored_publication_failed'); }
}

function receiptFromRows(rows, scope, snapshotId) {
  if (!Array.isArray(rows) || rows.length < 3 || rows.length > MAX_OBJECTS) {
    throw new HostedStoredPublicationError();
  }
  const prefix = `accounts/${scope.accountId}/vaults/${scope.vaultId}/`;
  const first = rows[0];
  const count = Number(first.staged_count);
  const bytes = Number(first.staged_bytes);
  if (!Number.isSafeInteger(count) || count !== rows.length ||
      !Number.isSafeInteger(bytes) || bytes <= 0 ||
      bytes > scope.allowanceBytes ||
      Number(first.declared_count) !== count ||
      Number(first.declared_bytes) !== bytes) {
    throw new HostedStoredPublicationError();
  }
  let observedBytes = 0;
  const objects = rows.map(row => {
    const size = Number(row.object_bytes);
    if (row.staged_snapshot_id !== snapshotId ||
        Number(row.staged_count) !== count || Number(row.staged_bytes) !== bytes ||
        Number(row.declared_count) !== count ||
        Number(row.declared_bytes) !== bytes ||
        typeof row.object_key !== 'string' ||
        !row.object_key.startsWith(prefix) ||
        !Number.isSafeInteger(size) || size <= 0 || size > 100_000_000 ||
        typeof row.sha256 !== 'string' || !HEX.test(row.sha256)) {
      throw new HostedStoredPublicationError();
    }
    observedBytes += size;
    if (!Number.isSafeInteger(observedBytes) || observedBytes > bytes) {
      throw new HostedStoredPublicationError();
    }
    return { key: row.object_key.slice(prefix.length), bytes: size,
      sha256: row.sha256 };
  });
  if (observedBytes !== bytes) throw new HostedStoredPublicationError();
  const rank = key => key.startsWith('metadata/') ? 0 :
    key.startsWith('objects/') ? 1 : key.startsWith('manifests/') ? 2 : 3;
  objects.sort((a, b) => rank(a.key) - rank(b.key) ||
    (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));
  return { version: 1, snapshot_id: snapshotId,
    remote_bytes_checked: bytes, objects };
}

async function publishStoredPages({ scope, reservationId, snapshotId,
  verifyBatch, query }) {
  if (!isAuthorizedScope(scope) || !UUID.test(reservationId) ||
      !UUID.test(snapshotId) || typeof query !== 'function' ||
      typeof verifyBatch !== 'function') throw new HostedStoredPublicationError();
  try {
    const result = await query(LOAD_SQL, [scope.accountId, scope.vaultId,
      reservationId, snapshotId]);
    const receipt = receiptFromRows(result?.rows, scope, snapshotId);
    return await publishStagedReceipt({ receipt, maxReceiptBytes: scope.allowanceBytes,
      scope, reservationId, verifyBatch, query });
  } catch {
    // Database or provider exceptions can include tenant and credential data.
    throw new HostedStoredPublicationError();
  }
}

module.exports = { HostedStoredPublicationError, publishStoredPages };
