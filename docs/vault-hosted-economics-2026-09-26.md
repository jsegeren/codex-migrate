# Hosted backup storage and cost validation

Updated October 1, 2026. This public engineering document replaces the earlier
commercial worksheet at the same path so existing links remain valid. Internal
pricing policy, owner-specific measurements, and commercial sensitivities are
kept privately outside this repository. Removing them from the current tree
does not remove earlier Git history; no history rewrite was performed.

Hosted backup is not available or for sale. The existing $49 one-time Mac beta
and checkout are unchanged. This document defines evidence needed for a
reliable service, not a customer price, capacity entitlement, or margin claim.
See the [hosted release contract](vault-hosted-backup-contract.md).

## Measure the supported backup, not the entire Mac

The draft hosted scope includes supported active and archived transcripts,
paginated Codex history, and Codex-owned attachments. It does not include
repository folders, authentication, installation identity, or an entire Mac.
The sizing tool must use the same encoding, compression decisions, and chunk
boundaries as the backup engine. A changing source or skipped source must be
reported as incomplete rather than projected into a customer allowance.

Record initial encrypted object bytes, object count, manifest/metadata bytes,
and completeness for each synthetic acceptance fixture. Check the estimator
against bytes actually written by the native helper. A compression ratio from
one history is not a customer forecast, and a transcript-only estimate is not
the full protected scope.

## Incremental operation model

The format uses immutable encrypted chunks and sealed manifests. Each new chunk
requires an upload and verification; unchanged chunks should be reused from
the authenticated published inventory. Repeated checks must not create full
copies or re-upload unchanged history. Rewrites and compaction can introduce
new chunks: neither filenames nor modification times establish append-only
behavior or actual unique growth.

The draft native path batches bounded object grants under short-lived
device/reservation authorization. This reduces first-party requests but does
not eliminate per-object authorization, provider operations, quota checks,
periodic remote scrubs, or independent publication verification. A lost upload
acknowledgement may still incur a provider request. An immutable retry does not
necessarily add retained bytes.

The target is a 30-minute incremental check while the Mac is awake, not a
30-minute full upload or a certified maximum recovery-point age. Sleep,
offline time, source changes, upload duration, and failed verification can
leave the latest good backup older. The UI must show the actual last-good,
offline, overdue, and failed states.

## Provider comparison boundary

R2 Standard is the current candidate. Evaluate retained storage, write/read
operations, verification, and full disaster restores. Direct R2 egress does
not have a per-GB fee, but read operations and any separate delivery services
still matter. Private Vercel Blob is another possible transport; include its
applicable transfer, origin, cache, and operation charges rather than assuming
that downloads are free. Verify current rates and account terms before making
a commercial decision; no rate table here should be treated as an invoice.

Sources: [R2 pricing](https://developers.cloudflare.com/r2/pricing/),
[R2 Workers API](https://developers.cloudflare.com/r2/api/workers/workers-api-reference/),
[Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/),
[Workers limits](https://developers.cloudflare.com/workers/platform/limits/),
[Vercel Blob pricing](https://vercel.com/docs/vercel-blob/usage-and-pricing/),
and [Vercel signed URLs](https://vercel.com/docs/vercel-blob/vercel-signed-urls).

Account-wide free allowances are shared, not a separate allowance for every
subscriber. Fixed provider minimums and rounded billing units must be included.
No hosted offer should depend on remaining within a free daily request ceiling.

## Evidence to collect

Measure initial backup, unchanged check, ordinary edit, large rewrite,
interrupted retry, full restore, and scheduled runs on independent Macs.
Collect at least 24-hour and seven-day unique retained-object growth before
using retained-version forecasts in an offer. Keep diagnostics content-free:
no titles, conversation text, credentials, recovery keys, or source paths.

- Per-run elapsed time, source bytes actually read, and novel ciphertext bytes.
- Attempted and confirmed service and object requests, upload bytes, and retries.
- Verified unique retained bytes, manifests, incomplete/orphan objects, and
  retention/deletion effects.
- Last-good snapshot age, source coverage warnings, missed/failed runs, and
  independent recovery verification.
- Provider request/CPU/storage costs, database/API/email/monitoring costs,
  payment fees, and allocated operational/support/recovery costs.

The current client counters are diagnostic evidence, not a provider invoice.
Scheduled run receipts include attempted recovery-service calls and Worker GETs
used to read the prior manifest, including network failures. A request rejected
locally before a network attempt is not an object operation. These counts do
not measure downloaded bytes, service-side verification, enrollment/rotation,
database operations, or provider CPU; those still require separate evidence.
Re-staged plaintext is not a complete disk-I/O counter; claimed ciphertext can
include reused objects; a confirmed upload does not prove new retained bytes.
The bounded local sample history can have gaps that a measurement review must
detect. Reconcile it with service and provider records before drawing a cost
conclusion.

## Usage ledger and customer terms

The draft SQL ledger records retained-byte changes and UTC daily peaks. A day
before the first recorded event is unknown, not zero. The ledger does not prove
that the provider holds every object, account for untracked orphan objects, or
establish usage before its baseline. It is not a live invoicing meter.

Reconcile exact account/Vault-scoped retained objects, reservations, cleanup,
and billing-period coverage against the actual provider before using usage in
an invoice. Count reused ciphertext once within a Vault; do not assume
cross-Vault deduplication. Never bill raw folder size or upload volume as
retained encrypted storage without a separately disclosed matching contract.

Final customer prices, storage/retention allowance, usage units, renewal dates,
first included month, cancellation/recovery period, taxes/refunds, and any
resource limits must be approved and clearly disclosed before enrollment or
charging opens. There is no customer-set spending-cap feature. Do not silently
pause protection, delete the last verified snapshot, or add unapproved charges.
Customer-owned-folder backup remains available without hosting fees.

## Acceptance still required

Primitive and synthetic encrypted R2 roundtrips are useful transport evidence,
not a completed authenticated customer service. Release still requires:

1. Customer enrollment and authorized publication through the real service.
2. Independent-Mac saved-key import, download, verification, and read/export.
3. Unattended incremental operation with honest source coverage and failure
   reporting; a bad capture must not displace the last good recovery version.
4. Real provider reconciliation, measured retained growth and restore costs,
   and the approved customer billing/retention contract.
5. An independently reviewed, notarized customer package and update path.
