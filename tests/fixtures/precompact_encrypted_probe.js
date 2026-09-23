#!/usr/bin/env node
// Disposable PreCompact timing probe. Synthetic transcripts only; not a Vault format.
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const STOP = {
  continue: false,
  stopReason: 'The disposable encrypted checkpoint did not verify; compaction was stopped.',
};
const CHUNK = 1024 * 1024;

function writeAll(fd, bytes, position = null) {
  let offset = 0;
  while (offset < bytes.length) {
    const written = fs.writeSync(fd, bytes, offset, bytes.length - offset,
      position === null ? null : position + offset);
    if (written <= 0) throw new Error('checkpoint write failed');
    offset += written;
  }
}

function sameFile(before, after) {
  return before.dev === after.dev && before.ino === after.ino &&
    before.size === after.size && before.mtimeNs === after.mtimeNs &&
    before.ctimeNs === after.ctimeNs;
}

function checkpoint(event) {
  if (event.hook_event_name !== 'PreCompact' ||
      !['manual', 'auto'].includes(event.trigger) ||
      typeof event.transcript_path !== 'string' ||
      !path.isAbsolute(event.transcript_path)) {
    throw new Error('no supported transcript path');
  }
  const directory = process.env.VAULT_PROBE_OUTPUT;
  const keyPath = process.env.VAULT_PROBE_KEY_FILE;
  if (!directory || !keyPath || !path.isAbsolute(directory) || !path.isAbsolute(keyPath)) {
    throw new Error('probe paths are not configured');
  }
  const directoryInfo = fs.lstatSync(directory);
  const keyInfo = fs.lstatSync(keyPath);
  if (!directoryInfo.isDirectory() || directoryInfo.isSymbolicLink() ||
      !keyInfo.isFile() || keyInfo.isSymbolicLink() ||
      (directoryInfo.mode & 0o077) || (keyInfo.mode & 0o077) ||
      directoryInfo.uid !== process.getuid() || keyInfo.uid !== process.getuid()) {
    throw new Error('probe storage is not owner-only');
  }
  const key = fs.readFileSync(keyPath);
  if (key.length !== 32) throw new Error('invalid probe key');
  const sourceFd = fs.openSync(event.transcript_path,
    fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW | fs.constants.O_NONBLOCK);
  let temporary;
  try {
    const before = fs.fstatSync(sourceFd, { bigint: true });
    if (!before.isFile()) throw new Error('transcript is not a regular file');
    const name = `precompact-${crypto.randomUUID()}`;
    temporary = path.join(directory, `.${name}.tmp`);
    const final = path.join(directory, `${name}.enc`);
    const nonce = crypto.randomBytes(12);
    const cipher = crypto.createCipheriv('aes-256-gcm', key, nonce);
    const sourceHash = crypto.createHash('sha256');
    const outputFd = fs.openSync(temporary,
      fs.constants.O_WRONLY | fs.constants.O_CREAT | fs.constants.O_EXCL | fs.constants.O_NOFOLLOW,
      0o600);
    let bytes = 0;
    try {
      writeAll(outputFd, nonce);
      writeAll(outputFd, Buffer.alloc(16)); // Tag is filled after encryption.
      const buffer = Buffer.allocUnsafe(CHUNK);
      for (;;) {
        const count = fs.readSync(sourceFd, buffer, 0, buffer.length, null);
        if (!count) break;
        const plaintext = buffer.subarray(0, count);
        sourceHash.update(plaintext);
        writeAll(outputFd, cipher.update(plaintext));
        bytes += count;
      }
      writeAll(outputFd, cipher.final());
      writeAll(outputFd, cipher.getAuthTag(), 12);
      fs.fsyncSync(outputFd);
    } finally {
      fs.closeSync(outputFd);
    }
    if (!sameFile(before, fs.fstatSync(sourceFd, { bigint: true }))) {
      throw new Error('transcript changed during checkpoint');
    }
    const expectedHash = sourceHash.digest('hex');
    const encryptedFd = fs.openSync(temporary, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
    try {
      if (fs.fstatSync(encryptedFd).size !== bytes + 28) {
        throw new Error('checkpoint length mismatch');
      }
      const header = Buffer.alloc(28);
      for (let offset = 0; offset < header.length;) {
        const count = fs.readSync(encryptedFd, header, offset, header.length - offset, null);
        if (!count) throw new Error('checkpoint header is incomplete');
        offset += count;
      }
      const decipher = crypto.createDecipheriv('aes-256-gcm', key, header.subarray(0, 12));
      decipher.setAuthTag(header.subarray(12, 28));
      const recoveredHash = crypto.createHash('sha256');
      const buffer = Buffer.allocUnsafe(CHUNK);
      let recoveredBytes = 0;
      for (;;) {
        const count = fs.readSync(encryptedFd, buffer, 0, buffer.length, null);
        if (!count) break;
        const plaintext = decipher.update(buffer.subarray(0, count));
        recoveredHash.update(plaintext);
        recoveredBytes += plaintext.length;
      }
      const tail = decipher.final();
      recoveredHash.update(tail);
      recoveredBytes += tail.length;
      if (recoveredBytes !== bytes || recoveredHash.digest('hex') !== expectedHash) {
        throw new Error('checkpoint did not verify');
      }
    } finally {
      fs.closeSync(encryptedFd);
    }
    fs.linkSync(temporary, final); // Exclusive publication; never replace a prior checkpoint.
    fs.unlinkSync(temporary);
    temporary = undefined;
    const receipt = {
      event: 'PreCompact', trigger: event.trigger, bytes,
      sha256: expectedHash, checkpoint: path.basename(final), verified: true,
    };
    fs.writeFileSync(path.join(directory, `${name}.json`),
      `${JSON.stringify(receipt)}\n`, { flag: 'wx', mode: 0o600 });
    const directoryFd = fs.openSync(directory, fs.constants.O_RDONLY | fs.constants.O_DIRECTORY);
    try { fs.fsyncSync(directoryFd); } finally { fs.closeSync(directoryFd); }
    return receipt;
  } finally {
    fs.closeSync(sourceFd);
    if (temporary) {
      try { fs.unlinkSync(temporary); } catch (error) {
        if (error.code !== 'ENOENT') throw error;
      }
    }
  }
}

let input = '';
let responded = false;
function respond(result) {
  if (responded) return;
  responded = true;
  process.stdout.write(`${JSON.stringify(result)}\n`);
}
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => {
  input += chunk;
  if (input.length > 65536) process.stdin.destroy(new Error('hook input too large'));
});
process.stdin.on('end', () => {
  try {
    checkpoint(JSON.parse(input));
    respond({ continue: true });
  } catch (_) {
    respond(STOP);
  }
});
process.stdin.on('error', () => respond(STOP));
