const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const test = require('node:test');

const probe = path.join(__dirname, 'fixtures/precompact_encrypted_probe.js');

function fixture(run) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'vault-precompact-'));
  try {
    const output = path.join(root, 'checkpoints');
    const key = path.join(root, 'test-only.key');
    const transcript = path.join(root, 'synthetic.jsonl');
    fs.mkdirSync(output, { mode: 0o700 });
    fs.writeFileSync(key, crypto.randomBytes(32), { mode: 0o600 });
    fs.writeFileSync(transcript,
      `{"type":"session_meta","payload":{"id":"synthetic"}}\n` +
      Array.from({ length: 16000 }, (_, n) =>
        `{"type":"response_item","payload":{"message":"synthetic-${n}"}}\n`).join(''));
    return run({ root, output, key, transcript });
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
}

function invoke({ output, key, transcript }, overrides = {}) {
  const event = {
    hook_event_name: 'PreCompact', trigger: 'manual',
    transcript_path: transcript, ...overrides,
  };
  const result = spawnSync(process.execPath, [probe], {
    input: JSON.stringify(event), encoding: 'utf8', timeout: 15000,
    env: { ...process.env, VAULT_PROBE_OUTPUT: output, VAULT_PROBE_KEY_FILE: key },
  });
  assert.equal(result.status, 0, result.stderr);
  return JSON.parse(result.stdout);
}

test('disposable hook verifies an encrypted checkpoint before continuing', () => fixture(paths => {
  const original = fs.readFileSync(paths.transcript);
  assert.deepEqual(invoke(paths), { continue: true });
  assert.deepEqual(fs.readFileSync(paths.transcript), original);
  const receiptName = fs.readdirSync(paths.output).find(name => name.endsWith('.json'));
  assert.ok(receiptName);
  const receipt = JSON.parse(fs.readFileSync(path.join(paths.output, receiptName)));
  assert.equal(receipt.verified, true);
  assert.equal(receipt.bytes, original.length);
  assert.equal(receipt.sha256, crypto.createHash('sha256').update(original).digest('hex'));
  const ciphertext = fs.readFileSync(path.join(paths.output, receipt.checkpoint));
  assert.equal(ciphertext.length, original.length + 28);
  assert.equal(ciphertext.includes(Buffer.from('synthetic-100')), false);
  const decipher = crypto.createDecipheriv('aes-256-gcm', fs.readFileSync(paths.key),
    ciphertext.subarray(0, 12));
  decipher.setAuthTag(ciphertext.subarray(12, 28));
  assert.deepEqual(Buffer.concat([
    decipher.update(ciphertext.subarray(28)), decipher.final(),
  ]), original);
}));

test('missing transcript fails closed without publishing a checkpoint', () => fixture(paths => {
  assert.equal(invoke(paths, { transcript_path: null }).continue, false);
  assert.deepEqual(fs.readdirSync(paths.output), []);
}));

test('symlinked transcript fails closed without publishing a checkpoint', () => fixture(paths => {
  const link = path.join(paths.root, 'linked.jsonl');
  fs.symlinkSync(paths.transcript, link);
  assert.equal(invoke(paths, { transcript_path: link }).continue, false);
  assert.deepEqual(fs.readdirSync(paths.output), []);
}));

test('non-private checkpoint folder fails closed', () => fixture(paths => {
  fs.chmodSync(paths.output, 0o755);
  assert.equal(invoke(paths).continue, false);
  assert.deepEqual(fs.readdirSync(paths.output), []);
}));
