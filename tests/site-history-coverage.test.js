const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

test('current-beta pages disclose the paginated-history coverage limit', () => {
  for (const page of [
    'index.html',
    'codex-vault.html',
    'backup-codex-conversations-mac.html',
    'search-codex-conversation-history.html',
    'recover-missing-codex-chats.html',
  ]) {
    const html = fs.readFileSync(path.join(__dirname, '..', 'site', page), 'utf8');
    assert.match(html, /paginated-history database/, `${page} omits the beta limit`);
  }
});
