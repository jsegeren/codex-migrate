// Server-only authorization boundary for hosted Vault operations. A purchase
// download link is not a storage credential. Call this for every operation;
// do not cache its result across requests or accept account IDs from clients.
const { createHash, randomBytes } = require('node:crypto');
const { uploadAllowance } = require('./stripe_entitlement');

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const SESSION_TOKEN = /^hv1_[A-Za-z0-9_-]{43}$/;
const AUTH_SQL = `SELECT account_id, vault_id FROM hosted.device_sessions
  WHERE token_hash = $1 AND vault_id = $2 AND revoked_at IS NULL
    AND expires_at > clock_timestamp()`;
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

function mintSessionSecret() {
  const token = `hv1_${randomBytes(32).toString('base64url')}`;
  return Object.freeze({ token, tokenHash: tokenHash(token) });
}

async function authorizeUploadScope({ sessionToken, vaultId, query,
  getEntitlement, live, priceCatalog }) {
  if (!UUID.test(vaultId) || typeof query !== 'function' ||
      typeof getEntitlement !== 'function') throw new HostedAccessError();
  const hash = tokenHash(sessionToken);
  let accountId;
  try {
    const result = await query(AUTH_SQL, [hash, vaultId]);
    if (result?.rows?.length !== 1 || result.rows[0].vault_id !== vaultId ||
        !UUID.test(result.rows[0].account_id)) throw new HostedAccessError();
    accountId = result.rows[0].account_id;
    // This callback must fetch the enrollment from our account record and the
    // current Subscription directly from Stripe, never a webhook or client.
    const evidence = await getEntitlement(accountId);
    if (evidence?.enrollment?.accountId !== accountId ||
        uploadAllowance(evidence.subscription, evidence.enrollment,
          live, priceCatalog) === null) throw new HostedAccessError();
  } catch {
    // No token, account, Vault, Stripe, or database detail crosses the API.
    throw new HostedAccessError();
  }
  const scope = Object.freeze({ accountId, vaultId });
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

module.exports = { HostedAccessError, mintSessionSecret, authorizeUploadScope,
  isAuthorizedScope, consumeAuthorizedScope };
