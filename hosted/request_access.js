// Keep individual purchase authority and dark business-pilot authority
// separate at every HTTP entry point. The business lane is sandbox-only and
// closed unless explicitly enabled; it never inherits an employee purchase.
const { authorizeUploadScope, authorizeLeasedUploadScope,
  authorizeReadScope, authorizeBusinessUploadScope,
  authorizeBusinessLeasedUploadScope, authorizeBusinessReadScope,
  tokenHash, businessTokenHash, HostedAccessError } = require('./access');

const INDIVIDUAL = /^Bearer (hv1_[A-Za-z0-9_-]{43})$/;
const BUSINESS = /^Bearer (hvb1_[A-Za-z0-9_-]{43})$/;
const issuedCredentials = new WeakSet();

function mintCredential(kind, token) {
  const credential = Object.freeze({ kind, token });
  issuedCredentials.add(credential);
  return credential;
}

function deviceCredential(header, env) {
  if (typeof header !== 'string' || !env || typeof env !== 'object') return null;
  const individual = INDIVIDUAL.exec(header)?.[1];
  if (individual) return mintCredential('individual', individual);
  const business = BUSINESS.exec(header)?.[1];
  if (business && env.HOSTED_MODE === 'sandbox' &&
      env.HOSTED_BUSINESS_BACKUP_SANDBOX_OPEN === 'yes') {
    return mintCredential('business', business);
  }
  return null;
}

function requireCredential(credential) {
  if (!credential || typeof credential !== 'object' ||
      !issuedCredentials.has(credential) ||
      !['individual', 'business'].includes(credential.kind) ||
      typeof credential.token !== 'string') throw new HostedAccessError();
}

function deviceHash(credential) {
  requireCredential(credential);
  return credential.kind === 'business' ?
    businessTokenHash(credential.token) : tokenHash(credential.token);
}

function authorizeWrite({ credential, vaultId, query, getEntitlement,
  verifyPurchase, live, priceCatalog }) {
  requireCredential(credential);
  if (credential.kind === 'business') {
    return authorizeBusinessUploadScope({ sessionToken: credential.token,
      vaultId, query });
  }
  return authorizeUploadScope({ sessionToken: credential.token,
    vaultId, query, getEntitlement, verifyPurchase, live, priceCatalog });
}

function authorizeRead({ credential, vaultId, query }) {
  requireCredential(credential);
  return credential.kind === 'business' ?
    authorizeBusinessReadScope({ sessionToken: credential.token,
      vaultId, query }) :
    authorizeReadScope({ sessionToken: credential.token, vaultId, query });
}

function authorizeLeasedWrite({ credential, vaultId, reservationId,
  lease, secret, query }) {
  requireCredential(credential);
  return credential.kind === 'business' ?
    authorizeBusinessLeasedUploadScope({ sessionToken: credential.token,
      vaultId, reservationId, lease, secret, query }) :
    authorizeLeasedUploadScope({ sessionToken: credential.token,
      vaultId, reservationId, lease, secret, query });
}

module.exports = { deviceCredential, deviceHash, authorizeWrite,
  authorizeRead, authorizeLeasedWrite };
