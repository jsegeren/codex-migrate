// Validate a client's staged-object claim before any hosted snapshot can be
// published. The caller supplies server-owned account/Vault IDs and a verifier
// backed by provider-validated checksums or storage-adjacent reads; this
// module never treats a client receipt, a bare PUT response, or an ETag as proof.

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const HEX = /^[0-9a-f]{64}$/;
const MAX_CHUNKS = 1_000_000;
const MAX_CHUNK_BYTES = 64 * 1024 * 1024 + 1024;
const MAX_MANIFEST_BYTES = 128 * 1024 * 1024 + 1024;
const MAX_METADATA_BYTES = 1024 * 1024;

class HostedReceiptError extends Error {
  constructor() { super('hosted_receipt_invalid'); }
}

function exactKeys(value, keys) {
  return value && typeof value === 'object' && !Array.isArray(value) &&
    Object.keys(value).sort().join(',') === keys.slice().sort().join(',');
}

function validObject(item, expectedKey, maximum) {
  return exactKeys(item, ['key', 'bytes', 'sha256']) && item.key === expectedKey &&
    Number.isSafeInteger(item.bytes) && item.bytes > 0 && item.bytes <= maximum &&
    typeof item.sha256 === 'string' && HEX.test(item.sha256);
}

function validateReceipt(receipt, maxReceiptBytes) {
  if (!Number.isSafeInteger(maxReceiptBytes) || maxReceiptBytes <= 0 ||
      !exactKeys(receipt, ['version', 'snapshot_id', 'remote_bytes_checked', 'objects']) ||
      receipt.version !== 1 || typeof receipt.snapshot_id !== 'string' ||
      !UUID.test(receipt.snapshot_id) || !Array.isArray(receipt.objects) ||
      receipt.objects.length < 3 || receipt.objects.length > MAX_CHUNKS + 3 ||
      !Number.isSafeInteger(receipt.remote_bytes_checked)) throw new HostedReceiptError();

  const { snapshot_id: snapshotId, objects } = receipt;
  if (!validObject(objects[0], `metadata/${snapshotId}.json`, MAX_METADATA_BYTES) ||
      !validObject(objects[objects.length - 2], `manifests/${snapshotId}.cvmanifest`, MAX_MANIFEST_BYTES) ||
      !validObject(objects[objects.length - 1], `refs/${snapshotId}.json`, MAX_METADATA_BYTES)) {
    throw new HostedReceiptError();
  }

  let previousChunk = '';
  let totalBytes = 0;
  for (let index = 0; index < objects.length; index++) {
    const item = objects[index];
    if (index > 0 && index < objects.length - 2) {
      const match = /^objects\/([0-9a-f]{2})\/([0-9a-f]{62})\.cvchunk$/.exec(item?.key);
      if (!match || match[1] + match[2] <= previousChunk ||
          !validObject(item, item.key, MAX_CHUNK_BYTES)) throw new HostedReceiptError();
      previousChunk = match[1] + match[2];
    }
    totalBytes += item.bytes;
    if (!Number.isSafeInteger(totalBytes) || totalBytes > maxReceiptBytes) throw new HostedReceiptError();
  }
  if (totalBytes !== receipt.remote_bytes_checked) throw new HostedReceiptError();
  return { snapshotId, objects: Object.freeze(objects.map(item => Object.freeze({
    key: item.key, bytes: item.bytes, sha256: item.sha256,
  }))), totalBytes };
}

function storagePrefix(scope) {
  // These IDs must come from the authenticated service's records, never from
  // a client-provided bucket name or prefix. A valid shape alone is not proof
  // that the caller owns either ID.
  if (!exactKeys(scope, ['accountId', 'vaultId']) ||
      !UUID.test(scope.accountId) || !UUID.test(scope.vaultId)) {
    throw new HostedReceiptError();
  }
  return `accounts/${scope.accountId}/vaults/${scope.vaultId}/`;
}

async function verifyStagedReceipt(receipt, maxReceiptBytes, scope, verifyObject) {
  if (typeof verifyObject !== 'function') throw new HostedReceiptError();
  const validated = validateReceipt(receipt, maxReceiptBytes);
  const prefix = storagePrefix(scope);
  for (const item of validated.objects) {
    // The service's verifier must independently establish the stored byte
    // count and SHA-256 within the authenticated account/Vault namespace.
    try {
      if (await verifyObject(Object.freeze({ ...item, key: prefix + item.key })) !== true) {
        throw new HostedReceiptError();
      }
    } catch { throw new HostedReceiptError(); }
  }
  return Object.freeze({ snapshotId: validated.snapshotId,
    objectCount: validated.objects.length, totalBytes: validated.totalBytes });
}

module.exports = { HostedReceiptError, validateReceipt, verifyStagedReceipt };
