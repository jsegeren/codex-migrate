const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(require.resolve('../site/analytics.js'), 'utf8');

function page({ blockedStorage = false, hostname = 'migrate.segeren.com' } = {}) {
  let resolveRegion;
  let click;
  let notice;
  const scripts = [];
  const storage = new Map();
  const region = new Promise(resolve => { resolveRegion = resolve; });
  const document = {
    cookie: '',
    head: { appendChild(script) { scripts.push(script); } },
    body: { dataset: {}, appendChild(element) { notice = element; } },
    addEventListener(type, handler) { if (type === 'click') click = handler; },
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
    localStorage: {
      getItem(key) { if (blockedStorage) throw Error('Storage unavailable'); return storage.get(key); },
      setItem(key, value) { if (blockedStorage) throw Error('Storage unavailable'); storage.set(key, value); },
    },
  };
  vm.runInNewContext(source, { window, document, fetch: () => region });
  return {
    window, scripts,
    get notice() { return notice; },
    choose(allow) {
      click({ preventDefault() {}, target: { closest: () => ({}) } });
      notice.querySelector(allow ? '[data-analytics-accept]' : '[data-analytics-decline]').activate();
    },
    async finish(mode) {
      resolveRegion({ ok: true, json: async () => ({ mode }) });
      await new Promise(resolve => setImmediate(resolve));
    },
  };
}

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
