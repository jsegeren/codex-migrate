import test from 'node:test';
import assert from 'node:assert/strict';
import worker, { scanOnce } from '../hosted/alert_scheduler/worker.mjs';

const secret = 'test-only-scheduler-secret-000000000000000000000000';

test('disabled scheduler and public HTTP interface cannot scan', async () => {
  let calls = 0;
  assert.equal(await scanOnce({}, async () => { calls++; }), 'disabled');
  assert.equal((await worker.fetch()).status, 404);
  assert.equal(calls, 0);
});

test('enabled scheduler requires a secret before making a request', async () => {
  let calls = 0;
  await assert.rejects(scanOnce({ SCAN_ENABLED: 'yes' },
    async () => { calls++; }), /unconfigured/);
  assert.equal(calls, 0);
});

test('scheduled scan calls only the fixed destination and validates counts', async () => {
  const env = { SCAN_ENABLED: 'yes', ALERT_SCAN_SECRET: secret };
  let calls = 0;
  assert.equal(await scanOnce(env, async (url, options) => {
    calls++;
    assert.equal(url,
      'https://codexbackup.segeren.com/api/hosted-business-alert-scan');
    assert.equal(options.method, 'GET');
    assert.equal(options.headers.Authorization, `Bearer ${secret}`);
    assert.equal(options.redirect, 'error');
    return { status: 200, json: async () => ({ claimed: 1,
      accepted: 1, rejected: 0, uncertain: 0, operatorReview: 0 }) };
  }), 'ok');
  assert.equal(calls, 1);
});

test('downstream failure and ambiguous delivery fail the scheduled run', async () => {
  const env = { SCAN_ENABLED: 'yes', ALERT_SCAN_SECRET: secret };
  await assert.rejects(scanOnce(env, async () => ({ status: 503 })),
    /unavailable/);
  await assert.rejects(scanOnce(env, async () => ({ status: 200,
    json: async () => ({ claimed: 1, accepted: 0, rejected: 0,
      uncertain: 1, operatorReview: 1 }) })), /needs_review/);
  await assert.rejects(scanOnce(env, async () => ({ status: 200,
    json: async () => ({ claimed: 1, accepted: 0, rejected: 0,
      uncertain: 0, operatorReview: 0 }) })), /invalid_result/);
});
