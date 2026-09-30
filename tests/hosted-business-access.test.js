const test = require('node:test');
const assert = require('node:assert/strict');
const { randomBytes } = require('node:crypto');
const { mintUploadLease } = require('../hosted/upload_lease');
const { authorizeBusinessUploadScope, authorizeBusinessReadScope,
  authorizeBusinessLeasedUploadScope, businessTokenHash,
  isAuthorizedScope, isAuthorizedReadScope } = require('../hosted/access');

const accountId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const vaultId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const reservationId = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const token = `hvb1_${'a'.repeat(43)}`;

function request(overrides = {}) {
  return { sessionToken: token, vaultId,
    query: async (sql, values) => {
      assert.deepEqual(values, [businessTokenHash(token), vaultId]);
      assert.match(sql, /business_device_sessions/);
      assert.match(sql, /business_seat_vaults/);
      assert.match(sql, /s\.revoked_at IS NULL/);
      assert.match(sql, /d\.revoked_at IS NULL/);
      assert.match(sql, /d\.expires_at > clock_timestamp\(\)/);
      if (sql.includes('business_backup_entitlements')) {
        assert.match(sql, /e\.revoked_at IS NULL/);
        assert.match(sql, /e\.starts_at <= clock_timestamp\(\)/);
        assert.match(sql, /e\.expires_at > clock_timestamp\(\)/);
        return { rows: [{ account_id: accountId, vault_id: vaultId,
          allowance_bytes: '1000000000' }] };
      }
      return { rows: [{ account_id: accountId, vault_id: vaultId }] };
    }, ...overrides };
}

test('business backup needs a separate current allowance and an active seat', async () => {
  const scope = await authorizeBusinessUploadScope(request());
  assert.deepEqual(scope, { accountId, vaultId, allowanceBytes: 1_000_000_000 });
  assert.equal(Object.isFrozen(scope), true);
  assert.equal(isAuthorizedScope(scope), true);
  assert.equal(isAuthorizedScope({ ...scope }), false);
  const read = await authorizeBusinessReadScope(request());
  assert.deepEqual(read, { accountId, vaultId });
  assert.equal(isAuthorizedReadScope(read), true);
});

test('invalid, foreign, expired, revoked, and missing business rows fail closed', async () => {
  for (const sessionToken of ['', `hv1_${'a'.repeat(43)}`, 'hvb1_bad']) {
    await assert.rejects(authorizeBusinessUploadScope(request({ sessionToken })),
      /hosted_access_denied/);
    await assert.rejects(authorizeBusinessReadScope(request({ sessionToken })),
      /hosted_access_denied/);
  }
  for (const rows of [[], [{ account_id: accountId,
    vault_id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd', allowance_bytes: '1000' }],
    [{ account_id: 'foreign', vault_id: vaultId, allowance_bytes: '1000' }],
    [{ account_id: accountId, vault_id: vaultId, allowance_bytes: '0' }],
    [{ account_id: accountId, vault_id: vaultId,
      allowance_bytes: '1000000000001' }]]) {
    await assert.rejects(authorizeBusinessUploadScope(request({
      query: async () => ({ rows }),
    })), /hosted_access_denied/);
  }
  await assert.rejects(authorizeBusinessUploadScope(request({
    query: async () => { throw Error('private database failure'); },
  })), error => error.message === 'hosted_access_denied');
  // The SQL predicates exclude expired sessions, revoked seats, and inactive
  // allowances. An absent qualifying row must never mint a scope.
  await assert.rejects(authorizeBusinessReadScope(request({
    query: async () => ({ rows: [] }),
  })), /hosted_access_denied/);
});

test('business upload lease stays bound to device, reservation, and allowance', async () => {
  const secret = randomBytes(32);
  const lease = mintUploadLease({ accountId, vaultId, reservationId,
    deviceHash: businessTokenHash(token), allowanceBytes: 1_000_000_000,
    secret });
  const scope = await authorizeBusinessLeasedUploadScope({ ...request(),
    reservationId, lease, secret });
  assert.equal(isAuthorizedScope(scope), true);
  assert.equal(scope.accountId, accountId);
  for (const changes of [{ sessionToken: `hvb1_${'b'.repeat(43)}` },
    { reservationId: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd' },
    { query: async () => ({ rows: [] }) },
    { query: async () => ({ rows: [{ account_id: accountId, vault_id: vaultId,
      allowance_bytes: '999999999' }] }) }]) {
    await assert.rejects(authorizeBusinessLeasedUploadScope({ ...request(),
      reservationId, lease, secret, ...changes }), /hosted_access_denied/);
  }
});
