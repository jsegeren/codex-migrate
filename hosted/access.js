// Server-only authorization boundary for hosted Vault operations. A purchase
// download link is not a storage credential. A full purchase/subscription check
// mints a one-minute upload lease; each object still checks the active
// device session and its exact reservation. Never accept client account IDs.
const { createHash } = require('node:crypto');
const { uploadAllowance } = require('./stripe_entitlement');
const { verifyUploadLease } = require('./upload_lease');
const { businessDeviceTokenHash } = require('./business_worker');

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
const authorizedReadScopes = new WeakMap();
const READ_SQL = `SELECT account_id, vault_id FROM hosted.device_sessions
  WHERE token_hash = $1 AND vault_id = $2 AND revoked_at IS NULL
    AND expires_at > clock_timestamp()`;
const BUSINESS_DEVICE_SQL = `SELECT d.account_id, d.vault_id
  FROM hosted.business_device_sessions AS d
  JOIN hosted.business_seats AS s
    ON s.account_id = d.account_id AND s.seat_id = d.seat_id
  JOIN hosted.business_seat_vaults AS v
    ON v.account_id = d.account_id AND v.seat_id = d.seat_id
      AND v.vault_id = d.vault_id
  WHERE d.token_hash = $1 AND d.vault_id = $2
    AND d.revoked_at IS NULL AND d.expires_at > clock_timestamp()
    AND s.revoked_at IS NULL`;
const BUSINESS_ABANDON_SQL = BUSINESS_DEVICE_SQL +
  " AND d.access_purpose = 'worker'";
const BUSINESS_UPLOAD_SQL = `SELECT d.account_id, d.vault_id,
    e.allowance_bytes
  FROM hosted.business_device_sessions AS d
  JOIN hosted.business_seats AS s
    ON s.account_id = d.account_id AND s.seat_id = d.seat_id
  JOIN hosted.business_seat_vaults AS v
    ON v.account_id = d.account_id AND v.seat_id = d.seat_id
      AND v.vault_id = d.vault_id
  JOIN hosted.business_backup_entitlements AS e
    ON e.account_id = d.account_id
  WHERE d.token_hash = $1 AND d.vault_id = $2
    AND d.revoked_at IS NULL AND d.expires_at > clock_timestamp()
    AND d.access_purpose = 'worker'
    AND s.revoked_at IS NULL AND e.revoked_at IS NULL
    AND e.starts_at <= clock_timestamp()
    AND e.expires_at > clock_timestamp()`;

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

function businessTokenHash(token) {
  try { return businessDeviceTokenHash(token); }
  catch { throw new HostedAccessError(); }
}

async function businessDeviceRow({ sessionToken, vaultId, query, upload,
  abandon }) {
  if (!UUID.test(vaultId) || typeof query !== 'function') {
    throw new HostedAccessError();
  }
  try {
    const result = await query(upload ? BUSINESS_UPLOAD_SQL :
      abandon ? BUSINESS_ABANDON_SQL : BUSINESS_DEVICE_SQL,
      [businessTokenHash(sessionToken), vaultId]);
    const row = result?.rows?.[0];
    if (result?.rows?.length !== 1 || row?.vault_id !== vaultId ||
        !UUID.test(row?.account_id)) throw new HostedAccessError();
    if (upload) {
      const allowanceBytes = Number(row.allowance_bytes);
      if (!Number.isSafeInteger(allowanceBytes) || allowanceBytes < 1 ||
          allowanceBytes > 1_000_000_000_000) throw new HostedAccessError();
      return { accountId: row.account_id, vaultId, allowanceBytes };
    }
    return { accountId: row.account_id, vaultId };
  } catch { throw new HostedAccessError(); }
}

// Dark business pilot only. Pairing proves device ownership, but this scope
// additionally requires a current, operator-approved storage allowance.
// No public route calls it until billing, privacy, and recovery gates pass.
async function authorizeBusinessUploadScope({ sessionToken, vaultId, query }) {
  const values = await businessDeviceRow({ sessionToken, vaultId, query,
    upload: true });
  const scope = Object.freeze(values);
  authorizedScopes.set(scope, Date.now());
  return scope;
}

async function authorizeBusinessReadScope({ sessionToken, vaultId, query }) {
  const values = await businessDeviceRow({ sessionToken, vaultId, query,
    upload: false });
  const scope = Object.freeze(values);
  authorizedReadScopes.set(scope, Date.now());
  return scope;
}

