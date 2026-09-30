const test = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');

const root = join(__dirname, '..');
const { redirects } = require(join(root, 'vercel.json'));
const oldHost = 'migrate.segeren.com';
const newOrigin = 'https://codexbackup.segeren.com';

test('old-host page redirects cover the sitemap without intercepting app APIs', () => {
  const publicRedirects = redirects.filter(rule => rule.has?.some(condition =>
    condition.type === 'host' && condition.value === oldHost));
  assert.equal(publicRedirects.length, 3);
  assert.equal(publicRedirects[0].source, '/');
  assert.equal(publicRedirects[2].source, '/ja/codex-new-mac');
  assert.equal(publicRedirects[0].destination, newOrigin + '/');
  assert.equal(publicRedirects[2].destination,
    newOrigin + '/ja/codex-new-mac');
  assert.ok(publicRedirects.every(rule => rule.permanent === true));

  const match = /^\/:page\(([^)]+)\)$/.exec(publicRedirects[1].source);
  assert.ok(match, 'public pages must be an exact named-path list');
  assert.equal(publicRedirects[1].destination, newOrigin + '/:page');
  const namedPages = match[1].split('|');
  const sitemap = readFileSync(join(root, 'site/sitemap.xml'), 'utf8');
  const sitemapPaths = [...sitemap.matchAll(/<loc>([^<]+)<\/loc>/g)]
    .map(([, value]) => new URL(value))
    .filter(url => url.origin === newOrigin)
    .map(url => url.pathname)
    .filter(path => path !== '/' && path !== '/ja/codex-new-mac')
    .map(path => path.slice(1));
  assert.deepEqual(namedPages.slice().sort(), sitemapPaths.sort());
  assert.ok(namedPages.every(page => !page.includes('/') &&
    !['api', 'assets', 'download', 'checkout'].includes(page)));
});
