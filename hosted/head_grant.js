// A HEAD reuse probe is permitted only for an object already recorded in a
// published snapshot, under a fresh upload entitlement and active reservation.
// Missing or unrecorded objects go through the reserved PUT path instead.
const { consumeAuthorizedScope } = require('./access');
const { validItem, signObjectCapability } = require('./object_capability');

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const REUSE_SQL = `SELECT EXISTS (
  SELECT 1 FROM hosted.upload_reservations AS r
  JOIN hosted.snapshot_objects AS so
    ON so.account_id = r.account_id AND so.vault_id = r.vault_id
  JOIN hosted.objects AS o
    ON o.account_id = so.account_id AND o.vault_id = so.vault_id
      AND o.object_key = so.object_key
  WHERE r.account_id = $1::uuid AND r.vault_id = $2::uuid
    AND r.reservation_id = $3::uuid AND r.state = 'active'
    AND r.expires_at > clock_timestamp() + interval '1 minute'
    AND o.object_key = $4::text AND o.bytes = $5::bigint
    AND o.sha256 = $6::text
) AS allowed`;

class HostedHeadGrantError extends Error {
  constructor() { super('hosted_head_grant_denied'); }
}

async function issueReuseHead({ scope, reservationId, item, secret, query }) {
  if (!consumeAuthorizedScope(scope) || !UUID.test(reservationId) ||
      !validItem(item) ||
      !item.key.startsWith(`accounts/${scope.accountId}/vaults/${scope.vaultId}/`) ||
      typeof query !== 'function') throw new HostedHeadGrantError();
  try {
    const result = await query(REUSE_SQL, [scope.accountId, scope.vaultId,
      reservationId, item.key, item.bytes, item.sha256]);
    if (result?.rows?.length !== 1 || result.rows[0].allowed !== true) {
      throw new HostedHeadGrantError();
    }
    return await signObjectCapability('HEAD', item, secret, Date.now(), 30_000);
  } catch { throw new HostedHeadGrantError(); }
}

module.exports = { HostedHeadGrantError, issueReuseHead };
