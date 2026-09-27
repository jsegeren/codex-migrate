// Server-only coordinator. The authenticated caller supplies its own account
// and Vault records, an active reservation, a provider-backed verifier, and a
// database query method. Never accept those authorities from the client body.
const { verifyStagedReceipt } = require('./receipt');

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const PUBLISH_SQL = `SELECT hosted.publish_verified_snapshot(
  $1::uuid, $2::uuid, $3::uuid, $4::uuid, $5::jsonb
) AS published`;

class HostedPublicationError extends Error {
  constructor() { super('hosted_publication_failed'); }
}

async function publishStagedReceipt({ receipt, maxReceiptBytes, scope,
  reservationId, verifyObject, query }) {
  if (!UUID.test(reservationId) || typeof query !== 'function') {
    throw new HostedPublicationError();
  }
  // This copies and freezes the client claim before any asynchronous provider
  // check. The database receives only the exact scoped objects verified here.
  const proof = await verifyStagedReceipt(receipt, maxReceiptBytes, scope, verifyObject);
  const result = await query(PUBLISH_SQL, [scope.accountId, scope.vaultId,
    reservationId, proof.snapshotId, JSON.stringify(proof.verifiedObjects)]);
  if (result?.rows?.[0]?.published !== true) throw new HostedPublicationError();
  return Object.freeze({ snapshotId: proof.snapshotId,
    verifiedObjectCount: proof.objectCount });
}

module.exports = { HostedPublicationError, publishStagedReceipt };
