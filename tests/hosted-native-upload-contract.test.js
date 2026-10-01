const test = require('node:test');
const assert = require('node:assert/strict');
const { createServer } = require('node:http');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const { resolve } = require('node:path');
const { makeHandler } = require('../api/hosted-upload');
const { mintSessionSecret } = require('./hosted-device-fixture');
const { accountId, vaultId } = require('./hosted-subscriber-fixture');

// Exercise the actual Python HTTP client against the Node route, not two
// separately mocked response shapes. This remains synthetic: no R2 or Stripe.
test('native client reserves, renews, reads and abandons through the sandbox route',
  { timeout: 30_000 }, async () => {
    const session = mintSessionSecret();
    const reservationId = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
    const item = { key: 'objects/aa/' + 'a'.repeat(62) + '.cvchunk',
      bytes: 20, sha256: 'b'.repeat(64) };
    let state = 'active';
    let purchaseChecks = 0;
    let readChecks = 0;
    const env = { HOSTED_MODE: 'sandbox', HOSTED_SANDBOX_UPLOAD_OPEN: 'yes' };
    const handler = makeHandler(async () => ({
      query: async (sql, values) => {
        if (sql.includes('FROM hosted.device_sessions AS sessions')) {
          purchaseChecks++;
          assert.deepEqual(values, [session.tokenHash, vaultId]);
          return { rows: [{ account_id: accountId, vault_id: vaultId,
            purchase_session_id: 'cs_test_fixture', purchase_mode: 'sandbox' }] };
        }
        if (sql.includes('FROM hosted.device_sessions\n')) {
          readChecks++;
          assert.deepEqual(values, [session.tokenHash, vaultId]);
          return { rows: [{ account_id: accountId, vault_id: vaultId }] };
        }
        if (sql.includes('SELECT 1 AS active FROM hosted.upload_reservations')) {
          assert.deepEqual(values, [accountId, vaultId, reservationId]);
          return { rows: [{ active: 1 }] };
        }
        if (sql.includes('reserve_upload_idempotent_current')) {
          assert.deepEqual(values.slice(0, 4), [accountId, vaultId, reservationId, 1]);
          return { rows: [{ allowed: true, base_snapshot_id: null,
            expires_at: values[4] }] };
        }
        if (sql.includes('renew_upload_reservation_current')) {
          assert.deepEqual(values.slice(0, 3), [accountId, vaultId, reservationId]);
          return { rows: [{ allowed: true }] };
        }
        if (sql.includes('classify_upload_object_current')) {
          assert.deepEqual(values.slice(0, 4), [accountId, vaultId,
            reservationId, `accounts/${accountId}/vaults/${vaultId}/${item.key}`]);
          return { rows: [{ decision: 'put' }] };
        }
        if (sql.includes('reserve_object_grant_elastic_current')) {
          assert.deepEqual(values.slice(0, 4), [accountId, vaultId,
            reservationId, `accounts/${accountId}/vaults/${vaultId}/${item.key}`]);
          return { rows: [{ allowed: true }] };
        }
        if (sql.includes('abandon_upload_reservation')) {
          assert.deepEqual(values, [accountId, vaultId, reservationId]);
          state = 'cleanup_pending';
          return { rows: [{ allowed: true }] };
        }
        if (sql.includes('FROM hosted.upload_reservations')) {
          assert.deepEqual(values, [accountId, vaultId, reservationId]);
          return { rows: [{ state, snapshot_id: null,
            verified_object_count: null }] };
        }
        throw Error('unexpected hosted SQL');
      },
      workerOrigin: 'http://127.0.0.1:49112',
      secret: Buffer.alloc(32, 7),
      verifyPurchase: async () => ({ sessionId: 'cs_test_fixture', mode: 'sandbox' }),
      getEntitlement: async id => {
        assert.equal(id, accountId);
        return { enrollment: { accountId, subscriptionId: 'sub_fixture',
          customerId: 'cus_fixture', priceId: 'price_fixture' },
        subscription: { id: 'sub_fixture', customer: 'cus_fixture',
          livemode: false, status: 'active', collection_method: 'charge_automatically',
          pause_collection: null, items: { data: [{ quantity: 1, price: {
            id: 'price_fixture', livemode: false, type: 'recurring', currency: 'usd',
            unit_amount: 1000, billing_scheme: 'per_unit',
            recurring: { interval: 'month', interval_count: 1 },
          } }] } } };
      },
      live: false,
      priceCatalog: new Map([['price_fixture', { priceCents: 1000,
        allowanceBytes: 100_000_000 }]]),
    }), env);
    const server = createServer(async (req, res) => {
      try {
        const parts = [];
        for await (const part of req) parts.push(part);
        req.body = JSON.parse(Buffer.concat(parts).toString('utf8'));
        await handler(req, res);
      } catch {
        if (!res.headersSent) res.writeHead(500);
        res.end();
      }
    });
    server.listen(0, '127.0.0.1');
    await once(server, 'listening');
    try {
      const origin = `http://127.0.0.1:${server.address().port}`;
      const python = [
        'import json, os',
        'from codex_migrate.vault_hosted_upload_client import HostedUploadClient',
        'client = HostedUploadClient(os.environ["SERVICE_ORIGIN"],',
        '    "http://127.0.0.1:49112", os.environ["DEVICE_TOKEN"],',
        '    os.environ["ACCOUNT_ID"], os.environ["VAULT_ID"],',
        '    allow_loopback_http=True)',
        'reservation, base = client.reserve_with_base(',
        '    reservation_id=os.environ["RESERVATION_ID"], apply=True)',
        'assert base is None',
        'assert client.renew(reservation, apply=True) == reservation',
        'item = {"key": "objects/aa/" + "a" * 62 + ".cvchunk",',
        '    "bytes": 20, "sha256": "b" * 64}',
        'decision = client._post({"action": "decide", "vaultId": os.environ["VAULT_ID"],',
        '    "reservationId": reservation, "item": item})',
        'assert decision == {"action": "put_required"}',
        'put = client._post({"action": "put", "vaultId": os.environ["VAULT_ID"],',
        '    "reservationId": reservation, "item": item})',
        'assert put["workerOrigin"] == "http://127.0.0.1:49112"',
        'assert isinstance(put["grant"], str) and len(put["grant"]) > 20',
        'batch = client._post({"action": "batch", "vaultId": os.environ["VAULT_ID"],',
        '    "reservationId": reservation, "items": [item]})',
        'assert batch["workerOrigin"] == "http://127.0.0.1:49112"',
        'assert len(batch["objects"]) == 1',
        'assert batch["objects"][0]["action"] == "put_required"',
        'assert len(batch["objects"][0]["headGrant"]) > 20',
        'assert len(batch["objects"][0]["putGrant"]) > 20',
        'before = client.reservation_status(reservation)',
        'client.abandon(reservation, apply=True)',
        'after = client.reservation_status(reservation)',
        'print(json.dumps({"reservation": reservation, "before": before, "after": after}))',
      ].join('\n');
      const child = spawn(process.env.PYTHON || 'python3', ['-c', python], {
        cwd: resolve(__dirname, '..'),
        timeout: 10_000,
        killSignal: 'SIGKILL',
        env: { ...process.env, PYTHONPATH: resolve(__dirname, '../src'),
          SERVICE_ORIGIN: origin, DEVICE_TOKEN: session.token,
          ACCOUNT_ID: accountId, VAULT_ID: vaultId,
          RESERVATION_ID: reservationId },
      });
      let output = '';
      let error = '';
      child.stdout.on('data', chunk => { output += chunk; });
      child.stderr.on('data', chunk => { error += chunk; });
      const [code] = await once(child, 'close');
      assert.equal(code, 0, error.slice(0, 2000));
      assert.deepEqual(JSON.parse(output), { reservation: reservationId,
        before: 'active', after: 'cleanup_pending' });
      assert.equal(purchaseChecks, 3);
      assert.equal(readChecks, 6);
    } finally {
      const closed = once(server, 'close');
      server.close();
      await closed;
    }
  });
