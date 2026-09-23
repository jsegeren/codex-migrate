#!/usr/bin/env node
// Creates and retires only disposable, synthetic encrypted-hook test storage.
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const prefix = 'codex-precompact-probe-';
if (process.argv[2] === 'create' && process.argv.length === 3) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
  const output = path.join(root, 'checkpoints');
  const key = path.join(root, 'test-only.key');
  fs.mkdirSync(output, { mode: 0o700 });
  fs.writeFileSync(key, crypto.randomBytes(32), { mode: 0o600 });
  process.stdout.write(`${JSON.stringify({ root, output, key })}\n`);
} else if (['verify', 'cleanup'].includes(process.argv[2]) && process.argv.length === 4) {
  const root = process.argv[3];
  if (!path.isAbsolute(root) || path.dirname(root) !== os.tmpdir() ||
      !path.basename(root).startsWith(prefix)) {
    throw new Error('refusing to remove anything outside disposable probe storage');
  }
  const info = fs.lstatSync(root);
  if (!info.isDirectory() || info.isSymbolicLink() || info.uid !== process.getuid()) {
    throw new Error('probe storage is not owned by this user');
  }
  if (process.argv[2] === 'cleanup') {
    fs.rmSync(root, { recursive: true, force: true });
  } else {
    const output = path.join(root, 'checkpoints');
    const receipts = fs.readdirSync(output).filter(name => name.endsWith('.json'));
    if (receipts.length !== 1) throw new Error('expected one encrypted checkpoint receipt');
    const receipt = JSON.parse(fs.readFileSync(path.join(output, receipts[0]), 'utf8'));
    if (receipt.verified !== true || receipt.event !== 'PreCompact' ||
        !['manual', 'auto'].includes(receipt.trigger) ||
        typeof receipt.checkpoint !== 'string' ||
        !/^precompact-[0-9a-f-]+\.enc$/.test(receipt.checkpoint)) {
      throw new Error('invalid checkpoint receipt');
    }
    const encryptedPath = path.join(output, receipt.checkpoint);
    if (fs.statSync(encryptedPath).size > 10 * 1024 * 1024) {
      throw new Error('independent smoke verifier is limited to small disposable cases');
    }
    const encrypted = fs.readFileSync(encryptedPath);
    const decipher = crypto.createDecipheriv('aes-256-gcm',
      fs.readFileSync(path.join(root, 'test-only.key')), encrypted.subarray(0, 12));
    decipher.setAuthTag(encrypted.subarray(12, 28));
    const plaintext = Buffer.concat([
      decipher.update(encrypted.subarray(28)), decipher.final(),
    ]);
    if (plaintext.length !== receipt.bytes ||
        crypto.createHash('sha256').update(plaintext).digest('hex') !== receipt.sha256) {
      throw new Error('independent checkpoint verification failed');
    }
    process.stdout.write(`${JSON.stringify({ verified: true, trigger: receipt.trigger,
      bytes: plaintext.length })}\n`);
  }
} else {
  throw new Error('usage: precompact_case.js create | verify/cleanup <exact-root>');
}
