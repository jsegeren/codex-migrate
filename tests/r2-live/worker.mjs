// Run only with `wrangler dev` bound to the named sandbox bucket. The endpoint
// deliberately refuses a non-loopback host if this fixture is ever deployed.
import store from '../../hosted/r2_verified_store.js';
import capability from '../../hosted/object_capability.js';
import { handleObjectRequest } from '../../hosted/r2_object_worker.mjs';

const { putImmutableChecked, verifiedHead, readVerifiedBody,
  deleteExactOrAbsent } = store;
const { signObjectCapability } = capability;
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
    wrongDigestRejected: false, restored: false, mismatchDeleteBlocked: false,
    deletedExact: false, repeatDeleteNoop: false, removed: false };
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
    try {
      // The same scoped key with the wrong digest must never be deleted.
      await deleteExactOrAbsent(bucket, { ...item, sha256: wrongItem.sha256 });
    } catch {
      result.mismatchDeleteBlocked = await verifiedHead(bucket, item);
    }
    result.deletedExact = await deleteExactOrAbsent(bucket, item) === 'deleted';
    result.repeatDeleteNoop = await deleteExactOrAbsent(bucket, item) === 'absent';
  } finally {
    // Only this run's random synthetic object is touched. Never scan or clear
    // the bucket, and never use real transcript data in this fixture.
    await bucket.delete([item.key, wrongItem.key]);
    result.removed = await bucket.head(item.key) === null &&
      await bucket.head(wrongItem.key) === null;
  }
  return result;
}

async function proveTransport(bucket) {
  // Exercise the actual capability-protected Worker route against the same
  // synthetic, random, short-lived object. No user data or deployed route.
  const bytes = crypto.getRandomValues(new Uint8Array(64 * 1024));
  const item = itemFor(await digest(bytes), bytes.byteLength);
  const secret = crypto.getRandomValues(new Uint8Array(32));
  let wrongItem = null;
  const result = { uploaded: false, reused: false, checked: false,
    restored: false, wrongMethodBlocked: false, corruptBodyBlocked: false,
    deleted: false, removed: false };
  const call = async (method, token, body) => {
    const headers = { Authorization: `Bearer ${token}` };
    if (body) headers['Content-Length'] = String(body.byteLength);
    return handleObjectRequest(new Request(
      `http://127.0.0.1/v1/object/${item.key}`, {
        method, headers, ...(body ? { body } : {}),
      }), bucket, secret);
  };
  try {
    const put = await signObjectCapability('PUT', item, secret);
    const head = await signObjectCapability('HEAD', item, secret);
    const get = await signObjectCapability('GET', item, secret);
    const remove = await signObjectCapability('DELETE', item, secret);
    result.wrongMethodBlocked = (await call('GET', put)).status === 403;
    result.uploaded = (await call('PUT', put, bytes)).status === 201;
    result.reused = (await call('PUT', put, bytes)).status === 200;
    result.checked = (await call('HEAD', head)).status === 200;
    // Existing immutable objects may return 'reused' without consuming the
    // request body. Check corruption on an absent key instead.
    const altered = bytes.slice();
    altered[0] ^= 1;
    wrongItem = itemFor(await digest(altered), altered.byteLength);
    const wrongPut = await signObjectCapability('PUT', wrongItem, secret);
    const wrongRequest = new Request(
      `http://127.0.0.1/v1/object/${wrongItem.key}`, {
        method: 'PUT', headers: { Authorization: `Bearer ${wrongPut}`,
          'Content-Length': String(bytes.byteLength) }, body: bytes,
      });
    result.corruptBodyBlocked = (await handleObjectRequest(
      wrongRequest, bucket, secret)).status === 409 &&
      (await bucket.head(wrongItem.key)) === null;
    const response = await call('GET', get);
    const restored = new Uint8Array(await response.arrayBuffer());
    result.restored = response.status === 200 &&
      restored.byteLength === bytes.byteLength &&
      await digest(restored) === item.sha256;
    result.deleted = (await call('DELETE', remove)).status === 204;
  } finally {
    await bucket.delete(wrongItem ? [item.key, wrongItem.key] : [item.key]);
    result.removed = await bucket.head(item.key) === null &&
      (!wrongItem || await bucket.head(wrongItem.key) === null);
  }
  return result;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    // The Wrangler config does not set this variable. An accidental deploy is
    // inert; only a deliberate local dev invocation may enable the probe.
    if (env.PROBE_ENABLED !== '1' ||
        !['localhost', '127.0.0.1'].includes(url.hostname) ||
        request.method !== 'POST' ||
        !['/probe', '/probe-transport'].includes(url.pathname)) {
      return new Response('not found', { status: 404 });
    }
    try {
      const result = url.pathname === '/probe-transport' ?
        await proveTransport(env.SANDBOX_BUCKET) : await prove(env.SANDBOX_BUCKET);
      return Response.json(result, {
        status: Object.values(result).every(Boolean) ? 200 : 500,
      });
    } catch {
      return Response.json({ error: 'r2_sandbox_proof_failed' }, { status: 500 });
    }
  },
};
