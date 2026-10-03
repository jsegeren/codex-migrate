const test = require('node:test');
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { subscriptionCheckout, POLICY, RESERVE_SQL, LOOKUP_SQL, SAVE_SQL,
  ENROLL_SQL } = require('../hosted/subscription_checkout');
const { subscriptionConfiguration, subscriptionRuntime } = require('../hosted/subscription_runtime');
const { makeHandler } = require('../api/hosted-subscription');
const { mintSessionSecret } = require('./hosted-device-fixture');

const site = 'https://codex-migrate-fixture-joshuas-projects-d3a5c48d.vercel.app';
const config = { priceId: 'price_fixture', priceCents: 1000,
  allowanceBytes: 1000000, site };
const env = { HOSTED_MODE: 'sandbox', COMMERCE_MODE: 'sandbox',
  HOSTED_SANDBOX_SUBSCRIPTION_OPEN: 'yes', HOSTED_SANDBOX_PRICE_ID: config.priceId,
  HOSTED_SANDBOX_PRICE_CENTS: String(config.priceCents),
  HOSTED_SANDBOX_ALLOWANCE_BYTES: String(config.allowanceBytes),
  COMMERCE_DATABASE_URL: 'postgresql://fixture:fixture@ep-square-queen-av5us6bx.c-11.us-east-1.aws.neon.tech/neondb' };

function fixture() {
  const accountId = randomUUID();
  const vaultId = randomUUID();
  const deviceId = randomUUID();
  const secret = mintSessionSecret();
  const attempt = { account_id: accountId, mode: 'sandbox', attempt_id: randomUUID(),
    price_id: config.priceId, price_cents: config.priceCents,
    allowance_bytes: String(config.allowanceBytes), site, policy: POLICY,
    session_id: null, retry_allowed: true };
  const metadata = { product: 'codex-backup-hosted-sandbox', account_id: accountId,
    checkout_attempt: attempt.attempt_id, policy: POLICY };
  const session = { id: 'cs_test_fixture', livemode: false, mode: 'subscription',
    client_reference_id: accountId, metadata, status: 'open',
    url: 'https://checkout.stripe.com/c/pay/cs_test_fixture',
    customer: 'cus_fixture', subscription: 'sub_fixture', payment_status: 'no_payment_required' };
  const subscription = { id: session.subscription, customer: session.customer,
    livemode: false, status: 'trialing', metadata: { ...metadata },
    collection_method: 'charge_automatically', pause_collection: null,
    items: { data: [{ quantity: 1, price: { id: config.priceId, livemode: false,
      type: 'recurring', currency: 'usd', unit_amount: config.priceCents,
      billing_scheme: 'per_unit', recurring: { interval: 'month', interval_count: 1 } } }] } };
  const counters = { creates: 0, retrieves: 0, subscriptions: 0, enrolls: 0, purchases: 0 };
  const price = { ...subscription.items.data[0].price, active: true };
  const createCalls = [];
  let lostCreate = false;
  let lostSave = false;
  let expiredDevice = false;
  let enrollmentConflict = false;
  const query = async (sql, params) => {
    if (sql.includes('FROM hosted.device_sessions')) {
      assert.deepEqual(params, [secret.tokenHash, deviceId]);
      return { rows: expiredDevice ? [] : [{ account_id: accountId, vault_id: vaultId,
        device_id: deviceId, purchase_session_id: 'cs_test_purchase', purchase_mode: 'sandbox' }] };
    }
    if (sql === RESERVE_SQL || sql === LOOKUP_SQL) {
      assert.equal(params[0], accountId);
      return { rows: [{ ...attempt }] };
    }
    if (sql === SAVE_SQL) {
      assert.deepEqual(params, [accountId, attempt.attempt_id, session.id]);
      attempt.session_id = session.id;
      if (lostSave) { lostSave = false; throw Error('private SQL failed after commit'); }
      return { rows: [{ recorded: true }] };
    }
    assert.equal(sql, ENROLL_SQL);
    assert.deepEqual(params, [accountId, attempt.attempt_id, session.id,
      subscription.id, session.customer]);
    counters.enrolls++;
    return { rows: [{ enrolled: !enrollmentConflict }] };
  };
  const stripe = { prices: { retrieve: async id => {
    assert.equal(id, config.priceId); return price;
  } }, checkout: { sessions: {
    create: async (params, options) => {
      counters.creates++;
      createCalls.push({ params, options });
      if (lostCreate) { lostCreate = false; throw Error('private Stripe lost acknowledgement'); }
      return { ...session };
    },
    retrieve: async id => { assert.equal(id, attempt.session_id); counters.retrieves++; return { ...session }; },
  } }, subscriptions: { retrieve: async (id, options) => {
    assert.equal(id, session.subscription);
    assert.deepEqual(options, { expand: ['items.data.price'] });
    counters.subscriptions++;
    return subscription;
  } } };
  const verifyPurchase = async (id, mode) => {
    counters.purchases++;
    assert.equal(id, 'cs_test_purchase'); assert.equal(mode, 'sandbox');
    return { sessionId: id, mode };
  };
  const options = { query, stripe, verifyPurchase, config,
    deviceId, deviceToken: secret.token };
  return { ...options, accountId, secret, attempt, session, subscription, price,
    counters, createCalls, loseCreate: () => { lostCreate = true; },
    loseSave: () => { lostSave = true; }, expireDevice: () => { expiredDevice = true; },
    conflict: () => { enrollmentConflict = true; },
    run: action => subscriptionCheckout({ ...options, action }) };
}

