// Server-only, published-snapshot-only read grant. The client selects an item
// from a published receipt, but only database-owned size and digest can be
// signed. This never accepts an upload reservation or staged claim as proof.
const { consumeAuthorizedReadScope } = require('./access');
const { validItem, signObjectCapability } = require('./object_capability');

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const HEX = /^[0-9a-f]{64}$/;
const READ_OBJECT_SQL = `SELECT o.bytes, o.sha256
  FROM hosted.snapshot_objects AS so
  JOIN hosted.objects AS o USING (account_id, vault_id, object_key)
  WHERE so.account_id = $1::uuid AND so.vault_id = $2::uuid
    AND so.snapshot_id = $3::uuid AND so.object_key = $4::text`;

class HostedReadGrantError extends Error {
  constructor() { super('hosted_read_grant_denied'); }
}

async function issuePublishedGet({ scope, snapshotId, relativeKey, secret, query }) {
  if (!consumeAuthorizedReadScope(scope) || !UUID.test(snapshotId) ||
      typeof relativeKey !== 'string' || typeof query !== 'function') {
    throw new HostedReadGrantError();
  }
  const key = `accounts/${scope.accountId}/vaults/${scope.vaultId}/${relativeKey}`;
  if (relativeKey.length > 200 || !validItem({ key, bytes: 1,
    sha256: '0'.repeat(64) })) throw new HostedReadGrantError();
  try {
    const result = await query(READ_OBJECT_SQL, [scope.accountId, scope.vaultId,
      snapshotId, key]);
    const row = result?.rows?.[0];
    if (!/^[1-9][0-9]*$/.test(String(row?.bytes))) throw new HostedReadGrantError();
    const bytes = Number(row.bytes);
    const item = { key, bytes, sha256: row?.sha256 };
    if (result?.rows?.length !== 1 || !Number.isSafeInteger(bytes) ||
        typeof row.sha256 !== 'string' || !HEX.test(row.sha256) ||
        !validItem(item)) throw new HostedReadGrantError();
    return await signObjectCapability('GET', item, secret, Date.now(), 30_000);
  } catch { throw new HostedReadGrantError(); }
}

module.exports = { HostedReadGrantError, issuePublishedGet };
