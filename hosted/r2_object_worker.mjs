// Deliberately undeployed: no Wrangler binding or public route points here.
// Production may use this only after authenticated grant issuance, quota,
// billing, retention, recovery, and clean-Mac acceptance are complete.
import capability from './object_capability.js';
import store from './r2_verified_store.js';

const { decodeSecret, verifyObjectCapability, verifyBatchVerification,
  MAX_BATCH_BODY_BYTES } = capability;
const { putImmutableChecked, checkedHeadState, readVerifiedBody,
  verifiedBatch, deleteExactOrAbsent } = store;
const PREFIX = '/v1/object/';
const BATCH_PATH = '/v1/verify-batch';
const BASE_HEADERS = Object.freeze({ 'Cache-Control': 'private, no-store',
  'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff' });

function answer(status, body = null) {
  return new Response(body, { status, headers: BASE_HEADERS });
}

function boundedBody(stream, expectedBytes) {
  if (typeof FixedLengthStream === 'function') {
    // R2 requires a stream with a known length. Cloudflare's fixed-length
    // stream also errors on short or excessive bodies without buffering a
    // potentially large encrypted object in Worker memory.
    const fixed = new FixedLengthStream(expectedBytes);
    const abort = new AbortController();
    const completion = stream.pipeTo(fixed.writable, { signal: abort.signal });
    void completion.catch(() => {});
    return { body: fixed.readable, completion, stop: () => abort.abort() };
  }
  // Node's unit-test runtime lacks FixedLengthStream. Its fake R2 consumes
  // ordinary Streams; the real Worker path above is exercised separately.
  let count = 0;
  return { body: stream.pipeThrough(new TransformStream({
    transform(chunk, controller) {
      if (!(chunk instanceof Uint8Array) ||
          count + chunk.byteLength > expectedBytes) throw Error('invalid_body');
      count += chunk.byteLength;
      controller.enqueue(chunk);
    },
    flush() { if (count !== expectedBytes) throw Error('invalid_body'); },
  })), completion: null, stop: () => {} };
}

async function boundedJson(stream, limit) {
  if (!stream || typeof stream.getReader !== 'function') throw Error('invalid_body');
  const reader = stream.getReader();
  const blocks = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (!(value instanceof Uint8Array) || total + value.byteLength > limit) {
        throw Error('invalid_body');
      }
      blocks.push(value);
      total += value.byteLength;
    }
    if (total === 0) throw Error('invalid_body');
    const bytes = new Uint8Array(total);
    let offset = 0;
    for (const block of blocks) { bytes.set(block, offset); offset += block.byteLength; }
    return new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  } finally { void reader.cancel().catch(() => {}); }
}

export async function handleBatchVerification(request, bucket, secret) {
  const url = new URL(request.url);
  if (request.method !== 'POST' || url.pathname !== BATCH_PATH ||
      url.search || url.hash) return answer(404);
  const length = Number(request.headers.get('Content-Length'));
  if (!Number.isSafeInteger(length) || length < 1 ||
      length > MAX_BATCH_BODY_BYTES ||
      request.headers.get('Content-Type') !== 'application/json') return answer(400);
  const match = /^Bearer ([A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)$/.exec(
    request.headers.get('Authorization') || '');
  if (!match) return answer(403);
  let items;
  try {
    const body = await boundedJson(request.body, MAX_BATCH_BODY_BYTES);
    if (new TextEncoder().encode(body).byteLength !== length) return answer(400);
    items = await verifyBatchVerification(match[1], body, secret);
  } catch { return answer(403); }
  return answer(await verifiedBatch(bucket, items) ? 204 : 409);
}

export async function handleObjectRequest(request, bucket, secret) {
  const url = new URL(request.url);
  if (!['PUT', 'GET', 'HEAD', 'DELETE'].includes(request.method) ||
      !url.pathname.startsWith(PREFIX) || url.search || url.hash) return answer(404);
  const key = url.pathname.slice(PREFIX.length);
  const authorization = request.headers.get('Authorization') || '';
  const match = /^Bearer ([A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)$/.exec(authorization);
  if (!match) return answer(403);
  let item;
  try { item = await verifyObjectCapability(match[1], request.method, key, secret); }
  catch { return answer(403); }
  if (request.method === 'HEAD') {
    // A retrying client must distinguish an absent object from an immutable
    // object with conflicting bytes. Never allow a conflict to become a PUT.
    const state = await checkedHeadState(bucket, item);
    return answer(state === 'verified' ? 200 : state === 'absent' ? 404 : 409);
  }
  if (request.method === 'GET') {
    try {
      const body = await readVerifiedBody(bucket, item);
      return new Response(body, { status: 200, headers: { ...BASE_HEADERS,
        'Content-Type': 'application/octet-stream',
        'Content-Length': String(item.bytes) } });
    } catch { return answer(409); }
  }
  if (request.method === 'DELETE') {
    if (![null, '0'].includes(request.headers.get('Content-Length'))) return answer(400);
    // urllib sends Content-Length: 0 with an empty stream. Workerd exposes
    // that stream as non-null even though no bytes were sent. Accept only a
    // stream that ends immediately; never ignore a non-empty DELETE body.
    if (request.body) {
      try {
        const reader = request.body.getReader();
        let ended = false;
        // Fetch may yield an empty chunk before the end of a zero-length
        // stream. Bound the reads and reject any actual byte.
        for (let index = 0; index < 8; index++) {
          const part = await reader.read();
          if (part.done) { ended = true; break; }
          if (!(part.value instanceof Uint8Array) || part.value.byteLength !== 0) break;
        }
        void reader.cancel().catch(() => {});
        if (!ended) return answer(400);
      } catch { return answer(400); }
    }
    try {
      await deleteExactOrAbsent(bucket, item);
      return answer(204);
    } catch { return answer(409); }
  }
  if (request.headers.get('Content-Length') !== String(item.bytes) || !request.body) {
    return answer(400);
  }
  const bounded = boundedBody(request.body, item.bytes);
  try {
    const state = await putImmutableChecked(bucket, item,
      bounded.body);
    if (state === 'reused') bounded.stop();
    else if (bounded.completion) await bounded.completion;
    return answer(state === 'uploaded' ? 201 : 200);
  } catch { bounded.stop(); return answer(409); }
}

export default {
  async fetch(request, env) {
    // No fallback, public probing, or accidental activation without both
    // explicit secret and bucket binding.
    if (!env.HOSTED_BUCKET || !env.CAPABILITY_SIGNING_KEY) return answer(404);
    let secret;
    try { secret = decodeSecret(env.CAPABILITY_SIGNING_KEY); }
    catch { return answer(404); }
    if (new URL(request.url).pathname === BATCH_PATH) {
      return handleBatchVerification(request, env.HOSTED_BUCKET, secret);
    }
    return handleObjectRequest(request, env.HOSTED_BUCKET, secret);
  },
};
