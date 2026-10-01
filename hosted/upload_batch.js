// Prepare at most four exact encrypted objects under one short-lived device
// lease. This amortizes client/service round trips without granting a bucket,
// waiving per-object SQL quota checks, or treating a grant as backup proof.
const { consumeAuthorizedScope } = require('./access');
const { validItem, signObjectCapability, grantAgeForScope } =
  require('./object_capability');
const { DECIDE_SQL } = require('./upload_decision');
const { GRANT_SQL } = require('./upload_grant');

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const MAX_ITEMS = 4;

class HostedUploadBatchError extends Error {
  constructor() { super('hosted_upload_batch_denied'); }
}

async function prepareUploadBatch({ scope, reservationId, items, secret,
  query }) {
  if (!consumeAuthorizedScope(scope) || !UUID.test(reservationId) ||
      !Array.isArray(items) || items.length < 1 || items.length > MAX_ITEMS ||
      typeof query !== 'function') throw new HostedUploadBatchError();
  const prefix = `accounts/${scope.accountId}/vaults/${scope.vaultId}/`;
  const seen = new Set();
  for (const item of items) {
    if (!validItem(item) ||
        Object.keys(item).sort().join(',') !== 'bytes,key,sha256' ||
        !item.key.startsWith(prefix) || seen.has(item.key)) {
      throw new HostedUploadBatchError();
    }
    seen.add(item.key);
  }
  const prepared = [];
  try {
    for (const item of items) {
      const params = [scope.accountId, scope.vaultId, reservationId,
        item.key, item.bytes, item.sha256, scope.allowanceBytes];
      const decision = await query(DECIDE_SQL, params);
      if (decision?.rows?.length !== 1) throw new HostedUploadBatchError();
      const state = decision.rows[0].decision;
      if (state !== 'head' && state !== 'put') throw new HostedUploadBatchError();
      if (state === 'put') {
        const grant = await query(GRANT_SQL, params);
        if (grant?.rows?.length !== 1 || grant.rows[0].allowed !== true) {
          throw new HostedUploadBatchError();
        }
      }
      const now = Date.now();
      const age = grantAgeForScope(scope, now);
      const headGrant = await signObjectCapability('HEAD', item, secret,
        now, age);
      prepared.push(Object.freeze(state === 'head' ?
        { action: 'head', grant: headGrant } :
        { action: 'put_required', putGrant: await signObjectCapability(
          'PUT', item, secret, now, age), headGrant }));
    }
    return Object.freeze(prepared);
  } catch { throw new HostedUploadBatchError(); }
}

module.exports = { HostedUploadBatchError, prepareUploadBatch, MAX_ITEMS };
