# Codex Vault backup format v1

This document defines the first portable, client-side encrypted Codex Vault
repository. The implementation is open source and intentionally independent of
any operated storage service. A Vault folder may live on a local disk or in a
customer-owned sync folder once that provider keeps all files locally while a
backup runs.

## Security boundary

Version 1 enumerates only regular `.jsonl` files below:

- `~/.codex/sessions`
- `~/.codex/archived_sessions`

It does not enumerate or copy `auth.json`, `installation_id`, SSH material,
logs, caches, runtime locks, repositories, worktrees, or unrelated home-folder
data. Source files are opened without following links and are never changed.

All conversation bytes and the complete snapshot manifest are encrypted before
they enter the Vault folder. The visible repository metadata reveals the format
version, an opaque key identifier, snapshot identifiers, snapshot times, and
encrypted object sizes. It does not reveal conversation text or transcript
paths.

## Key derivation and storage

The macOS helper creates a random 256-bit master key with CryptoKit and stores
it as a generic-password item in macOS Keychain:

- service: `com.segeren.codex-vault`
- account: the random Vault key UUID
- release accessibility: `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` in the
  Data Protection Keychain, under the provisioned Vault helper access group

The previously notarized build-17 candidate used the legacy login Keychain;
its requested accessibility class was not a verified device-only property.
New release builds of this source require a separately provisioned helper app
and use `kSecUseDataProtectionKeychain` for all new keys. On first use of an
existing legacy key, the helper must write and read back the Data Protection
copy, remove the matching legacy item, and fail closed on conflicts or failed
removal. An interrupted transition is retried; an unreadable old item requires
recovery-key import or support. The local-test helper without a profile still
uses the legacy Keychain and is not distributable. Device-only custody remains
an **unverified release claim** until the provisioned helper, legacy-key
transition, and independent-Mac recovery tests physically pass.

The master key is not written into the Vault folder. Its one-time recovery
encoding is `CV1-` followed by unpadded base64url of the 32 key bytes. Users
must keep it in a password manager for recovery on another Mac.

Two 256-bit subkeys are derived with HKDF-SHA256. Both use salt
`codex-vault-v1`; their info values are:

- `authenticated-encryption`
- `private-object-identifiers`

The first key is used with AES-256-GCM. The second is used with HMAC-SHA256 so
object names do not expose ordinary plaintext content hashes.

## Repository layout

```text
Codex Vault/
  vault.json
  latest.json
  backup.lock
  objects/ab/cdef...cvchunk
  manifests/<snapshot-uuid>.cvmanifest
  refs/<snapshot-uuid>.json
```

`vault.json` is public metadata:

```json
{
  "created_at": "RFC-3339 timestamp",
  "format": "codex-vault",
  "key_id": "lowercase UUID",
  "version": 1
}
```

New repositories add `"storage_codec": "lzfse-v1"`. An existing repository
without this field remains readable. Its metadata gains the field only after a
compressed-capable snapshot passes complete verification and before that
snapshot becomes latest. Older app builds reject the extra field rather than
writing an incompatible snapshot. If backup fails before publication, the
last verified reference stays unchanged. Updating this metadata does not
rewrite or remove any older encrypted objects or snapshots.

Every `refs/<snapshot-uuid>.json` is an immutable public reference containing
the snapshot UUID, creation time, format/version and relative encrypted
manifest path. `latest.json` is the only replaced file and is advanced only
after full verification succeeds.

## Chunks

Each regular source transcript is read through an already-open no-follow file
descriptor. The default chunk size is 4 MiB. For plaintext chunk `P`:

1. `id = HMAC-SHA256(identifier_key, P)` in lowercase hex.
2. Additional authenticated data is UTF-8
   `codex-vault:chunk:v1:<id>:<plaintext-byte-count>`.
3. CryptoKit AES-GCM seals `P`; its combined nonce, ciphertext and tag are
   stored at `objects/<first-two-id-chars>/<remaining-id>.cvchunk`.

An existing object is reused only after successful authenticated decryption and
exact plaintext comparison. New objects are read back and decrypted before the
helper reports success. A source file whose device, inode, size, modification
time, or change time moves during reading aborts the snapshot before publish.
Unreferenced encrypted objects from an interruption are harmless and may be
garbage-collected by a later maintenance operation.

## Lossless chunk compression

New writers try Apple's LZFSE codec on each plaintext chunk before encryption.
They use it only when it saves more than 64 bytes; otherwise they retain the
raw v1 chunk. An unchanged raw v1 object is reused rather than rewritten.
Compression is per chunk so appending a transcript does not force an entire
file to be recompressed. The private object identifier of a compressed chunk
is HMAC-SHA256 of the original plaintext under a distinct HKDF-derived key
(salt `codex-vault-lzfse-v1`, info `private-compressed-object-identifiers`,
derived from the v1 identifier key). This domain separation prevents a
compressed object from colliding with its raw v1 counterpart. Its
authenticated data is
`codex-vault:chunk:lzfse:v1:<id>:<uncompressed-byte-count>`; the encrypted
manifest's chunk record adds `"encoding": "lzfse"`. Raw records omit that field.

Readers authenticate, decompress to the exact declared byte count, and verify
the domain-separated identifier and whole-file SHA-256 before accepting or
restoring a snapshot. Unknown encodings fail closed. Existing raw v1 snapshots
remain readable. Compression changes storage size, not the transcript content,
search scope, or restore semantics. The visible snapshot still reports source
plaintext bytes; it is not a promise of a fixed compression ratio.

## Encrypted manifest

The canonical compact JSON manifest contains:

- format `codex-vault-snapshot` and version `1`;
- snapshot UUID and creation time;
- for every transcript: active/archived collection, relative path, byte size,
  source modification time in nanoseconds, SHA-256 of the whole plaintext file,
  and its ordered `{id, size}` chunk list.

The entire manifest is AES-GCM encrypted. Its additional authenticated data is
UTF-8 `codex-vault:manifest:v1:<lowercase-snapshot-uuid>`. The ciphertext is
stored as `manifests/<snapshot-uuid>.cvmanifest`.

## Commit and verification protocol

The writer takes a nonblocking exclusive repository lock, writes or reuses
immutable encrypted chunks, seals the manifest, and then performs a complete
verification pass:

1. authenticate and decrypt the manifest;
2. validate its format and snapshot identity;
3. authenticate and decrypt every referenced chunk;
4. recompute each private chunk identifier;
5. recompute each complete transcript byte count and SHA-256;
6. compare total files, chunks and bytes with the writer's result.

Only then does the writer create the immutable snapshot reference and
atomically replace `latest.json`. A failure never advances the last verified
snapshot and never mutates source data.

## Compatibility contract

Readers must reject unknown format versions rather than guessing. Future
versions may add algorithms, content types or retention metadata, but must not
silently change version 1 semantics. Recovery software must default to a plan,
stage restored plaintext outside live Codex state, verify it, and require
explicit apply intent before replacing anything.

The staging recovery command implements that safe inspection boundary. It
verifies the complete encrypted snapshot first, requires a new or empty output
folder outside both live `~/.codex` data and the Vault repository, reconstructs
each transcript through authenticated chunks, hashes the staged plaintext, and
writes a content-free `restore-receipt.json`.

Live installation is a separate explicit operation after Codex is closed.
Whole-history installation keeps and verifies a rollback copy. Selected-thread
installation re-verifies and stages the complete snapshot, then atomically adds
one exact missing transcript. It does not overwrite or merge an existing thread
identity, and it verifies all pre-existing transcript hashes are unchanged.
