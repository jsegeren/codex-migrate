const test = require('node:test');
const assert = require('node:assert/strict');
const { planRetainedAddition } = require('../hosted/capacity');

const object = (key, bytes, sha256 = 'a'.repeat(64)) => ({ key, bytes, sha256 });

test('reused chunks count once while each new version adds its own objects', () => {
  const chunk = object('objects/aa/chunk', 100);
  const first = planRetainedAddition(0, 200, [chunk, object('refs/first', 10)], new Map());
  assert.equal(first.retainedBytes, 110);
  const existing = new Map(first.newObjects.map(item => [item.key, item]));
  const second = planRetainedAddition(first.retainedBytes, 200,
    [chunk, object('refs/second', 10)], existing);
  assert.equal(second.addedBytes, 10);
  assert.equal(second.retainedBytes, 120);
  assert.deepEqual(second.newObjects.map(item => item.key), ['refs/second']);
});

test('one account allowance covers objects from both of its Vaults', () => {
  const first = planRetainedAddition(0, 150, [object('vault-a/chunk', 100)], new Map());
  assert.throws(() => planRetainedAddition(first.retainedBytes, 150,
    [object('vault-b/chunk', 60)], new Map()), /hosted_capacity_invalid/);
});

test('the allowance is a hard stop, including an exact-boundary success', () => {
  assert.equal(planRetainedAddition(80, 100, [object('new', 20)], new Map()).retainedBytes, 100);
  assert.throws(() => planRetainedAddition(80, 100,
    [object('new', 21)], new Map()), /hosted_capacity_invalid/);
});

test('a reused key with different bytes or digest never silently overwrites', () => {
  const current = object('objects/aa/chunk', 10);
  for (const changed of [object(current.key, 11), object(current.key, 10, 'b'.repeat(64))]) {
    assert.throws(() => planRetainedAddition(10, 100, [changed],
      new Map([[current.key, current]])), /hosted_capacity_invalid/);
  }
});

test('duplicate keys and unsafe totals fail closed without changing inventory', () => {
  const existing = new Map();
  const item = object('new', 10);
  for (const objects of [[item, item], [object('bad', 0)], [object('bad', 1, 'x')]]) {
    assert.throws(() => planRetainedAddition(0, 100, objects, existing),
      /hosted_capacity_invalid/);
  }
  assert.throws(() => planRetainedAddition(Number.MAX_SAFE_INTEGER - 1,
    Number.MAX_SAFE_INTEGER, [item], existing), /hosted_capacity_invalid/);
  assert.equal(existing.size, 0);
});
