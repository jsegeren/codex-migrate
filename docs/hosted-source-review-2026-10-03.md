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
use the separate verified abandonment/cleanup path first.

### Resolve an ordinary failed upload before reviewing deletion

The dark operator entrypoints now expose that lifecycle without deleting a
journal by hand:

```sh
./codex-migrate vault --source-home /absolute/account/home hosted-pending-upload \
  --device-id '<device UUID>' --key-metadata /absolute/path/vault.json --json

# Only after deciding to abandon this exact unpublished upload:
./codex-migrate vault --source-home /absolute/account/home hosted-abandon-upload \
  --device-id '<same device UUID>' --key-metadata /absolute/path/vault.json \
  --reservation-id '<reservation UUID from inspection>' --apply --json
```

Inspection requests the service receipt for the exact local reservation and
returns opaque IDs and states only. Neither an absent journal nor a published
receipt proves readable backup protection. An already published version must
finish its exact backup verification; this explicit abandonment interface
refuses publication, including a publication racing the earlier inspection.

Abandonment verifies the reservation and individual key again under the run
lock. A changed reservation is refused, never substituted. With a saved setup
binding, the app-facing functions follow verified device renewal without
changing account, Vault or key. Provider text, bearer tokens, grants and local
content are not returned on failure.

`cleanup_pending` is not release: keep the journal and repeat the same exact
abandonment after service cleanup completes. Only `released` retires recognized
temporary upload scratch and that reservation's local journal. A failed reply
uses the existing exact-reservation reconciliation instead of blindly issuing
another action. Published snapshots, live Codex files and unknown scratch stay
intact. These commands do not change the schedule or grant deletion approval.
The acceptance-gated dashboard now exposes these controls. Actual-R2
cleanup/recovery proof remains separate work.

### Acceptance-gated unfinished-upload controls

From the hosted setup's saved-key or verified-backup screen, open **If a hosted
backup is stuck**, then **Check upload status**. The app inspects the exact
local pending reservation with its confirmed individual key. Reviewing status
does not authorize release, intentional deletion, or another upload.

For an unpublished upload, a separate unchecked confirmation enables **Release
this unfinished upload**. The server checks the same opaque reservation again;
an old selection cannot release its replacement. The checkbox resets when an
action starts or the reservation changes. A published upload has no release
control: return to backup for verification, or contact Joshua if a reviewed
deletion upload requires operator help. Do not remove local retry state by hand.

While cleanup is pending, the app preserves the journal, displays that another
backup cannot start, and requires a fresh confirmation to finish cleanup. A
lost reply stays uncertain until another status check. A release request clears
the pending review only after confirmed release. Previously verified receipts, published
backups, live Codex files, schedules, subscriptions and deletion approvals are
not changed by these controls. Returning to backup closes the review only;
it does not abandon an upload. Background enablement is refused while a known
unfinished upload remains. Restart does not replay a release or retain consent.

`tests/manual_hosted_setup_fixture.py` serves the real dashboard on loopback
with clearly labelled simulated states and no file, Keychain, billing or
provider access. It is for rendered interaction review, not hosted acceptance.

The baseline is never erased or treated as a first backup. No remote snapshot
or referenced chunk is deleted; old publication records remain selectable under
the existing service. This source slice does not implement retention deletion
or prove older bytes are recoverable from actual R2 after this operation. The
real-service/independent-Mac recovery proof remains required before release.

## Remaining release work

Intentional-deletion confirmation is still operator-only, not yet buyer UI.
Unfinished-upload controls exist only behind the hosted acceptance gate. Tests exercise real
source inventory/staging and retry logic with synthetic service/crypto boundaries;
they are not production, real-R2 or clean-Mac certification. Integrate a clear
buyer intentional-deletion review/confirmation, prove cleanup against actual R2, complete those independent
recovery checks, and certify the original full release objective.

Owner: the primary Codex Backup implementation task. The clean sibling task
worktree is reused; retained through October 4, 2026 for this active release
slice, with pushed source checkpoints and no credentials or test keys in Git.
