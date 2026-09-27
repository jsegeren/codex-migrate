// Server-only enumeration of one published snapshot for clean-Mac recovery.
// No unbounded receipt or client-supplied inventory is trusted as authority.
const { consumeAuthorizedReadScope } = require('./access');
const { validItem } = require('./object_capability');

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const HEX = /^[0-9a-f]{64}$/;
const PAGE_SIZE = 256;
const LATEST_SQL = `SELECT v.last_good_snapshot_id, s.verified_object_count,
    r.staged_bytes
  FROM hosted.vaults AS v
  LEFT JOIN hosted.snapshots AS s ON s.account_id = v.account_id
    AND s.vault_id = v.vault_id AND s.snapshot_id = v.last_good_snapshot_id
  LEFT JOIN hosted.upload_reservations AS r ON r.reservation_id = s.reservation_id
  WHERE v.account_id = $1::uuid AND v.vault_id = $2::uuid`;
const PAGE_SQL = `SELECT s.verified_object_count, r.staged_bytes,
    so.object_key, o.bytes, o.sha256
  FROM hosted.snapshots AS s
  JOIN hosted.upload_reservations AS r ON r.reservation_id = s.reservation_id
  JOIN hosted.snapshot_objects AS so
    ON so.account_id = s.account_id AND so.vault_id = s.vault_id
      AND so.snapshot_id = s.snapshot_id
  JOIN hosted.objects AS o
    ON o.account_id = so.account_id AND o.vault_id = so.vault_id
      AND o.object_key = so.object_key
  WHERE s.account_id = $1::uuid AND s.vault_id = $2::uuid
    AND s.snapshot_id = $3::uuid AND so.object_key > $4::text
  ORDER BY so.object_key LIMIT 257`;

class HostedInventoryError extends Error {
  constructor() { super('hosted_inventory_denied'); }
}

function validCursor(afterKey, prefix) {
  if (afterKey === null) return true;
  if (typeof afterKey !== 'string' || !afterKey.startsWith(prefix)) return false;
  // Use the same key grammar as the object Worker. Bytes and digest here are
  // placeholders only for grammar validation, never signed or returned.
  return validItem({ key: afterKey, bytes: 1, sha256: '0'.repeat(64) });
}

async function getLastGoodSnapshot({ scope, query }) {
  if (!consumeAuthorizedReadScope(scope) || typeof query !== 'function') {
    throw new HostedInventoryError();
  }
  try {
    const result = await query(LATEST_SQL, [scope.accountId, scope.vaultId]);
    const row = result?.rows?.[0];
    if (result?.rows?.length !== 1) throw new HostedInventoryError();
    if (row.last_good_snapshot_id === null) return null;
    const count = Number(row?.verified_object_count);
    const bytes = Number(row?.staged_bytes);
    if (!UUID.test(row.last_good_snapshot_id) ||
        !Number.isSafeInteger(count) || count < 3 || count > 1_000_000 ||
        !Number.isSafeInteger(bytes) || bytes < count) {
      throw new HostedInventoryError();
    }
    return Object.freeze({ snapshotId: row.last_good_snapshot_id,
      totalObjects: count, totalBytes: bytes });
  } catch { throw new HostedInventoryError(); }
}

async function listPublishedObjects({ scope, snapshotId, afterKey = null, query }) {
  if (!consumeAuthorizedReadScope(scope) || !UUID.test(snapshotId) ||
      typeof query !== 'function') throw new HostedInventoryError();
  const prefix = `accounts/${scope.accountId}/vaults/${scope.vaultId}/`;
  if (!validCursor(afterKey, prefix)) throw new HostedInventoryError();
  try {
    const result = await query(PAGE_SQL, [scope.accountId, scope.vaultId,
      snapshotId, afterKey || '']);
    const rows = result?.rows;
    if (!Array.isArray(rows) || rows.length < 1 || rows.length > PAGE_SIZE + 1) {
      throw new HostedInventoryError();
    }
    const total = Number(rows[0].verified_object_count);
    const totalBytes = Number(rows[0].staged_bytes);
    if (!Number.isSafeInteger(total) || total < 3 || total > 1_000_000 ||
        rows.length > total || !Number.isSafeInteger(totalBytes) ||
        totalBytes < total) {
      throw new HostedInventoryError();
    }
    let prior = afterKey || '';
    const objects = rows.map(row => {
      const bytes = Number(row.bytes);
      const item = { key: row.object_key, bytes, sha256: row.sha256 };
      if (Number(row.verified_object_count) !== total ||
          Number(row.staged_bytes) !== totalBytes ||
          typeof item.sha256 !== 'string' || !HEX.test(item.sha256) ||
          !item.key.startsWith(prefix) || item.key <= prior || !validItem(item)) {
        throw new HostedInventoryError();
      }
      prior = item.key;
      return Object.freeze({ key: item.key.slice(prefix.length), bytes,
        sha256: item.sha256 });
    });
    const hasMore = objects.length > PAGE_SIZE;
    if (hasMore) objects.pop();
    return Object.freeze({ snapshotId, totalObjects: total, totalBytes,
      objects: Object.freeze(objects),
      nextCursor: hasMore ? prefix + objects[objects.length - 1].key : null });
  } catch { throw new HostedInventoryError(); }
}

module.exports = { HostedInventoryError, getLastGoodSnapshot,
  listPublishedObjects };
