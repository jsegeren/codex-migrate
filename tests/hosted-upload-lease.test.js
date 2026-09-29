const test = require('node:test');
const assert = require('node:assert/strict');
const { randomBytes } = require('node:crypto');
const { mintUploadLease, verifyUploadLease,
  requireActiveReservation } = require('../hosted/upload_lease');

const secret = randomBytes(32);
const claim = Object.freeze({
  accountId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  vaultId: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
  reservationId: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
  deviceHash: 'd'.repeat(64), allowanceBytes: 100_000_000,
});

test('upload lease is exact, signed and valid for at most one minute', () => {
  const now = 1_790_000_000_000;
  const lease = mintUploadLease({ ...claim, secret, now });
  const verified = { ...claim, expiresAt: now + 60_000 };
  assert.deepEqual(verifyUploadLease(lease, secret, now), verified);
  assert.deepEqual(verifyUploadLease(lease, secret, now + 59_999), verified);
  assert.throws(() => verifyUploadLease(lease, secret, now + 60_000),
    /hosted_upload_lease_denied/);
  assert.throws(() => verifyUploadLease(lease, secret, now - 1),
    /hosted_upload_lease_denied/);
  assert.throws(() => verifyUploadLease(lease, randomBytes(32), now),
    /hosted_upload_lease_denied/);
  assert.throws(() => verifyUploadLease(lease.slice(0, -1) +
    (lease.endsWith('A') ? 'B' : 'A'), secret, now),
    /hosted_upload_lease_denied/);
  assert.throws(() => verifyUploadLease(lease + '.extra', secret, now),
    /hosted_upload_lease_denied/);
});

test('lease issuer rejects missing scope, unlimited allowance and invalid key', () => {
  for (const bad of [
    { vaultId: 'foreign' }, { deviceHash: 'bad' },
    { allowanceBytes: 0 }, { allowanceBytes: 1_000_000_000_001 },
    { reservationId: 'bad' },
  ]) {
    assert.throws(() => mintUploadLease({ ...claim, ...bad, secret }),
      /hosted_upload_lease_denied/);
  }
  assert.throws(() => mintUploadLease({ ...claim, secret: randomBytes(16) }),
    /hosted_upload_lease_denied/);
});

test('lease issuance requires an active reservation owned by the same account and Vault', async () => {
  const query = async (sql, values) => {
    assert.match(sql, /state = 'active'/);
    assert.deepEqual(values, [claim.accountId, claim.vaultId,
      claim.reservationId]);
    return { rows: [{ active: 1 }] };
  };
  await requireActiveReservation({ ...claim, query });
  for (const rows of [[], [{ active: 0 }], [{ active: 1 }, { active: 1 }]]) {
    await assert.rejects(requireActiveReservation({ ...claim,
      query: async () => ({ rows }) }), /hosted_upload_lease_denied/);
  }
  await assert.rejects(requireActiveReservation({ ...claim,
    reservationId: 'invalid', query }), /hosted_upload_lease_denied/);
});
