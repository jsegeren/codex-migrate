// Server-only authorization boundary for hosted Vault operations. A purchase
// download link is not a storage credential. Call this for every operation;
// do not cache its result across requests or accept account IDs from clients.
const { createHash } = require('node:crypto');
const { uploadAllowance } = require('./stripe_entitlement');

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const SESSION_TOKEN = /^hv1_[A-Za-z0-9_-]{43}$/;
const AUTH_SQL = `SELECT sessions.account_id, sessions.vault_id,
    purchases.purchase_session_id, purchases.purchase_mode
  FROM hosted.device_sessions AS sessions
  JOIN hosted.purchase_enrollments AS purchases
    ON purchases.account_id = sessions.account_id
  WHERE sessions.token_hash = $1 AND sessions.vault_id = $2
    AND sessions.revoked_at IS NULL
    AND sessions.expires_at > clock_timestamp()`;
const MAX_SCOPE_AGE_MS = 60_000;
const authorizedScopes = new WeakMap();

class HostedAccessError extends Error {
  constructor() { super('hosted_access_denied'); }
}

function tokenHash(token) {
  if (typeof token !== 'string' || !SESSION_TOKEN.test(token)) {
    throw new HostedAccessError();
  }
  return createHash('sha256').update('codex-vault-hosted-session-v1\0').update(token)
    .digest('hex');
}

async function authorizeUploadScope({ sessionToken, vaultId, query,
  getEntitlement, verifyPurchase, live, priceCatalog }) {
  if (!UUID.test(vaultId) || typeof query !== 'function' ||
      typeof getEntitlement !== 'function' ||
      typeof verifyPurchase !== 'function') throw new HostedAccessError();
  const hash = tokenHash(sessionToken);
  let accountId;
  let allowanceBytes;
  try {
    const result = await query(AUTH_SQL, [hash, vaultId]);
    const row = result?.rows?.[0];
    if (result?.rows?.length !== 1 || row.vault_id !== vaultId ||
        !UUID.test(row.account_id)) throw new HostedAccessError();
    accountId = row.account_id;
    // The one-time app purchase remains required after enrollment. Recheck
    // Stripe's current refund/dispute state; a stored commerce row is only
    // historical evidence, and neither the device nor the caller chooses it.
    const purchase = await verifyPurchase(row.purchase_session_id,
      row.purchase_mode);
    if (purchase?.sessionId !== row.purchase_session_id ||
        purchase?.mode !== row.purchase_mode ||
        row.purchase_mode !== (live ? 'live' : 'sandbox')) {
      throw new HostedAccessError();
    }
    // This callback must fetch the enrollment from our account record and the
    // current Subscription directly from Stripe, never a webhook or client.
    const evidence = await getEntitlement(accountId);
    allowanceBytes = uploadAllowance(evidence?.subscription,
      evidence?.enrollment, live, priceCatalog);
    if (evidence?.enrollment?.accountId !== accountId ||
        allowanceBytes === null) throw new HostedAccessError();
  } catch {
    // No token, account, Vault, Stripe, or database detail crosses the API.
    throw new HostedAccessError();
  }
  const scope = Object.freeze({ accountId, vaultId, allowanceBytes });
  authorizedScopes.set(scope, Date.now());
  return scope;
}

function isAuthorizedScope(scope) {
  const issuedAt = scope !== null && typeof scope === 'object' &&
    authorizedScopes.get(scope);
  const age = Date.now() - issuedAt;
  return Number.isSafeInteger(issuedAt) && age >= 0 && age <= MAX_SCOPE_AGE_MS;
}

function consumeAuthorizedScope(scope) {
  const valid = isAuthorizedScope(scope);
  if (scope !== null && typeof scope === 'object') authorizedScopes.delete(scope);
  return valid;
}

module.exports = { HostedAccessError, authorizeUploadScope,
  isAuthorizedScope, consumeAuthorizedScope, tokenHash };