test('begin persists attempt, uses server-owned price/identity and explicit test trial', async () => {
  const f = fixture();
  assert.deepEqual(await f.run('begin'), { status: 'checkout_required',
    checkoutUrl: f.session.url, testMode: true });
  const call = f.createCalls[0];
  assert.equal(call.params.client_reference_id, f.accountId);
  assert.deepEqual(call.params.line_items, [{ price: config.priceId, quantity: 1 }]);
  assert.equal(call.params.payment_method_collection, 'always');
  assert.equal(call.params.subscription_data.trial_period_days, 30);
  assert.deepEqual(call.params.metadata, call.params.subscription_data.metadata);
  assert.equal(call.options.idempotencyKey, `hosted-subscription-sandbox-${f.attempt.attempt_id}`);
  assert.equal(f.counters.enrolls, 0);
  assert.equal(f.counters.subscriptions, 0);
  assert.equal(f.counters.purchases, 1);
});

test('lost create response retries same frozen parameters and key', async () => {
  const f = fixture(); f.loseCreate();
  await assert.rejects(f.run('begin'), /^Error: hosted_subscription_unavailable$/);
  await f.run('begin');
  assert.deepEqual(f.createCalls[0], f.createCalls[1]);
  await f.run('begin');
  assert.equal(f.counters.creates, 2);
  assert.equal(f.counters.retrieves, 1);
});

test('lost save response reconciles persisted checkout without creating another', async () => {
  const f = fixture(); f.loseSave();
  await assert.rejects(f.run('begin'), /hosted_subscription_unavailable/);
  await f.run('begin');
  assert.equal(f.counters.creates, 1);
  assert.equal(f.counters.retrieves, 1);
});

test('uncertain attempt past idempotency window fails closed; status cannot create', async () => {
  const f = fixture(); f.attempt.retry_allowed = false;
  await assert.rejects(f.run('begin'), /hosted_subscription_unavailable/);
  await assert.rejects(f.run('status'), /hosted_subscription_unavailable/);
  assert.equal(f.counters.creates, 0);
});

test('misconfigured provider catalog refuses checkout before any subscription can be created', async () => {
  for (const patch of [{ active: false }, { livemode: true }, { unit_amount: 999 },
    { currency: 'eur' }, { type: 'one_time' }, { id: 'price_other' },
    { recurring: { interval: 'year', interval_count: 1 } }]) {
    const f = fixture(); Object.assign(f.price, patch);
    await assert.rejects(f.run('begin'), /hosted_subscription_unavailable/);
    assert.equal(f.counters.creates, 0);
  }
});

test('expired saved checkout asks for support instead of starting a second subscription', async () => {
  const f = fixture(); await f.run('begin'); f.session.status = 'expired';
  assert.deepEqual(await f.run('begin'), { status: 'needs_support', testMode: true });
  assert.equal(f.counters.creates, 1); assert.equal(f.counters.enrolls, 0);
});

test('successful checkout requires fresh matching subscription before idempotent enrollment', async () => {
  const f = fixture(); await f.run('begin'); f.session.status = 'complete';
  assert.deepEqual(await f.run('status'), { status: 'subscribed', testMode: true });
  assert.deepEqual(await f.run('begin'), { status: 'subscribed', testMode: true });
  assert.equal(f.counters.creates, 1); assert.equal(f.counters.subscriptions, 2);
  assert.equal(f.counters.purchases, 3);
  f.subscription.status = 'past_due';
  assert.deepEqual(await f.run('status'), { status: 'not_entitled', testMode: true });
  assert.equal(f.counters.enrolls, 2);
});

test('foreign, live, or altered Checkout sessions cannot be claimed', async () => {
  for (const mutate of [
    f => { f.session.id = 'cs_live_fixture'; },
    f => { f.session.livemode = true; },
    f => { f.session.mode = 'payment'; },
    f => { f.session.client_reference_id = randomUUID(); },
    f => { f.session.metadata = { ...f.session.metadata, account_id: randomUUID() }; },
    f => { f.session.metadata = { ...f.session.metadata, checkout_attempt: randomUUID() }; },
    f => { f.session.metadata = { ...f.session.metadata, policy: 'other' }; },
    f => { f.session.url = 'https://checkout.stripe.com.evil.example/c/pay/x'; },
  ]) {
    const f = fixture(); mutate(f);
    await assert.rejects(f.run('begin'), /hosted_subscription_unavailable/);
    assert.equal(f.counters.enrolls, 0);
  }
});

