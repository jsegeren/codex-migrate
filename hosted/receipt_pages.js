// Server-only page admission. Pages are untrusted object claims, not a backup.
// The complete stored set must still be assembled and provider-verified before
// the publication transaction can advance last-good.
const { consumeAuthorizedScope } = require('./access');

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const HEX = /^[0-9a-f]{64}$/;
const CHUNK = /^objects\/[0-9a-f]{2}\/[0-9a-f]{62}\.cvchunk$/;
const PAGE_LIMIT = 512;
const PAGE_SQL = `SELECT hosted.append_receipt_page_current(
  $1::uuid, $2::uuid, $3::uuid, $4::uuid, $5::jsonb, $6::bigint
) AS accepted`;

class HostedReceiptPageError extends Error {
  constructor() { super('hosted_receipt_page_denied'); }
}

function checkedPage(objects, snapshotId, scope) {
  if (!Array.isArray(objects) || objects.length < 1 || objects.length > PAGE_LIMIT) {
    throw new HostedReceiptPageError();
  }
  const prefix = `accounts/${scope.accountId}/vaults/${scope.vaultId}/`;
  const keys = new Set();
  let bytes = 0;
  const scoped = objects.map(item => {
    if (!item || typeof item !== 'object' || Array.isArray(item) ||
        Object.keys(item).sort().join(',') !== 'bytes,key,sha256' ||
        typeof item.key !== 'string' || typeof item.sha256 !== 'string' ||
        !HEX.test(item.sha256) || !Number.isSafeInteger(item.bytes) ||
        item.bytes < 1 || item.bytes > 100_000_000 || keys.has(item.key)) {
      throw new HostedReceiptPageError();
    }
    const valid = (item.key === `metadata/${snapshotId}.json` && item.bytes <= 1_048_576) ||
      item.key === `manifests/${snapshotId}.cvmanifest` ||
      (item.key === `refs/${snapshotId}.json` && item.bytes <= 1_048_576) ||
      (CHUNK.test(item.key) && item.bytes <= 67_109_888);
    if (!valid) throw new HostedReceiptPageError();
    keys.add(item.key);
    bytes += item.bytes;
    if (!Number.isSafeInteger(bytes) || bytes > scope.allowanceBytes) {
      throw new HostedReceiptPageError();
    }
    return Object.freeze({ key: prefix + item.key, bytes: item.bytes,
      sha256: item.sha256 });
  });
  return Object.freeze(scoped);
}

async function appendStagedPage({ scope, reservationId, snapshotId, objects, query }) {
  if (!consumeAuthorizedScope(scope) || !UUID.test(reservationId) ||
      !UUID.test(snapshotId) || typeof query !== 'function') {
    throw new HostedReceiptPageError();
  }
  const scoped = checkedPage(objects, snapshotId, scope);
  try {
    const result = await query(PAGE_SQL, [scope.accountId, scope.vaultId,
      reservationId, snapshotId, JSON.stringify(scoped), scope.allowanceBytes]);
    if (result?.rows?.length !== 1 || result.rows[0].accepted !== true) {
      throw new HostedReceiptPageError();
    }
  } catch {
    throw new HostedReceiptPageError();
  }
  return Object.freeze({ acceptedObjects: scoped.length });
}

module.exports = { HostedReceiptPageError, appendStagedPage };
