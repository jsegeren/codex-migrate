// Storage-adjacent primitive for an authenticated R2 Worker. This is not an
// HTTP endpoint: the caller must bind account/Vault ownership, entitlement,
// and aggregate quota before accepting an object or publishing a snapshot.
const { MAX_WORKER_OBJECT_BYTES, VERIFICATION_BATCH_SIZE,
  VERIFICATION_CONCURRENCY } = require('./transport_limits');

const HEX = /^[0-9a-f]{64}$/;
const UUID = '[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}';
const OBJECT_PATH = `(?:metadata/${UUID}\\.json|objects/[0-9a-f]{2}/[0-9a-f]{62}\\.cvchunk|manifests/${UUID}\\.cvmanifest|refs/${UUID}\\.json)`;
const SCOPED_KEY = new RegExp(`^accounts/${UUID}/vaults/${UUID}/${OBJECT_PATH}$`);
// The Free-account Worker inbound limit is 100 MB. Reject larger objects
// rather than accepting a receipt for data this transport cannot upload.

class R2VerificationError extends Error {
  constructor() { super('hosted_object_unverified'); }
}

function validItem(item) {
  return item && typeof item === 'object' && !Array.isArray(item) &&
    typeof item.key === 'string' && SCOPED_KEY.test(item.key) &&
    Number.isSafeInteger(item.bytes) &&
    item.bytes > 0 && item.bytes <= MAX_WORKER_OBJECT_BYTES &&
    typeof item.sha256 === 'string' && HEX.test(item.sha256);
}

function checksumHex(value) {
  let bytes;
  if (value instanceof ArrayBuffer) bytes = new Uint8Array(value);
  else if (ArrayBuffer.isView(value)) {
    bytes = new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  } else return null;
  if (bytes.length !== 32) return null;
  return Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
}

function matches(object, item) {
  return object?.key === item.key && object.size === item.bytes &&
    checksumHex(object.checksums?.sha256) === item.sha256;
}

async function verifiedHead(bucket, item) {
  return (await checkedHeadState(bucket, item)) === 'verified';
}

async function checkedHeadState(bucket, item) {
  if (!validItem(item) || typeof bucket?.head !== 'function') return 'conflict';
  try {
    const object = await bucket.head(item.key);
    if (!object) return 'absent';
    return matches(object, item) ? 'verified' : 'conflict';
  } catch {
    return 'conflict';
  }
}

async function verifiedBatch(bucket, items) {
  if (!Array.isArray(items) || items.length < 1 ||
      items.length > VERIFICATION_BATCH_SIZE || !items.every(validItem)) return false;
  // A large snapshot has thousands of chunks. Bound parallel HEAD requests
  // so verification does not serialize every network round trip or create
  // an unbounded burst within one Worker invocation.
  for (let start = 0; start < items.length; start += VERIFICATION_CONCURRENCY) {
    const wave = items.slice(start, start + VERIFICATION_CONCURRENCY);
    if (!(await Promise.all(wave.map(item => verifiedHead(bucket, item)))).every(Boolean)) {
      return false;
    }
  }
  return true;
}

async function readVerifiedBody(bucket, item) {
  if (!validItem(item) || typeof bucket?.get !== 'function') {
    throw new R2VerificationError();
  }
  try {
    // The caller must have authenticated ownership of this exact scoped key.
    // R2 returns metadata and a stream from the same GET; never buffer the
    // ciphertext in a Worker or return a body whose stored digest is absent.
    // The native client must still hash every received byte before recovery.
    const object = await bucket.get(item.key);
    if (!matches(object, item) || typeof object.body?.getReader !== 'function') {
      throw new R2VerificationError();
    }
    return object.body;
  } catch {
    throw new R2VerificationError();
  }
}

async function putImmutableChecked(bucket, item, body) {
  if (!validItem(item) || !body || typeof bucket?.head !== 'function' ||
      typeof bucket?.put !== 'function') throw new R2VerificationError();
  try {
    const prior = await bucket.head(item.key);
    if (prior) {
      if (!matches(prior, item)) throw new R2VerificationError();
      return 'reused';
    }
    // R2 checks the supplied SHA-256 against the streamed bytes. A
    // conditional PUT prevents a reusable upload request from replacing an
    // immutable chunk or a concurrent writer's version of the same key.
    const written = await bucket.put(item.key, body, {
      sha256: item.sha256,
      onlyIf: new Headers({ 'If-None-Match': '*' }),
    });
    if (written && !matches(written, item)) throw new R2VerificationError();
    // R2 documents strong consistency after put resolves. Check the stored
    // metadata even after a successful write, including the raced-write case.
    const stored = await bucket.head(item.key);
    if (!matches(stored, item) ||
        (written && stored.version !== written.version)) throw new R2VerificationError();
    return written ? 'uploaded' : 'reused';
  } catch {
    throw new R2VerificationError();
  }
}

module.exports = { R2VerificationError, checkedHeadState, verifiedHead, verifiedBatch,
  putImmutableChecked, readVerifiedBody };
