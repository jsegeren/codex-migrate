// Server-only coordinator. The authenticated caller supplies its own account
// and Vault records, an active reservation, a provider-backed verifier, and a
// database query method. Never accept those authorities from the client body.
const { verifyStagedReceiptBatched } = require('./receipt');
const { consumeAuthorizedScope } = require('./access');
const { HostedPublicationStaleError, isStalePublication } =
  require('./publication_conflict');

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const PUBLISH_SQL = `SELECT hosted.publish_declared_verified_staged_current(
  $1::uuid, $2::uuid, $3::uuid, $4::uuid, $5::jsonb, $6::bigint
) AS published`;

class HostedPublicationError extends Error {
  constructor() { super('hosted_publication_failed'); }
}

async function publishStagedReceipt({ receipt, maxReceiptBytes, scope,
  reservationId, verifyBatch, query }) {
  if (!consumeAuthorizedScope(scope) || !UUID.test(reservationId) ||
      !Number.isSafeInteger(maxReceiptBytes) || maxReceiptBytes <= 0 ||
      maxReceiptBytes > scope.allowanceBytes ||
      typeof query !== 'function') {
    throw new HostedPublicationError();
  }
  // This copies and freezes the client claim before any asynchronous provider
  // check. The database receives only the exact scoped objects verified here.
  const storageScope = Object.freeze({ accountId: scope.accountId, vaultId: scope.vaultId });
  const proof = await verifyStagedReceiptBatched(
    receipt, maxReceiptBytes, storageScope, verifyBatch);
  let result;
  try {
    result = await query(PUBLISH_SQL, [scope.accountId, scope.vaultId,
      reservationId, proof.snapshotId, JSON.stringify(proof.verifiedObjects),
      scope.allowanceBytes]);
  } catch (error) {
    if (isStalePublication(error)) throw new HostedPublicationStaleError();
    // Database errors can contain connection details or tenant metadata.
    // The HTTP layer must never receive those through this coordinator.
    throw new HostedPublicationError();
  }
  if (result?.rows?.[0]?.published !== true) throw new HostedPublicationError();
  return Object.freeze({ snapshotId: proof.snapshotId,
    verifiedObjectCount: proof.objectCount });
}

module.exports = { HostedPublicationError, publishStagedReceipt };
