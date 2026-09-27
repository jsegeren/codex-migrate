// Narrow bearer permissions for the R2 transport. Only a trusted service may
// sign these after checking the device, purchase, subscription, Vault ownership,
// and upload reservation (or a published snapshot for reads). A valid token is
// not an entitlement or a published-backup receipt by itself.
const UUID = '[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}';
const OBJECT = `(?:metadata/${UUID}\\.json|objects/[0-9a-f]{2}/[0-9a-f]{62}\\.cvchunk|manifests/${UUID}\\.cvmanifest|refs/${UUID}\\.json)`;
const KEY = new RegExp(`^accounts/${UUID}/vaults/${UUID}/${OBJECT}$`);
const HEX = /^[0-9a-f]{64}$/;
const B64 = /^[A-Za-z0-9_-]+$/;
const MAX_AGE_MS = 60_000;
const MAX_OBJECT_BYTES = 100 * 1000 * 1000;
const MAX_BATCH_BODY_BYTES = 256 * 1024;
const MAX_BATCH_ITEMS = 512;

class ObjectCapabilityError extends Error {
  constructor() { super('hosted_object_access_denied'); }
}

function encode(bytes) {
  return btoa(String.fromCharCode(...new Uint8Array(bytes)))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function decode(text) {
  if (typeof text !== 'string' || !B64.test(text) || text.length > 2048) {
    throw new ObjectCapabilityError();
  }
  try {
    const bytes = Uint8Array.from(atob(text.replace(/-/g, '+').replace(/_/g, '/')
      .padEnd(Math.ceil(text.length / 4) * 4, '=')), character => character.charCodeAt(0));
    if (encode(bytes) !== text) throw new ObjectCapabilityError();
    return bytes;
  } catch { throw new ObjectCapabilityError(); }
}

function decodeSecret(text) {
  const bytes = decode(text);
  if (bytes.length !== 32) throw new ObjectCapabilityError();
  return bytes;
}

function validItem(item) {
  return item && typeof item === 'object' && !Array.isArray(item) &&
    typeof item.key === 'string' && KEY.test(item.key) &&
    Number.isSafeInteger(item.bytes) && item.bytes > 0 &&
    item.bytes <= MAX_OBJECT_BYTES && typeof item.sha256 === 'string' &&
    HEX.test(item.sha256);
}

async function signingKey(secret) {
  if (!(secret instanceof Uint8Array) || secret.byteLength !== 32) {
    throw new ObjectCapabilityError();
  }
  return crypto.subtle.importKey('raw', secret, { name: 'HMAC', hash: 'SHA-256' },
    false, ['sign', 'verify']);
}

async function signObjectCapability(method, item, secret, now = Date.now(), ageMs = MAX_AGE_MS) {
  if (!['PUT', 'GET', 'HEAD', 'DELETE'].includes(method) || !validItem(item) ||
      !Number.isSafeInteger(now) || !Number.isSafeInteger(ageMs) ||
      ageMs < 1 || ageMs > MAX_AGE_MS) throw new ObjectCapabilityError();
  const payload = new TextEncoder().encode(JSON.stringify({ v: 1, m: method,
    k: item.key, b: item.bytes, h: item.sha256, i: now, e: now + ageMs }));
  const signature = await crypto.subtle.sign('HMAC', await signingKey(secret), payload);
  return `${encode(payload)}.${encode(signature)}`;
}

async function verifyObjectCapability(token, method, pathKey, secret, now = Date.now()) {
  if (typeof token !== 'string' || token.length > 2048 ||
      !Number.isSafeInteger(now) || !['PUT', 'GET', 'HEAD', 'DELETE'].includes(method) ||
      typeof pathKey !== 'string' || !KEY.test(pathKey)) throw new ObjectCapabilityError();
  const parts = token.split('.');
  if (parts.length !== 2) throw new ObjectCapabilityError();
  const payload = decode(parts[0]);
  const signature = decode(parts[1]);
  if (signature.length !== 32 || !(await crypto.subtle.verify('HMAC',
    await signingKey(secret), signature, payload))) throw new ObjectCapabilityError();
  let claim;
  try { claim = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(payload)); }
  catch { throw new ObjectCapabilityError(); }
  if (!claim || typeof claim !== 'object' || Array.isArray(claim) ||
      Object.keys(claim).sort().join(',') !== 'b,e,h,i,k,m,v' ||
      claim.v !== 1 || claim.m !== method || claim.k !== pathKey ||
      !validItem({ key: claim.k, bytes: claim.b, sha256: claim.h }) ||
      !Number.isSafeInteger(claim.i) || !Number.isSafeInteger(claim.e) ||
      claim.e - claim.i < 1 || claim.e - claim.i > MAX_AGE_MS ||
      claim.i > now || claim.e <= now) throw new ObjectCapabilityError();
  return Object.freeze({ key: claim.k, bytes: claim.b, sha256: claim.h });
}

