const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const { readFileSync } = require('node:fs');

const script = readFileSync(require.resolve('../site/demo.js'), 'utf8');

function fixture() {
  const videos = [{ paused: 0, pause() { this.paused += 1; } }, { paused: 0, pause() { this.paused += 1; } }];
  const panels = [
    { hidden: false, querySelector: () => videos[0] },
    { hidden: true, querySelector: () => videos[1] },
  ];
  const tabs = ['vault-demo-panel', 'migration-demo-panel'].map((target) => ({
    dataset: { demoTarget: target }, events: {}, attributes: {}, tabIndex: target === 'vault-demo-panel' ? 0 : -1,
    addEventListener(name, handler) { this.events[name] = handler; },
    setAttribute(name, value) { this.attributes[name] = value; },
    focus() { this.focused = true; },
  }));
  const document = {
    querySelectorAll: () => tabs,
    getElementById: (id) => panels[id === 'vault-demo-panel' ? 0 : 1],
  };
  vm.runInNewContext(script, { document });
  return { tabs, panels, videos };
}

test('clicking a walkthrough tab swaps panels and pauses the hidden video', () => {
  const f = fixture();
  f.tabs[1].events.click();
  assert.equal(f.tabs[0].attributes['aria-selected'], 'false');
  assert.equal(f.tabs[1].attributes['aria-selected'], 'true');
  assert.equal(f.panels[0].hidden, true);
  assert.equal(f.panels[1].hidden, false);
  assert.equal(f.videos[0].paused, 1);
});

test('arrow keys cycle tabs with roving focus', () => {
  const f = fixture();
  let prevented = false;
  f.tabs[0].events.keydown({ key: 'ArrowLeft', preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
  assert.equal(f.tabs[1].focused, true);
  assert.equal(f.tabs[1].tabIndex, 0);
  assert.equal(f.tabs[0].tabIndex, -1);
});
