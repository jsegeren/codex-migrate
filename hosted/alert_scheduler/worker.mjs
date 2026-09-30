// Dedicated sandbox scheduler. It has no R2 binding, database credential,
// customer content, or public HTTP API. Deploy only after the operator has
// configured a scoped endpoint secret and verified the alert delivery drill.
const ENDPOINT = 'https://codexbackup.segeren.com/api/hosted-business-alert-scan';

export async function scanOnce(env, request = fetch) {
  if (env?.SCAN_ENABLED !== 'yes') return 'disabled';
  if (typeof env.ALERT_SCAN_SECRET !== 'string' ||
      env.ALERT_SCAN_SECRET.length < 32 ||
      !/^[A-Za-z0-9_-]+$/.test(env.ALERT_SCAN_SECRET)) {
    throw Error('alert_scan_unconfigured');
  }
  let response;
  try {
    response = await request(ENDPOINT, { method: 'GET', redirect: 'error',
      headers: { Authorization: `Bearer ${env.ALERT_SCAN_SECRET}` },
      signal: AbortSignal.timeout(20000) });
  } catch { throw Error('alert_scan_unavailable'); }
  if (response.status !== 200) throw Error('alert_scan_unavailable');
  let result;
  try { result = await response.json(); }
  catch { throw Error('alert_scan_invalid_result'); }
  if (!result || !['claimed', 'accepted', 'rejected', 'uncertain',
    'operatorReview'].every(key => Number.isSafeInteger(result[key]) &&
      result[key] >= 0) ||
      result.claimed !== result.accepted + result.rejected +
        result.uncertain) {
    throw Error('alert_scan_invalid_result');
  }
  // Cloudflare's scheduled invocation must fail visibly if delivery needs
  // operator reconciliation; never include contacts or seat IDs in logs.
  if (result.operatorReview > 0) throw Error('alert_delivery_needs_review');
  return 'ok';
}

export default {
  async fetch() { return new Response(null, { status: 404 }); },
  async scheduled(_controller, env) { await scanOnce(env); },
};
