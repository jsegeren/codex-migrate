// Finalize only the exact staged set whose provider proofs were durably
// checkpointed. The SQL function rechecks completeness and freshness before
// moving last-good; the client never supplies a verification receipt.
const { consumeAuthorizedScope } = require('./access');
const { HostedPublicationStaleError, isStalePublication } =
  require('./publication_conflict');

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const PUBLISH_SQL = `SELECT hosted.publish_checkpointed_staged_current(
  $1::uuid, $2::uuid, $3::uuid, $4::uuid, $5::bigint
) AS published`;
const COUNT_SQL = `SELECT verified_object_count FROM hosted.snapshots
  WHERE account_id = $1::uuid AND vault_id = $2::uuid
    AND reservation_id = $3::uuid AND snapshot_id = $4::uuid`;

class HostedCheckpointedPublicationError extends Error {
  constructor() { super('hosted_checkpointed_publication_failed'); }
}

async function publishCheckpointed({ scope, reservationId, snapshotId, query }) {
  if (!consumeAuthorizedScope(scope) || !UUID.test(reservationId) ||
      !UUID.test(snapshotId) || typeof query !== 'function') {
    throw new HostedCheckpointedPublicationError();
  }
  try {
    const published = await query(PUBLISH_SQL, [scope.accountId, scope.vaultId,
      reservationId, snapshotId, scope.allowanceBytes]);
    if (published?.rows?.length !== 1 ||
        published.rows[0].published !== true) {
      throw new HostedCheckpointedPublicationError();
    }
    const count = await query(COUNT_SQL, [scope.accountId, scope.vaultId,
      reservationId, snapshotId]);
    const verifiedObjectCount = Number(count?.rows?.[0]?.verified_object_count);
    if (count?.rows?.length !== 1 ||
        !Number.isSafeInteger(verifiedObjectCount) ||
        verifiedObjectCount < 3 || verifiedObjectCount > 1_000_000) {
      throw new HostedCheckpointedPublicationError();
    }
    return Object.freeze({ snapshotId, verifiedObjectCount });
  } catch (error) {
    if (isStalePublication(error)) throw new HostedPublicationStaleError();
    throw new HostedCheckpointedPublicationError();
  }
}

module.exports = { HostedCheckpointedPublicationError, publishCheckpointed };
