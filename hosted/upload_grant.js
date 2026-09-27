// Server-only authorization of one immutable PUT. A caller must first mint a
// fresh scope from the device, purchase, and live subscription checks. SQL
// records each distinct object under an active byte reservation before this
// function returns a short-lived storage token. Not an HTTP endpoint.
const { consumeAuthorizedScope } = require('./access');
const { validItem, signObjectCapability } = require('./object_capability');

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const GRANT_SQL = `SELECT hosted.reserve_object_grant_current(
  $1::uuid, $2::uuid, $3::uuid, $4::text, $5::bigint, $6::text, $7::bigint
) AS allowed`;

class HostedUploadGrantError extends Error {
  constructor() { super('hosted_upload_grant_denied'); }
}

async function issuePutCapability({ scope, reservationId, item, secret, query }) {
  if (!consumeAuthorizedScope(scope) || !UUID.test(reservationId) ||
      !validItem(item) ||
      !item.key.startsWith(`accounts/${scope.accountId}/vaults/${scope.vaultId}/`) ||
      typeof query !== 'function') throw new HostedUploadGrantError();
  try {
    const result = await query(GRANT_SQL, [scope.accountId, scope.vaultId,
      reservationId, item.key, item.bytes, item.sha256, scope.allowanceBytes]);
    if (result?.rows?.length !== 1 || result.rows[0].allowed !== true) {
      throw new HostedUploadGrantError();
    }
    return await signObjectCapability('PUT', item, secret, Date.now(), 30_000);
  } catch {
    // Do not expose tenant IDs, the reservation, Stripe state, SQL, or the
    // storage signing key through the API error boundary.
    throw new HostedUploadGrantError();
  }
}

module.exports = { HostedUploadGrantError, issuePutCapability };