async function authorizeBusinessAbandonScope({ sessionToken, vaultId, query }) {
  const values = await businessDeviceRow({ sessionToken, vaultId, query,
    abandon: true });
  const scope = Object.freeze(values);
  authorizedReadScopes.set(scope, Date.now());
  return scope;
}

async function authorizeBusinessLeasedUploadScope({ sessionToken, vaultId,
  reservationId, lease, secret, query }) {
  if (!UUID.test(reservationId)) throw new HostedAccessError();
  try {
    const digest = businessTokenHash(sessionToken);
    const claim = verifyUploadLease(lease, secret);
    if (claim.deviceHash !== digest || claim.vaultId !== vaultId ||
        claim.reservationId !== reservationId) throw new HostedAccessError();
    const values = await businessDeviceRow({ sessionToken, vaultId, query,
      upload: true });
    if (values.accountId !== claim.accountId ||
        values.allowanceBytes < claim.allowanceBytes) {
      throw new HostedAccessError();
    }
    const scope = Object.freeze({ ...values,
      allowanceBytes: claim.allowanceBytes,
      leaseExpiresAt: claim.expiresAt });
    authorizedScopes.set(scope, Date.now());
    return scope;
  } catch { throw new HostedAccessError(); }
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

async function authorizeReadScope({ sessionToken, vaultId, query }) {
  if (!UUID.test(vaultId) || typeof query !== 'function') throw new HostedAccessError();
  const hash = tokenHash(sessionToken);
  let row;
  try {
    const result = await query(READ_SQL, [hash, vaultId]);
    row = result?.rows?.[0];
    if (result?.rows?.length !== 1 || row.vault_id !== vaultId ||
        !UUID.test(row.account_id)) throw new HostedAccessError();
  } catch { throw new HostedAccessError(); }
  // Reading an already published snapshot never reserves storage. If the
  // subscription has lapsed but data remains in retention, let its owner
  // recover/export it; retention duration is a separate launch policy.
  const scope = Object.freeze({ accountId: row.account_id, vaultId });
  authorizedReadScopes.set(scope, Date.now());
  return scope;
}

async function authorizeLeasedUploadScope({ sessionToken, vaultId,
  reservationId, lease, secret, query }) {
  if (!UUID.test(vaultId) || !UUID.test(reservationId) ||
      typeof query !== 'function') throw new HostedAccessError();
  try {
    const digest = tokenHash(sessionToken);
    const claim = verifyUploadLease(lease, secret);
    if (claim.deviceHash !== digest || claim.vaultId !== vaultId ||
        claim.reservationId !== reservationId) throw new HostedAccessError();
    const result = await query(READ_SQL, [digest, vaultId]);
    const row = result?.rows?.[0];
    if (result?.rows?.length !== 1 || row.vault_id !== vaultId ||
        row.account_id !== claim.accountId) throw new HostedAccessError();
    const scope = Object.freeze({ accountId: claim.accountId, vaultId,
      allowanceBytes: claim.allowanceBytes,
      leaseExpiresAt: claim.expiresAt });
    authorizedScopes.set(scope, Date.now());
    return scope;
  } catch { throw new HostedAccessError(); }
}

function isAuthorizedReadScope(scope) {
  const issuedAt = scope !== null && typeof scope === 'object' &&
    authorizedReadScopes.get(scope);
  const age = Date.now() - issuedAt;
  return Number.isSafeInteger(issuedAt) && age >= 0 && age <= MAX_SCOPE_AGE_MS;
}

function consumeAuthorizedReadScope(scope) {
  const valid = isAuthorizedReadScope(scope);
  if (scope !== null && typeof scope === 'object') authorizedReadScopes.delete(scope);
  return valid;
}

module.exports = { HostedAccessError, authorizeUploadScope,
  isAuthorizedScope, consumeAuthorizedScope, authorizeLeasedUploadScope,
  authorizeReadScope,
  isAuthorizedReadScope, consumeAuthorizedReadScope, tokenHash,
  authorizeBusinessUploadScope, authorizeBusinessReadScope,
  authorizeBusinessAbandonScope,
  authorizeBusinessLeasedUploadScope, businessTokenHash };
