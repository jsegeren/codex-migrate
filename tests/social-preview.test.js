const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { test } = require('node:test');

test('homepage declares an accessible large social card with a real PNG asset', () => {
  const html = readFileSync(new URL('../site/index.html', `file://${__filename}`), 'utf8');
  const tags = [...html.matchAll(/<meta\s+(?:property|name)="([^"]+)"\s+content="([^"]*)"\s*\/?\s*>/g)];
  const meta = Object.fromEntries(tags.map(match => [match[1], match[2]]));
  for (const key of ['og:image', 'twitter:image']) {
    assert.equal(meta[key], 'https://migrate.segeren.com/og-dark-v1.png');
    assert.equal(tags.filter(match => match[1] === key).length, 1);
  }
  assert.equal(meta['twitter:card'], 'summary_large_image');
  assert.equal(meta['og:image:type'], 'image/png');
  assert.match(meta['twitter:description'], /Free CLI beta; \$50 Mac beta access by request/);
  for (const key of ['og:description', 'twitter:description']) {
    assert.match(meta[key], /OpenAI Codex/);
    assert.match(meta[key], /Codex in the ChatGPT desktop app/);
  }
  for (const key of ['og:image:alt', 'twitter:image:alt']) {
    assert.match(meta[key], /Codex Migrate/);
    assert.match(meta[key], /not affiliated with OpenAI/);
  }
  const png = readFileSync(new URL('../site/og-dark-v1.png', `file://${__filename}`));
  assert.equal(png.subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
  assert.equal(png.readUInt32BE(16), Number(meta['og:image:width']));
  assert.equal(png.readUInt32BE(20), Number(meta['og:image:height']));
  assert(png.length < 5 * 1024 * 1024, 'keep the image below social crawler size limits');
});
