const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { readMigrationFiles } = require('drizzle-orm/migrator');

test('hosted migration journal includes every SQL migration in order', () => {
  const folder = path.join(__dirname, '..', 'hosted', 'migrations');
  const journal = JSON.parse(fs.readFileSync(
    path.join(folder, 'meta', '_journal.json'), 'utf8'));
  const files = fs.readdirSync(folder).filter(name => /^\d{4}_.+\.sql$/.test(name))
    .map(name => name.slice(0, -4)).sort();
  const entries = journal.entries;

  assert.equal(journal.dialect, 'postgresql');
  assert.deepEqual(entries.map(entry => entry.tag), files);
  assert.deepEqual(entries.map(entry => entry.idx),
    files.map((_, index) => index));
  assert.equal(readMigrationFiles({ migrationsFolder: folder }).length, files.length);
  for (let index = 1; index < entries.length; index++) {
    assert.ok(entries[index].when > entries[index - 1].when,
      'migration timestamps must be strictly increasing');
  }
});
