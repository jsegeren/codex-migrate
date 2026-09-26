const test = require('node:test');
const assert = require('node:assert/strict');
const { uploadEntitled } = require('../hosted/stripe_entitlement');

const enrollment = { subscriptionId: 'sub_hosted', customerId: 'cus_buyer',
  priceId: 'price_hosted' };
function subscription(status = 'trialing') {
  return { id: enrollment.subscriptionId, customer: enrollment.customerId,
    livemode: false, status, collection_method: 'charge_automatically',
    pause_collection: null, items: { data: [{ quantity: 1, price: {
      id: enrollment.priceId, livemode: false, type: 'recurring',
      currency: 'usd', unit_amount: 1000, billing_scheme: 'per_unit',
      recurring: { interval: 'month', interval_count: 1 },
    } }] } };
}

test('only the authenticated buyer’s verified monthly trial or paid subscription grants uploads', () => {
  for (const state of ['trialing', 'active']) {
    assert.equal(uploadEntitled(subscription(state), enrollment, false), true);
  }
  for (const state of ['incomplete', 'incomplete_expired', 'past_due', 'unpaid',
    'paused', 'canceled', 'unknown']) {
    assert.equal(uploadEntitled(subscription(state), enrollment, false), false);
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
    assert.equal(uploadEntitled(value, enrollment, false), false);
  }
  assert.equal(uploadEntitled(subscription(), { ...enrollment, customerId: 'cus_other' }, false), false);
  assert.equal(uploadEntitled(subscription(), { ...enrollment, priceId: 'price_other' }, false), false);
  assert.equal(uploadEntitled(subscription(), enrollment, true), false);
});

test('missing or malformed authority cannot be mistaken for an entitlement', () => {
  for (const value of [null, {}, { ...enrollment, subscriptionId: '../other' },
    { ...enrollment, customerId: null }]) {
    assert.equal(uploadEntitled(subscription(), value, false), false);
  }
  assert.equal(uploadEntitled(null, enrollment, false), false);
  assert.equal(uploadEntitled(subscription(), enrollment, undefined), false);
  assert.equal(uploadEntitled({ ...subscription(), items: null }, enrollment, false), false);
});
