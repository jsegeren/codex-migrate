const test = require('node:test');
const assert = require('node:assert/strict');
const { uploadAllowance, uploadEntitled } = require('../hosted/stripe_entitlement');

const enrollment = { subscriptionId: 'sub_hosted', customerId: 'cus_buyer',
  priceId: 'price_hosted' };
const catalog = new Map([
  ['price_hosted', { priceCents: 1000, allowanceBytes: 100_000_000_000 }],
  ['price_larger', { priceCents: 2000, allowanceBytes: 200_000_000_000 }],
]);
function subscription(status = 'trialing', priceId = enrollment.priceId, priceCents = 1000) {
  return { id: enrollment.subscriptionId, customer: enrollment.customerId,
    livemode: false, status, collection_method: 'charge_automatically',
    pause_collection: null, items: { data: [{ quantity: 1, price: {
      id: priceId, livemode: false, type: 'recurring',
      currency: 'usd', unit_amount: priceCents, billing_scheme: 'per_unit',
      recurring: { interval: 'month', interval_count: 1 },
    } }] } };
}

test('only the authenticated buyer’s verified monthly trial or paid subscription grants uploads', () => {
  for (const state of ['trialing', 'active']) {
    assert.equal(uploadEntitled(subscription(state), enrollment, false, catalog), true);
    assert.equal(uploadAllowance(subscription(state), enrollment, false, catalog),
      100_000_000_000);
  }
  for (const state of ['incomplete', 'incomplete_expired', 'past_due', 'unpaid',
    'paused', 'canceled', 'unknown']) {
    assert.equal(uploadEntitled(subscription(state), enrollment, false, catalog), false);
  }
});

test('foreign identity, environment, catalog, or paused collection never grants uploads', () => {
  const changes = [
    value => { value.id = 'sub_other'; },
    value => { value.customer = 'cus_other'; },
    value => { value.livemode = true; },
    value => { value.pause_collection = { behavior: 'void' }; },
    value => { value.collection_method = 'send_invoice'; },
    value => { value.items.data.push(value.items.data[0]); },
    value => { value.items.data[0].quantity = 2; },
    value => { value.items.data[0].price.id = 'price_other'; },
    value => { value.items.data[0].price.livemode = true; },
    value => { value.items.data[0].price.unit_amount = 0; },
    value => { value.items.data[0].price.recurring.interval = 'year'; },
  ];
  for (const change of changes) {
    const value = subscription();
    change(value);
    assert.equal(uploadEntitled(value, enrollment, false, catalog), false);
  }
  assert.equal(uploadEntitled(subscription(), { ...enrollment, customerId: 'cus_other' }, false, catalog), false);
  assert.equal(uploadEntitled(subscription(), { ...enrollment, priceId: 'price_other' }, false, catalog), false);
  assert.equal(uploadEntitled(subscription(), enrollment, true, catalog), false);
});

test('missing or malformed authority cannot be mistaken for an entitlement', () => {
  for (const value of [null, {}, { ...enrollment, subscriptionId: '../other' },
    { ...enrollment, customerId: null }]) {
    assert.equal(uploadEntitled(subscription(), value, false, catalog), false);
  }
  assert.equal(uploadEntitled(null, enrollment, false, catalog), false);
  assert.equal(uploadEntitled(subscription(), enrollment, undefined, catalog), false);
  assert.equal(uploadEntitled({ ...subscription(), items: null }, enrollment, false, catalog), false);
  assert.equal(uploadEntitled(subscription(), enrollment, false), false);
});

test('server-held price catalog grants only the matched tier and allowance', () => {
  const larger = { ...enrollment, priceId: 'price_larger' };
  assert.equal(uploadAllowance(subscription('active', 'price_larger', 2000),
    larger, false, catalog), 200_000_000_000);
  assert.equal(uploadAllowance(subscription('active', 'price_larger', 1000),
    larger, false, catalog), null);
  assert.equal(uploadAllowance(subscription('active', 'price_hosted', 1000),
    larger, false, catalog), null);
  assert.equal(uploadAllowance(subscription('active', 'price_larger', 2000),
    larger, false, new Map()), null);
  assert.equal(uploadAllowance(subscription(), enrollment, false,
    new Map([['price_hosted', { priceCents: 0, allowanceBytes: 100 }]])), null);
  assert.equal(uploadAllowance(subscription(), enrollment, false,
    new Map([['price_hosted', { priceCents: 1000, allowanceBytes: 0 }]])), null);
});
