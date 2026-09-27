// Deliberately undeployed: no Wrangler binding or public route points here.
// Production may use this only after authenticated grant issuance, quota,
// billing, retention, recovery, and clean-Mac acceptance are complete.
import capability from './object_capability.js';
import store from './r2_verified_store.js';

const { decodeSecret, verifyObjectCapability } = capability;
const { putImmutableChecked, checkedHeadState, readVerifiedBody } = store;
const PREFIX = '/v1/object/';
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

export async function handleObjectRequest(request, bucket, secret) {
  const url = new URL(request.url);
  if (!['PUT', 'GET', 'HEAD'].includes(request.method) ||
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
    return handleObjectRequest(request, env.HOSTED_BUCKET, secret);
  },
};
