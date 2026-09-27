import test from 'node:test';
import assert from 'node:assert/strict';
import worker from './worker.mjs';

test('sandbox probe is inert without an explicit local enable flag', async () => {
  const request = new Request('http://127.0.0.1/probe', { method: 'POST' });
  const response = await worker.fetch(request, {});
  assert.equal(response.status, 404);
});

test('sandbox probe refuses non-loopback hosts even when enabled', async () => {
  const request = new Request('https://example.com/probe', { method: 'POST' });
  const response = await worker.fetch(request, { PROBE_ENABLED: '1' });
  assert.equal(response.status, 404);
});

test('sandbox probe refuses other paths and methods', async () => {
  for (const request of [new Request('http://localhost/probe'),
    new Request('http://localhost/other', { method: 'POST' })]) {
    const response = await worker.fetch(request, { PROBE_ENABLED: '1' });
    assert.equal(response.status, 404);
  }
});
