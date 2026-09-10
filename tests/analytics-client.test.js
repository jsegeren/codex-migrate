const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(require.resolve('../site/analytics.js'), 'utf8');

function page({ blockedStorage = false, hostname = 'migrate.segeren.com' } = {}) {
  let resolveRegion;
  let click;
  let applicationEvent;
  let load;
  let notice;
  let fetchCalls = 0;
  const scripts = [];
  const storage = new Map();
  const region = new Promise(resolve => { resolveRegion = resolve; });
  const document = {
    readyState: 'loading',
    cookie: '',
    head: { appendChild(script) { scripts.push(script); } },
    body: { dataset: {}, appendChild(element) { notice = element; } },
    addEventListener(type, handler) {
      if (type === 'click') click = handler;
      if (type === 'codex-migrate:analytics-event') applicationEvent = handler;
    },
    createElement(tag) {
      const buttons = new Map();
      return {
        setAttribute() {},
        remove() { notice = null; },
        querySelector(selector) {
          if (!buttons.has(selector)) buttons.set(selector, {
            focus() {},
            addEventListener(type, handler) { this.activate = handler; },
          });
          return buttons.get(selector);
        },
      };
    },
  };
  const window = {
    location: { hostname },
    addEventListener(type, handler) { if (type === 'load') load = handler; },
    localStorage: {
      getItem(key) { if (blockedStorage) throw Error('Storage unavailable'); return storage.get(key); },
      setItem(key, value) { if (blockedStorage) throw Error('Storage unavailable'); storage.set(key, value); },
    },
  };
  vm.runInNewContext(source, { window, document, fetch: () => { fetchCalls++; return region; } });
  return {
    window, scripts,
    get fetchCalls() { return fetchCalls; },
    get notice() { return notice; },
    clickTarget(target) { click({ preventDefault() {}, target }); },
    applicationEvent(name) { applicationEvent({ detail: name }); },
    choose(allow) {
      click({ preventDefault() {}, target: { closest: () => ({}) } });
      notice.querySelector(allow ? '[data-analytics-accept]' : '[data-analytics-decline]').activate();
    },
    async finish(mode) {
      load();
      resolveRegion({ ok: true, json: async () => ({ mode }) });
      await new Promise(resolve => setImmediate(resolve));
    },
  };
}

test('analytics waits for page load instead of competing with the hero render', async () => {
  const browser = page();
  assert.equal(browser.fetchCalls, 0);
  assert.equal(browser.scripts.length, 0);
  await browser.finish('default');
  assert.equal(browser.fetchCalls, 1);
  assert.equal(browser.scripts.length, 1);
});

test('CTA events before page load are queued and flushed after analytics starts', async () => {
  const browser = page();
  // Exercise the installed document listener with a tracked-link-shaped target.
  // The first closest() call is for preferences; the second is the CTA.
  let calls = 0;
  const target = { closest() { return ++calls === 1 ? null : { dataset: { analyticsEvent: 'select_paid_beta' } }; } };
  browser.clickTarget(target);
  await browser.finish('default');
  assert.equal(browser.window.dataLayer.some(entry => entry[0] === 'event' && entry[1] === 'select_paid_beta'), true);
});

test('verified application events use the same validated analytics queue', async () => {
  const browser = page();
  browser.applicationEvent('purchase');
  browser.applicationEvent('Invalid event name');
  await browser.finish('default');
  assert.equal(browser.window.dataLayer.some(entry => entry[0] === 'event' && entry[1] === 'purchase'), true);
  assert.equal(browser.window.dataLayer.some(entry => entry[0] === 'event' && entry[1] === 'Invalid event name'), false);
});

for (const blockedStorage of [false, true]) {
  for (const allow of [false, true]) {
    test(`choice before region lookup survives initialization: allow=${allow}, blockedStorage=${blockedStorage}`, async () => {
      const browser = page({ blockedStorage });
      browser.choose(allow);
      assert.equal(browser.notice, null);
      await browser.finish(allow ? 'consent' : 'default');
      assert.equal(browser.scripts.length, 1);
      assert.equal(browser.window.dataLayer[0][2].analytics_storage, allow ? 'granted' : 'denied');
      assert.equal(browser.notice, null);
    });
  }
}

test('choices work on a local preview without loading Google', () => {
  const browser = page({ hostname: 'localhost' });
  browser.choose(false);
  browser.choose(true);
  assert.equal(browser.notice, null);
  assert.equal(browser.scripts.length, 0);
});

test('choice after initialization updates Google consent', async () => {
  const browser = page();
  await browser.finish('default');
  browser.choose(false);
  const update = browser.window.dataLayer.at(-1);
  assert.equal(update[0], 'consent');
  assert.equal(update[1], 'update');
  assert.equal(update[2].analytics_storage, 'denied');
});