test('subscription status, price, ownership and collection mismatches grant nothing', async () => {
  for (const mutate of [
    f => { f.session.payment_status = 'unpaid'; },
    f => { f.subscription.status = 'canceled'; },
    f => { f.subscription.status = 'unpaid'; },
    f => { f.subscription.customer = 'cus_other'; },
    f => { f.subscription.livemode = true; },
    f => { f.subscription.metadata.account_id = randomUUID(); },
    f => { f.subscription.collection_method = 'send_invoice'; },
    f => { f.subscription.pause_collection = {}; },
    f => { f.subscription.items.data[0].price.unit_amount = 999; },
    f => { f.subscription.items.data[0].price.id = 'price_other'; },
    f => { f.subscription.items.data[0].quantity = 2; },
    f => { f.subscription.items.data[0].price.recurring.interval = 'year'; },
  ]) {
    const f = fixture(); await f.run('begin'); f.session.status = 'complete'; mutate(f);
    assert.deepEqual(await f.run('status'), { status: 'not_entitled', testMode: true });
    assert.equal(f.counters.enrolls, 0);
  }
});

test('revoked device, refunded purchase, and enrollment conflict refuse without leaking diagnostics', async () => {
  const f = fixture(); f.expireDevice();
  await assert.rejects(f.run('begin'), /hosted_subscription_unavailable/);
  assert.equal(f.counters.creates, 0);
  const refund = fixture();
  await assert.rejects(subscriptionCheckout({ ...refund, action: 'begin',
    verifyPurchase: async () => { throw Error('private refund details'); } }),
  /^Error: hosted_subscription_unavailable$/);
  assert.equal(refund.counters.creates, 0);
  const conflict = fixture(); await conflict.run('begin');
  conflict.session.status = 'complete'; conflict.conflict();
  await assert.rejects(conflict.run('status'), /hosted_subscription_unavailable/);
});

test('checkout runtime refuses live configuration and wrong Preview before provider mutation', async () => {
  assert.deepEqual(subscriptionConfiguration(env), { priceId: config.priceId,
    priceCents: config.priceCents, allowanceBytes: config.allowanceBytes });
  for (const patch of [{ HOSTED_MODE: 'live' }, { COMMERCE_MODE: 'live' },
    { HOSTED_SANDBOX_SUBSCRIPTION_OPEN: 'no' }, { HOSTED_SANDBOX_PRICE_CENTS: '999' },
    { COMMERCE_DATABASE_URL: env.COMMERCE_DATABASE_URL.replace('ep-square-queen', 'ep-other') },
    { HOSTED_SANDBOX_ALLOWANCE_BYTES: '1000000000001' }]) {
    assert.throws(() => subscriptionConfiguration({ ...env, ...patch }));
  }
  const f = fixture();
  const options = { openDatabase: async () => f.query, openCommerce: async () => ({
    config: { mode: 'sandbox', live: false, site }, stripe: f.stripe,
    service: { verifyForHostedAuthorization: f.verifyPurchase },
  }) };
  const runtime = await subscriptionRuntime(env, options);
  assert.equal(runtime.config.site, site);
  await assert.rejects(subscriptionRuntime(env, { ...options, openCommerce: async () => ({
    config: { mode: 'sandbox', live: false, site: 'https://codexbackup.segeren.com' },
  }) }), /hosted_subscription_unavailable/);
});

test('route rejects caller identity/session/price, malformed requests, and no bearer before loading', async () => {
  const f = fixture(); let loads = 0;
  const settings = { ...env };
  const handler = makeHandler(async () => { loads++; return f; }, settings);
  const req = { method: 'POST', headers: { 'content-type': 'application/json',
    authorization: `Bearer ${f.secret.token}` }, body: { action: 'begin', deviceId: f.deviceId } };
  const send = async () => {
    const res = { headers: {}, setHeader(k, v) { this.headers[k] = v; },
      end(data) { this.body = JSON.parse(data); } };
    await handler(req, res); return res;
  };
  settings.HOSTED_SANDBOX_SUBSCRIPTION_OPEN = 'no';
  assert.equal((await send()).statusCode, 404);
  settings.HOSTED_SANDBOX_SUBSCRIPTION_OPEN = 'yes';
  settings.COMMERCE_MODE = 'live'; assert.equal((await send()).statusCode, 404);
  settings.COMMERCE_MODE = 'sandbox';
  for (const key of ['sessionId', 'accountId', 'email', 'priceId', 'allowanceBytes', 'trialDays']) {
    req.body[key] = 'untrusted'; assert.equal((await send()).statusCode, 400); delete req.body[key];
  }
  req.headers.origin = 'https://attacker.example'; assert.equal((await send()).statusCode, 400);
  delete req.headers.origin;
  delete req.headers.authorization; assert.equal((await send()).statusCode, 403);
  assert.equal(loads, 0);
  req.headers.authorization = `Bearer ${f.secret.token}`;
  const result = await send(); assert.equal(result.statusCode, 200);
  assert.equal(result.headers['Cache-Control'], 'no-store');
  assert.equal(result.body.status, 'checkout_required');
});
