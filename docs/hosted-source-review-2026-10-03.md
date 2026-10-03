# Hosted source-loss review — October 3, 2026

This is a dark, read-only diagnostic for the unreleased hosted backup path.
It helps identify why a smaller source needs attention. It does not authorize
intentional deletion, reset a baseline, upload a snapshot, renew protection,
alter a schedule, or change any existing backup or live Codex history.

## Operator use

With an already enrolled device and its existing Keychain-held individual key:

```sh
./codex-migrate vault --source-home /absolute/account/home hosted-source-review \
  --device-id '<device UUID>' --key-metadata /absolute/path/vault.json --json
```

No bearer or recovery key is accepted on the command line. There is no `--apply`
option. The non-JSON output gives counts only. Deliberately requesting JSON
includes at most 25 opaque thread IDs or relative paths per sample category;
totals remain exact. It never returns conversation bodies, titles, content
hashes, authentication material, or recovery material. Keep a diagnosis private:
relative file names can themselves contain sensitive information.

## Evidence and limits

- Fetch and decrypt the authenticated last-good manifest bound to its account,
  Worker origin and snapshot ID; a failed read is not a first backup. Validate
  catalog paths, IDs, metadata and collection invariants before comparison or
  output. Decryption alone does not prove that those fields are valid.
- Inspect active and archived transcripts, pasted attachments and supported
  paginated SQLite history without staging plaintext or ciphertext. Validate
  JSON and source identities, stream body hashes in memory for exact-byte move
  detection, and compare file and database fingerprints before and after.
- Share the existing staging decisions for missing verified IDs and unidentified
  transcripts. An ID-preserving archive move is not thread loss. Indistinguishable
  unidentified copies are counted, not merged. A vanished entire transcript or
  paginated source still requires review, as it does in staging.
- Report lost-message/large-shrink signals, conflicting current IDs and missing
  referenced pasted text. Fetch the service pointer again before returning;
  changed authority, changed source, corrupt JSON or decryption failure refuses
  a result rather than reporting an empty or green source.

This is point-in-time diagnosis, not an atomic snapshot, complete corruption
detection, or proof that the inspected source was backed up. A local Vault lock
does not stop Codex itself from writing. The normal backup path must repeat its
own checks. No-loss diagnosis cannot turn an incomplete backup into protection.

## Remaining release work

An explicit intentional-deletion confirmation and rebaseline are still absent.
They must bind approval to the reviewed base and exact current source, reject
stale approval, keep older recoverable versions, and never bypass invalid JSON,
identity conflicts, missing attachments or source-change checks. This diagnostic
is not that confirmation and cannot be supplied to the backup path as a bypass.
Buyer UI integration and independent real-cloud acceptance remain pending.

Owner: the primary Codex Backup implementation task. The clean sibling task
worktree is reused; retained through October 4, 2026 for this active release
slice, with pushed source checkpoints and no credentials or test keys in Git.
