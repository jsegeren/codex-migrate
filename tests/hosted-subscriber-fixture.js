const { authorizeUploadScope } = require('../hosted/access');
const { mintSessionSecret } = require('./hosted-device-fixture');

const accountId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const vaultId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';

async function freshScope() {
  const session = mintSessionSecret();
  return authorizeUploadScope({
    sessionToken: session.token, vaultId,
    query: async () => ({ rows: [{ account_id: accountId, vault_id: vaultId,
      purchase_session_id: 'cs_test_fixture', purchase_mode: 'sandbox' }] }),
    verifyPurchase: async () => ({ sessionId: 'cs_test_fixture', mode: 'sandbox' }),
    getEntitlement: async () => ({
      enrollment: { accountId, subscriptionId: 'sub_fixture',
        customerId: 'cus_fixture', priceId: 'price_fixture' },
      subscription: { id: 'sub_fixture', customer: 'cus_fixture',
        livemode: false, status: 'active', collection_method: 'charge_automatically',
        pause_collection: null, items: { data: [{ quantity: 1, price: {
          id: 'price_fixture', livemode: false, type: 'recurring', currency: 'usd',
          unit_amount: 1000, billing_scheme: 'per_unit',
          recurring: { interval: 'month', interval_count: 1 },
        } }] } },
    }),
    live: false,
    priceCatalog: new Map([['price_fixture', { priceCents: 1000,
      allowanceBytes: 100_000_000 }]]),
  });
}

module.exports = { accountId, vaultId, freshScope };