function batchBody(items) {
  if (!Array.isArray(items) || items.length < 1 || items.length > MAX_BATCH_ITEMS) {
    throw new ObjectCapabilityError();
  }
  let prefix = null;
  const seen = new Set();
  for (const item of items) {
    if (!validItem(item) || Object.keys(item).sort().join(',') !== 'bytes,key,sha256' ||
        seen.has(item.key)) throw new ObjectCapabilityError();
    const scope = /^accounts\/[0-9a-f-]{36}\/vaults\/[0-9a-f-]{36}\//.exec(item.key)?.[0];
    if (!scope || (prefix !== null && scope !== prefix)) throw new ObjectCapabilityError();
    prefix = scope;
    seen.add(item.key);
  }
  const body = JSON.stringify(items);
  if (new TextEncoder().encode(body).byteLength > MAX_BATCH_BODY_BYTES) {
    throw new ObjectCapabilityError();
  }
  return body;
}

async function bodyDigest(body) {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(body));
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
}

async function signBatchVerification(items, secret, now = Date.now(), ageMs = 30_000) {
  const body = batchBody(items);
  if (!Number.isSafeInteger(now) || !Number.isSafeInteger(ageMs) ||
      ageMs < 1 || ageMs > MAX_AGE_MS) throw new ObjectCapabilityError();
  const payload = new TextEncoder().encode(JSON.stringify({ v: 1, a: 'verify-batch',
    d: await bodyDigest(body), i: now, e: now + ageMs }));
  const signature = await crypto.subtle.sign('HMAC', await signingKey(secret), payload);
  return Object.freeze({ body, token: `${encode(payload)}.${encode(signature)}` });
}

async function verifyBatchVerification(token, body, secret, now = Date.now()) {
  if (typeof token !== 'string' || token.length > 2048 ||
      typeof body !== 'string' || !Number.isSafeInteger(now) ||
      new TextEncoder().encode(body).byteLength > MAX_BATCH_BODY_BYTES) {
    throw new ObjectCapabilityError();
  }
  const parts = token.split('.');
  if (parts.length !== 2) throw new ObjectCapabilityError();
  const payload = decode(parts[0]);
  const signature = decode(parts[1]);
  if (signature.length !== 32 || !(await crypto.subtle.verify('HMAC',
    await signingKey(secret), signature, payload))) throw new ObjectCapabilityError();
  let claim;
  let items;
  try {
    claim = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(payload));
    items = JSON.parse(body);
  } catch { throw new ObjectCapabilityError(); }
  if (!claim || typeof claim !== 'object' || Array.isArray(claim) ||
      Object.keys(claim).sort().join(',') !== 'a,d,e,i,v' ||
      claim.v !== 1 || claim.a !== 'verify-batch' ||
      typeof claim.d !== 'string' || !HEX.test(claim.d) ||
      !Number.isSafeInteger(claim.i) || !Number.isSafeInteger(claim.e) ||
      claim.e - claim.i < 1 || claim.e - claim.i > MAX_AGE_MS ||
      claim.i > now || claim.e <= now ||
      claim.d !== await bodyDigest(body) || batchBody(items) !== body) {
    throw new ObjectCapabilityError();
  }
  return Object.freeze(items.map(item => Object.freeze(item)));
}

module.exports = { ObjectCapabilityError, decodeSecret, validItem,
  signObjectCapability, verifyObjectCapability, signBatchVerification,
  verifyBatchVerification, MAX_BATCH_BODY_BYTES };
