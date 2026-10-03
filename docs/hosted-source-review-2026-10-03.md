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
  output. The recovery client retains the authenticated catalog format version:
  absent identity/count fields are accepted only for explicit legacy v1, never
  inferred from missing fields in a modern backup. Decryption alone does not
  prove that those fields are valid.
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

## Separate intentional-deletion confirmation

The dark operator path now has two separate commands. Neither a diagnosis nor
an ordinary scheduled run grants deletion permission:

```sh
./codex-migrate vault --source-home /absolute/account/home hosted-prepare-deletions \
  --device-id '<device UUID>' --key-metadata /absolute/path/vault.json --apply

# Read the complete private JSON review file printed above first. Review every
# entry in missingThreadIds, missingFiles and missingAttachments; not a sample.
./codex-migrate vault --source-home /absolute/account/home hosted-confirm-deletions \
  --device-id '<same device UUID>' --key-metadata /absolute/path/vault.json \
  --review-id '<exact review UUID>' --confirm-intentional-deletions --apply
```

Preparation writes a bounded owner-only report under this home's Application
Support; it does not reserve or upload. Confirmation binds one upload to that
report, account, Vault, key, device, source-home/root identity, authenticated
prior snapshot/version and exact sorted content fingerprints. No body or title
is stored in the report. The report includes private IDs, relative paths and
content fingerprints; do not attach it to public support posts.

Confirmation refuses stale source or prior backup, an empty/attachments-only
history, invalid JSON/catalogs, conflicting IDs, shortened remaining threads,
missing referenced attachments, and a baseline without a complete source
coverage claim. Legacy v1 snapshots remain readable but cannot authorize this
loss-metadata-dependent path. The latest authenticated manifest must still match
the review before any PUT; staged content and a fresh source scan must match
before publication. This is point-in-time capture, not an atomic exclusion of
Codex writers. A change after the final check belongs to a later capture.

The pending run persists the approval binding before reservation. Ordinary
manual/background backup cannot resume it. An interrupted active upload needs
the same intact review and unchanged source; a published upload with a lost
reply is reconciled against its exact authenticated published catalog and the
saved digest, even if the source/report subsequently disappeared. Publication
or abandonment consumes the review with an owner-only receipt. A prior ordinary
pending upload cannot be converted into a reviewed upload: keep its state and
use the existing verified abandonment/cleanup path with support first.

The baseline is never erased or treated as a first backup. No remote snapshot
or referenced chunk is deleted; old publication records remain selectable under
the existing service. This source slice does not implement retention deletion
or prove older bytes are recoverable from actual R2 after this operation. The
real-service/independent-Mac recovery proof remains required before release.

## Remaining release work

The confirmation path is operator-only, not yet buyer UI. Tests exercise real
source inventory/staging and retry logic with synthetic service/crypto boundaries;
they are not production, real-R2 or clean-Mac certification. Integrate a clear
buyer review/confirmation and pending-cleanup flow, complete those independent
recovery checks, and certify the original full release objective.

Owner: the primary Codex Backup implementation task. The clean sibling task
worktree is reused; retained through October 4, 2026 for this active release
slice, with pushed source checkpoints and no credentials or test keys in Git.
