// Run only with `wrangler dev` bound to the named sandbox bucket. The endpoint
// deliberately refuses a non-loopback host if this fixture is ever deployed.
import store from '../../hosted/r2_verified_store.js';

const { putImmutableChecked, verifiedHead, readVerifiedBody } = store;
const ACCOUNT = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const VAULT = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';

function hex(bytes) {
  return Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
}

async function digest(bytes) {
  return hex(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)));
}

function itemFor(hash, length) {
  return {
    key: `accounts/${ACCOUNT}/vaults/${VAULT}/objects/${hash.slice(0, 2)}/${hash.slice(2)}.cvchunk`,
    bytes: length,
    sha256: hash,
  };
}

async function prove(bucket) {
  const bytes = crypto.getRandomValues(new Uint8Array(64 * 1024));
  const hash = await digest(bytes);
  const item = itemFor(hash, bytes.byteLength);
  const altered = bytes.slice();
  altered[0] ^= 1;
  const wrongItem = itemFor(await digest(altered), bytes.byteLength);
  const result = { uploaded: false, checked: false, reused: false,
    wrongDigestRejected: false, restored: false, removed: false };
  try {
    result.uploaded = await putImmutableChecked(bucket, item, bytes) === 'uploaded';
    result.checked = await verifiedHead(bucket, item);
    result.reused = await putImmutableChecked(bucket, item, bytes) === 'reused';
    try {
      // This key is absent, so rejection must come from R2 checking the
      // supplied SHA-256 against the uploaded body, not from a prior HEAD.
      await putImmutableChecked(bucket, wrongItem, bytes);
    } catch {
      result.wrongDigestRejected = await bucket.head(wrongItem.key) === null;
    }
    const body = await readVerifiedBody(bucket, item);
    const readBytes = new Uint8Array(await new Response(body).arrayBuffer());
    result.restored = readBytes.byteLength === bytes.byteLength &&
      await digest(readBytes) === hash;
  } finally {
    // Only this run's random synthetic object is touched. Never scan or clear
    // the bucket, and never use real transcript data in this fixture.
    await bucket.delete([item.key, wrongItem.key]);
    result.removed = await bucket.head(item.key) === null &&
      await bucket.head(wrongItem.key) === null;
  }
  return result;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (!['localhost', '127.0.0.1'].includes(url.hostname) ||
        request.method !== 'POST' || url.pathname !== '/probe') {
      return new Response('not found', { status: 404 });
    }
    try {
      const result = await prove(env.SANDBOX_BUCKET);
      return Response.json(result, {
        status: Object.values(result).every(Boolean) ? 200 : 500,
      });
    } catch {
      return Response.json({ error: 'r2_sandbox_proof_failed' }, { status: 500 });
    }
  },
};
