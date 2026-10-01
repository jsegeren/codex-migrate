// A HEAD probe is permitted only for an exact object already published in this
// Vault or granted for PUT under this active reservation. A newly uploaded
// object can then be independently checked before publication or on retry.
const { consumeAuthorizedScope } = require('./access');
const { validItem, signObjectCapability } = require('./object_capability');

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const REUSE_SQL = `SELECT hosted.can_probe_upload_object_current(
  $1::uuid, $2::uuid, $3::uuid, $4::text, $5::bigint, $6::text, $7::bigint
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
      reservationId, item.key, item.bytes, item.sha256, scope.allowanceBytes]);
    if (result?.rows?.length !== 1 || result.rows[0].allowed !== true) {
      throw new HostedHeadGrantError();
    }
    return await signObjectCapability('HEAD', item, secret, Date.now(), 30_000);
  } catch { throw new HostedHeadGrantError(); }
}

module.exports = { HostedHeadGrantError, issueReuseHead };
