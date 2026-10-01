// Server-only upload preflight. "put" is not a capability and never implies
// that the object is absent; it means HEAD is not authorized yet. A separate
// fresh scope and durable grant ledger are required before an immutable PUT.
const { consumeAuthorizedScope } = require('./access');
const { validItem, signObjectCapability, grantAgeForScope } =
  require('./object_capability');

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const DECIDE_SQL = `SELECT hosted.classify_upload_object_current(
  $1::uuid, $2::uuid, $3::uuid, $4::text, $5::bigint, $6::text, $7::bigint
) AS decision`;

class HostedUploadDecisionError extends Error {
  constructor() { super('hosted_upload_decision_denied'); }
}

async function decideUploadObject({ scope, reservationId, item, secret, query }) {
  if (!consumeAuthorizedScope(scope) || !UUID.test(reservationId) ||
      !validItem(item) ||
      !item.key.startsWith(`accounts/${scope.accountId}/vaults/${scope.vaultId}/`) ||
      typeof query !== 'function') throw new HostedUploadDecisionError();
  try {
    const result = await query(DECIDE_SQL, [scope.accountId, scope.vaultId,
      reservationId, item.key, item.bytes, item.sha256, scope.allowanceBytes]);
    if (result?.rows?.length !== 1) throw new HostedUploadDecisionError();
    if (result.rows[0].decision === 'put') {
      return Object.freeze({ action: 'put_required' });
    }
    if (result.rows[0].decision !== 'head') throw new HostedUploadDecisionError();
    const now = Date.now();
    const grant = await signObjectCapability('HEAD', item, secret, now,
      grantAgeForScope(scope, now));
    return Object.freeze({ action: 'head', grant });
  } catch { throw new HostedUploadDecisionError(); }
}

module.exports = { HostedUploadDecisionError, decideUploadObject, DECIDE_SQL };
