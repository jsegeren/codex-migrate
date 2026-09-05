#!/usr/bin/env node
// Receipt-bound operator upload, not a signing or clean-Mac acceptance claim.
// Defaults to a local plan. --apply uploads only to this product's private store.
const fs = require('node:fs/promises');
const { constants } = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { createHash } = require('node:crypto');
const blob = require('@vercel/blob');

const ROOT = path.resolve(__dirname, '..');
const STORE = 'Ksz4f7gOIH2qRu9I';
const ORIGIN = `https://${STORE.toLowerCase()}.private.blob.vercel-storage.com`;
const LIMIT = 100 * 1024 * 1024;
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
function prepareArchive(receipt, bytes, id) {
  if (!receipt || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/.test(id || '') ||
      receipt.build_mode !== 'release' || receipt.source_dirty !== false ||
      !/^[a-f0-9]{40}$/.test(receipt.source_revision || '') ||
      !['arm64', 'x86_64'].includes(receipt.architecture) ||
      !/^\d+\.\d+\.\d+$/.test(receipt.version || '') ||
      !/^[1-9]\d*$/.test(receipt.bundle_version || '') ||
      receipt.notarization?.status !== 'Accepted' ||
      !/^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(receipt.notarization?.id || '') ||
      !Number.isFinite(Date.parse(receipt.built_at))) throw Error('invalid_release_receipt');
  const filename = `Codex-Migrate-${receipt.version}-build${receipt.bundle_version}-${receipt.architecture}.zip`;
  if (receipt.artifact !== filename || filename.length > 125 || !Buffer.isBuffer(bytes) ||
      bytes.length < 4 || bytes.length > LIMIT || bytes.readUInt32LE(0) !== 0x04034b50 ||
      !/^[a-f0-9]{64}$/.test(receipt.sha256 || '') || digest(bytes) !== receipt.sha256) {
    throw Error('archive_receipt_mismatch');
  }
  return { id, kind: 'signed-notarized', source: receipt.source_revision,
    sha256: receipt.sha256, filename, size: bytes.length,
    pathname: `live/${receipt.sha256}/${filename}`, accepted: false };
}
async function readOwned(file, maximum) {
  if (await fs.realpath(file) !== file) throw Error('linked_input');
  const handle = await fs.open(file, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const info = await handle.stat();
    if (!info.isFile() || info.uid !== process.getuid() || info.mode & 0o022 || info.size > maximum) throw Error('unsafe_input');
    return await handle.readFile();
  } finally { await handle.close(); }
}
async function uploadCandidate(candidate, bytes, sdk = blob) {
  // Called with prepared, immutable in-memory bytes. A changed or partial remote
  // object never becomes accepted and is never overwritten on a retry.
  if (!Buffer.isBuffer(bytes) || bytes.length > LIMIT || candidate.accepted !== false || candidate.kind !== 'signed-notarized' ||
      !/^Codex-Migrate-\d+\.\d+\.\d+-build[1-9]\d*-(arm64|x86_64)\.zip$/.test(candidate.filename || '') ||
      candidate.sha256 !== digest(bytes) ||
      candidate.pathname !== `live/${digest(bytes)}/${candidate.filename}` || candidate.size !== bytes.length) {
    throw Error('invalid_upload_candidate');
  }
  const url = `${ORIGIN}/${candidate.pathname}`;
  const options = () => ({ storeId: STORE, access: 'private', useCache: false,
    abortSignal: AbortSignal.timeout(30000) });
  let remote = await sdk.get(url, options());
  if (!remote) {
    await sdk.put(candidate.pathname, bytes, { ...options(), addRandomSuffix: false,
      allowOverwrite: false, contentType: 'application/zip' });
    remote = await sdk.get(url, options());
  }
  if (!remote || remote.statusCode !== 200 || remote.blob.url !== url ||
      remote.blob.pathname !== candidate.pathname || remote.blob.size !== candidate.size ||
      remote.blob.contentType !== 'application/zip') {
    await remote?.stream?.cancel(); throw Error('uploaded_metadata_mismatch');
  }
  const hash = createHash('sha256'); let length = 0;
  for await (const chunk of remote.stream) {
    length += chunk.length;
    if (length > candidate.size) throw Error('uploaded_size_mismatch');
    hash.update(chunk);
  }
  if (length !== candidate.size || hash.digest('hex') !== candidate.sha256) throw Error('uploaded_checksum_mismatch');
  return { candidate, bytesVerified: length, accepted: false,
    next: 'Complete exact-artifact signed clean-Mac acceptance, then review the catalog entry. Checkout remains closed.' };
}
async function main(args = process.argv.slice(2)) {
  let directory, id, apply = false;
  while (args.length) {
    const flag = args.shift();
    if (flag === '--build-dir' && !directory) directory = args.shift();
    else if (flag === '--release-id' && !id) id = args.shift();
    else if (flag === '--apply' && !apply) apply = true;
    else throw Error('invalid_arguments');
  }
  if (!directory || !id) throw Error('build_dir_and_release_id_required');
  directory = path.resolve(directory);
  if (path.dirname(directory) !== path.join(ROOT, 'build') || await fs.realpath(directory) !== directory) throw Error('invalid_build_directory');
  const receipt = JSON.parse((await readOwned(path.join(directory, 'build-info.json'), 16384)).toString('utf8'));
  // Validate basename before touching the archive path supplied by the receipt.
  if (!/^Codex-Migrate-\d+\.\d+\.\d+-build[1-9]\d*-(arm64|x86_64)\.zip$/.test(receipt.artifact || '')) throw Error('invalid_release_archive');
  const bytes = await readOwned(path.join(directory, receipt.artifact), LIMIT);
  const candidate = prepareArchive(receipt, bytes, id);
  execFileSync('git', ['cat-file', '-e', `${candidate.source}^{commit}`], { cwd: ROOT, stdio: 'pipe', timeout: 10000 });
  if (!apply) return { candidate, planOnly: true, uploaded: false, accepted: false };
  return uploadCandidate(candidate, bytes);
}
module.exports = { prepareArchive, uploadCandidate, readOwned, main };
if (require.main === module) main().then(value => console.log(JSON.stringify(value, null, 2))).catch(() => {
  // Do not print provider exceptions, credential-bearing URLs or filesystem data.
  console.error('Release upload stopped. Check the signed build receipt and private storage configuration. No catalog entry was enabled.');
  process.exitCode = 1;
});
