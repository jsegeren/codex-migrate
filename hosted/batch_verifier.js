// Server-side verifier for the exact object batches supplied by the stored
// publication coordinator. The Worker does the provider-backed R2 HEADs;
// neither a client receipt nor an HTTP 200 from an arbitrary origin suffices.
const { signBatchVerification } = require('./object_capability');

class HostedBatchVerificationError extends Error {
  constructor() { super('hosted_batch_verification_failed'); }
}

function createBatchVerifier({ origin, secret, fetchImpl = fetch,
  allowLoopbackHttp = false }) {
  let parsed;
  try { parsed = new URL(origin); }
  catch { throw new HostedBatchVerificationError(); }
  if (parsed.username || parsed.password || parsed.pathname !== '/' ||
      parsed.search || parsed.hash || !parsed.hostname ||
      (parsed.protocol !== 'https:' && !(allowLoopbackHttp &&
        parsed.protocol === 'http:' &&
        ['127.0.0.1', '[::1]'].includes(parsed.hostname))) ||
      typeof fetchImpl !== 'function') throw new HostedBatchVerificationError();
  const endpoint = `${parsed.origin}/v1/verify-batch`;
  return async batch => {
    try {
      const signed = await signBatchVerification(batch, secret);
      const response = await fetchImpl(endpoint, { method: 'POST',
        redirect: 'error', cache: 'no-store',
        headers: { Authorization: `Bearer ${signed.token}`,
          'Content-Type': 'application/json',
          'Content-Length': String(Buffer.byteLength(signed.body)) },
        body: signed.body, signal: AbortSignal.timeout(30_000) });
      if (response.status === 204) return true;
      if (response.status === 409) return false;
    } catch { /* Provider, transport, or signing detail stays server-side. */ }
    throw new HostedBatchVerificationError();
  };
}

module.exports = { HostedBatchVerificationError, createBatchVerifier };
