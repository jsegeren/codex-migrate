const test = require('node:test');
const assert = require('node:assert/strict');
const { createUploadReservation, renewUploadReservation,
  abandonUploadReservation } =
  require('../hosted/reservation');
const { authorizeReadScope } = require('../hosted/access');
const { mintSessionSecret } = require('./hosted-device-fixture');
const { freshScope, accountId, vaultId } = require('./hosted-subscriber-fixture');

test('fresh paid scope creates a bounded byte reservation', async () => {
  let calls = 0;
  const receipt = await createUploadReservation({ scope: await freshScope(),
    bytes: 1234, query: async (sql, values) => {
      calls++;
      assert.match(sql, /reserve_upload_current/);
      assert.deepEqual(values.slice(0, 2), [accountId, vaultId]);
      assert.match(values[2], /^[0-9a-f-]{36}$/);
      assert.equal(values[3], 1234);
      assert.equal(values[5], 100_000_000);
      return { rows: [{ allowed: true }] };
    } });
  assert.equal(calls, 1);
  assert.equal(receipt.reservationId.length, 36);
  assert.equal(Object.isFrozen(receipt), true);
  assert.ok(Date.parse(receipt.expiresAt) > Date.now() + 50 * 60_000);
  assert.ok(Date.parse(receipt.expiresAt) < Date.now() + 60 * 60_000);
});

test('renewal rechecks scope and does not trust client-shaped quota', async () => {
  const reservationId = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
  const receipt = await renewUploadReservation({ scope: await freshScope(),
    reservationId, query: async (sql, values) => {
      assert.match(sql, /renew_upload_reservation_current/);
      assert.deepEqual(values.slice(0, 3), [accountId, vaultId, reservationId]);
      assert.equal(values[4], 100_000_000);
      return { rows: [{ allowed: true }] };
    } });
  assert.equal(receipt.reservationId, reservationId);
  let calls = 0;
  await assert.rejects(renewUploadReservation({ scope: { accountId, vaultId,
    allowanceBytes: 100_000_000 }, reservationId,
  query: async () => { calls++; } }), /hosted_reservation_denied/);
  assert.equal(calls, 0);
});

test('malformed requests and replay never reach quota writes', async () => {
  const scope = await freshScope();
  let calls = 0;
  const query = async () => { calls++; return { rows: [{ allowed: true }] }; };
  await assert.rejects(createUploadReservation({ scope, bytes: 100_000_001,
    query }), /hosted_reservation_denied/);
  await assert.rejects(createUploadReservation({ scope, bytes: 1, query }),
    /hosted_reservation_denied/);
  await assert.rejects(renewUploadReservation({ scope: await freshScope(),
    reservationId: 'foreign', query }), /hosted_reservation_denied/);
  assert.equal(calls, 0);
});

test('database and quota errors never disclose internals', async () => {
  const reservationId = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
  for (const execute of [async () => ({ rows: [{ allowed: false }] }),
    async () => { throw Error('secret database detail'); }]) {
    await assert.rejects(createUploadReservation({ scope: await freshScope(),
      bytes: 10, query: execute }), error =>
      error.message === 'hosted_reservation_denied');
    await assert.rejects(renewUploadReservation({ scope: await freshScope(),
      reservationId, query: execute }), error =>
      error.message === 'hosted_reservation_denied');
  }
});

test('abandon consumes owned read scope and never releases quota in its response', async () => {
  const session = mintSessionSecret();
  const scope = await authorizeReadScope({ sessionToken: session.token, vaultId,
    query: async () => ({ rows: [{ account_id: accountId, vault_id: vaultId }] }) });
  const reservationId = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
  const result = await abandonUploadReservation({ scope, reservationId,
    query: async (sql, values) => {
      assert.match(sql, /abandon_upload_reservation/);
      assert.deepEqual(values, [accountId, vaultId, reservationId]);
      return { rows: [{ allowed: true }] };
    } });
  assert.deepEqual(result, { cleanupPending: true });
  await assert.rejects(abandonUploadReservation({ scope, reservationId,
    query: async () => ({ rows: [{ allowed: true }] }) }),
  /hosted_reservation_denied/);
});
