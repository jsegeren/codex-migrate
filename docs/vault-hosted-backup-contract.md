# Optional hosted Vault backup — product and release contract

Status: approved direction with local and synthetic live-R2 transport tests, **not a hosted
service or for sale**. This document does not authorize a production bucket, a
live subscription checkout, or changing the current $49 one-time checkout.
Codex Migrate remains the product name.

## Customer choice

The Mac app will offer two destinations for the *same* portable, encrypted
Vault format:

1. **A folder the customer controls.** It is included in the $49 one-time Mac
   app. That folder may be local, on an external drive, or in the customer's
   cloud-sync provider. A detected cloud folder is not proof that its remote
   copy has synced; a local-only folder does not insure against Mac loss.
2. **Segeren-hosted backup.** A buyer may opt in after buying the $49 Mac app.
   Their **first hosted month is free**. The earlier $10/month flat-price
   direction is under capacity review: a limited $10 tier and a higher tier
   are candidates, but exact allowances and higher-tier price are not approved
   or live. It uploads client-encrypted transcript objects and required
   non-content Vault metadata to operated object storage, then reports the last
   remotely verified snapshot. Existing Mac-app buyers retain their local
   edition, must not repurchase it to add hosting, and receive the same one-time
   free hosted month when they first opt in. The trial and subsequent renewal
   must be clear before enrollment opens. A subscription is not needed to
   browse/search current local history or backups the customer controls.

The hosted tier protects the supported Codex active and archived conversation
transcripts that Vault currently snapshots. It is not a whole-Mac backup, a
backup of selected repository folders, a continuous two-Mac sync or merge
service, or a way to make Codex display every restored thread. Read/export of a
verified snapshot is the guarantee; Codex resume remains best-effort.

Do not display the hosted option as purchasable, or rewrite the live site's
"no subscription" copy, until all release gates below are evidenced. The
existing one-time checkout must remain operable independently.

## Storage and price economics

Use **R2 Standard** as the first provider candidate, subject to a proof with
realistic object counts and a clean-Mac restore. Vercel Blob is a technically
plausible alternative because private signed URLs permit direct transfers, but
its first-time download transfer charges make large disaster restores and a
flat $10 allowance materially riskier. See the
[measured sizing and provider comparison](vault-hosted-economics-2026-09-26.md).
Cloudflare's setup requires a separate Cloudflare account and R2 subscription
checkout, even for included free monthly usage; hosting the website on Vercel
does not itself activate R2. The Founder activated R2 on September 27, 2026,
and a private Standard-class sandbox bucket exists. A synthetic Worker proof
passed all six checks against both Wrangler's **local simulation** and a
**remote binding to real R2** on September 27: upload, checksum check,
immutable reuse, wrong-digest rejection, read-back, and removal. The R2
dashboard showed zero objects and zero bytes afterward. No customer data has
been uploaded; no hosted service or production bucket is live. The sandbox
probe is inert unless explicitly enabled for local development. The temporary
Workers-edit API token used for the proof was deleted immediately afterward;
the account token list showed no remaining user API tokens. This small
proof does not establish authenticated customer uploads, realistic object-count
performance, quota enforcement, retention, or clean-Mac restore. See the
[R2 setup documentation](https://developers.cloudflare.com/r2/get-started/).
An account billing alert now emails the Founder at $10 of Cloudflare spend;
it is an early warning, **not** a hard spending cap. No customer workload is
enabled, and the R2 dashboard showed $0.00 billable usage after the proof.
R2's presigned S3 PUT alone does not satisfy immutable SHA-256 verification:
the candidate transport uses a small authenticated Worker with R2's
checksum-checked conditional PUT. Its $5/month paid-plan minimum matters for
the first few customers. The adapter is still test-only; the full storage
transport and disaster-recovery release gates below remain open.
The draft object Worker now accepts only a short-lived HMAC capability for one
exact method, account/Vault-scoped key, byte length, and SHA-256. Uploads are
stream-size bounded and immutable; reads require matching stored checksum
metadata. Focused tests, a Wrangler **dry-run bundle**, and a synthetic
PUT/reuse/HEAD/GET round trip against Wrangler's **local R2 simulation** pass.
The real Worker path uses Cloudflare's
[FixedLengthStream](https://developers.cloudflare.com/workers/runtime-apis/streams/transformstream/)
so R2 accepts the bounded stream without buffering the object in Worker
memory. It has no deployment configuration, live signing key, or customer
route. The sandbox-only grant issuer checks device identity, purchase,
subscription, Vault ownership, and quota before upload grants; read grants
additionally require membership in a published snapshot. This code is not
evidence of a usable or safe hosted backup yet.
The native Python side now has a test-only `CapabilityHttpStore` that can
transfer frozen encrypted objects to that Worker with exact per-object grants.
It pins one HTTPS origin, refuses redirects and mismatched or out-of-scope
objects, streams recovery reads, and distinguishes a missing object from a
checksum conflict during staging. Loopback HTTP is permitted only when
explicitly enabled for a synthetic test. A dark authenticated grant issuer and
native sandbox client now exist, but there is no live customer endpoint, hosted
schedule, publication path wired to the app, or clean-account hosted recovery
proof. A passing transport test must not change the release status above.
The draft database now records each distinct PUT grant against one active
reservation and refuses conflicting retries or aggregate granted bytes beyond
that reservation. A server-only coordinator consumes a fresh, purchase- and
subscription-checked scope before it signs one exact 30-second PUT; the SQL
gate stops issuing grants when under one minute remains on the reservation.
The draft reservation coordinator can reserve new physical bytes for 55
minutes and extend a still-active reservation for another 55 minutes only
after a fresh device, purchase, and subscription check. The database locks the
account before the reservation, refuses a renewal after downgrade below
retained plus reserved bytes, and never revives expired or cleanup-pending
work. A native sandbox client renews a still-active lease before the next
object in a slow transfer and fails closed if the lease expired. It is not
wired to the installed buyer flow; resume after expiry remains a release
blocker.
Future orphan cleanup must wait beyond the last token's expiry. This is a tested
building block, not an activated grant API: cleanup after failed/expired
reservations and customer identity
enrollment still need the same fail-closed review before deployment.
The first cleanup transition now quarantines an upload reservation only after
its lease has been expired for at least two minutes, under the same
account-before-reservation lock order as upload and publication. It is safe to
retry, blocks renewal and publication, and deliberately leaves both R2 objects
and reserved quota untouched. A cleanup worker still must distinguish objects
in published snapshots or other in-flight grants, prove safe provider deletion
for exclusive orphans, and only then release quota. Quarantine alone is not
orphan cleanup and is not enabled as a customer feature.
After quarantine, the draft database can claim an individual orphan key only
when it is not published and no other reservation has a still-live storage
capability. The claim survives a worker crash and blocks new PUT grants and
publication for that exact key under the account lock. This closes the race
that would otherwise let a cleanup job delete a newly reused object.
The draft database now also has a guarded completion path: a trusted worker
may record exact provider absence for a claimed key, and a reservation may
release its bytes only when every granted key is published or has an exact
absence record at least two minutes old. The claim is removed only in that
same quota-release transaction. These SQL checks do **not** establish R2
absence themselves. An undeployed, operator-only cleanup path now gets a
database-issued, 30-second DELETE capability for one claimed key. The R2
Worker checks the stored size and SHA-256 before deletion and checks HEAD for
absence afterward; only its 204 response lets the operator record absence.
The signer uses the database issue time, so a delayed response cannot mint a
fresh DELETE capability after the claim-release hold. Synthetic tests cover
provider conflicts and a retry after the response to a successful delete is
lost. A separate operator call can ask the database to reclaim reserved bytes;
it succeeds only after every granted key has a published object or an old
absence record, then clears the claims in that same transaction. No cleanup
schedule, production credential, real-R2 deletion proof,
retention policy, or customer-facing abandon flow exists. These functions
must remain dark until those gates and operational review pass.
The September 27 synthetic Wrangler local-R2 probe passed all nine upload,
integrity, read, exact-delete, and already-absent retry flags. Its separate
Node test is in CI. A remote-binding attempt stopped before touching R2
because this session had no Cloudflare API token; local simulation is not a
real-R2 cleanup receipt.
The draft HEAD grant requires a fresh upload entitlement and active
reservation, then checks that the exact key, size, and checksum either belong
to a published snapshot of that Vault or have a PUT grant recorded under this
same reservation. The latter permits read-after-write verification and retry
of a staged object without exposing another staged upload. It grants only a
30-second HEAD probe, not a read or overwrite. A missing or unrecorded object
must use the reserved PUT path; a HEAD response alone never becomes publication
proof. Treating an authorization failure as "absent" would be unsafe. A
server-only decision now returns either a short-lived exact HEAD capability or
`put_required` for an active, owned reservation. Invalid authority returns a
denial, never `put_required`; the latter is not an upload capability and must
be followed by a separate quota-recorded PUT grant. A native sandbox client
consumes this decision, pins the service and Worker origins, reconciles a lost
PUT response by exact HEAD, and requires explicit mutation confirmation. It
is not wired to the buyer UI. A dark `/api/hosted-upload` route joins
reservation, renewal, decision, and exact PUT grant actions. It is available
only when separately enabled in the pinned sandbox; each action rechecks the
device, current Mac-app purchase, and current Stripe Subscription. An empty
subscription-enrollment table binds a future hosted checkout to the purchased
account and its environment. There is no hosted subscription checkout,
enrollment write, customer upload, or live route yet. A later SQL migration
lets an active one-byte reservation grow only when a distinct PUT grant is
needed, under the fresh subscription allowance and account lock. Previously
published chunks can be checked and reused without reserving their bytes
again. This fixes the incremental-capacity dead end near an allowance, but
does not authorize a hosted release.
The draft published-only GET issuer now requires an unrevoked device session
bound to that Vault, consumes a one-use read scope, and signs only an exact
object listed in a published snapshot, using the database-owned size and
checksum. Its capability expires after 30 seconds. A lapsed subscription does
not by itself revoke access to already retained ciphertext, so the customer
can recover/export it during the eventual published retention window; that
window and cancellation policy still require Founder approval. There is no
customer read endpoint, installed-client flow, or clean-Mac restore proof.
The draft recovery discovery reads the owned Vault's last-good pointer, then
enumerates that published snapshot in
256-object pages under the same read authorization, with scoped key cursors,
server-held object checksums/sizes, and the total expected count and bytes.
The recovery client must reconcile the complete inventory before declaring a
download successful; a page alone is not proof of a recoverable snapshot.
A sandbox-only recovery HTTP route now exercises these read boundaries: it
requires a device bearer, rejects cross-origin browser calls, verifies the
current sandbox database identity, and is closed unless explicitly enabled.
It can return the last-good pointer, an inventory page, or one published-object
GET grant. It cannot open against the live database and is **not enabled or
customer-accessible**. Buyer enrollment and app-UI wiring are still absent,
so this route is not a disaster-recovery proof.
The native recovery adapter now validates every inventory page, total count,
total bytes, key order, and snapshot identity before constructing the existing
authenticated download receipt. It requests one exact GET grant at a time and
never persists the device token. A disposable loopback test created an
encrypted Vault, staged it, removed its test Keychain key, fetched ciphertext
through the API-shaped service, imported the separately held recovery key, and
restored a known synthetic thread. This proves local client wiring only; it
does **not** prove a real R2-backed, clean-Mac customer restore.
Do not send a whole staged receipt as one Vercel Function request. A synthetic
JSON receipt matching the measured newer Mac's 21,907 chunks is about 4.03 MB,
close to [Vercel's 4.5 MB request and response limit](https://vercel.com/docs/functions/limitations/);
the two-Mac combined count would be about 6.69 MB if ever treated as one
snapshot. Growing histories will exceed the limit. The authenticated API must
accept bounded, idempotent receipt pages tied to one reservation and snapshot,
then load the complete stored set server-side, validate and provider-verify it,
and publish it in one database transaction. A page acknowledgement is not
protection; only the last-good published pointer is.
The draft now admits at most 512 exact object claims per page under a fresh
authorized scope and stores them transactionally by reservation/key; identical
retries do not add rows or bytes, and a conflicting page rolls back in full.
The native staging result can emit those pages. The server-side coordinator
reassembles the stored set without a whole-receipt web request, checks its
count/bytes/scope, verifies every object with provider-backed batches, and
publishes through a database function that requires exact equality with the
staged rows under the reservation lock. An isolated PostgreSQL fixture passed
21,910 synthetic objects, close to the measured newer-Mac inventory. This
still does not close the hosted release gate: a dark authenticated sandbox
route now admits bounded, idempotent claim pages, but there is no asynchronous
provider-verification/publication job, real-scale R2 run, or clean-account
recovery proof. A page ACK must never appear as a protected backup.
The draft now has a resumable alternative to verifying the whole staged set
inside one web request. A dark sandbox endpoint checks at most 128 exact
objects through the authenticated R2 batch verifier, then records those
specific object facts in PostgreSQL under the active reservation. A failed
request can retry; an incomplete, mismatched, or older-than-24-hours proof
cannot publish. A separate dark publication endpoint rechecks that every
declared staged object has a fresh matching proof before it atomically moves
last-good. The native sandbox adapter can request one step and finalization;
neither is wired to an installed customer schedule or UI. Disposable
PostgreSQL tests cover partial, stale, conflicting, retry, and 21,910-object
finalization. This is a durable verification building block, not a remote R2
scale result or a customer-protection claim. The sandbox client now loops
through bounded steps, renews the active lease during a long run, and retries
using the same reservation after an interruption. A lost final response can be
reconciled against the exact published reservation. Real Worker performance,
clean-account recovery, and installed-app scheduling remain release gates.
The native sandbox adapter can now run one selected encrypted local snapshot
through immutable-object staging, bounded receipt pages, and checkpointed
server verification/publication as one explicitly confirmed operation. The
caller must first reserve and persist the reservation ID for safe retries. The
adapter returns a protection receipt only after the service confirms the
exact object count was published. A failed page or lost final response is not
reported as success; the caller must pass the same reservation ID to retry and
reuse already verified ciphertext objects. This does not create local
snapshots, install a schedule, or
open the buyer UI. It remains a dark integration step, not an available
hosted-backup feature.
An owner-only local journal now wraps that dark adapter. It records the opaque
account, Vault, snapshot, and reservation IDs before staging, retains them
after a failed run, and reuses the same reservation on a later invocation.
It refuses a different snapshot or account instead of silently replacing a
pending run, and removes the journal only after the service's publication
receipt. A crash after reservation but before the journal write can still
leave an unused server reservation; server expiry/orphan cleanup and a
customer-facing retry or abandon flow remain release gates. The journal does
not store the device bearer, recovery key, ciphertext, or conversation text.
The run pins the upload to the journaled snapshot ID, even if the local
`latest` pointer advances before staging starts.
The dark reservation endpoint now also accepts a client-generated UUID that a
future live-history runner can record *before* the network call. Repeating that
exact ID after a lost response returns its original base and expiry without
reserving bytes twice; a foreign, expired, or quarantined reservation is not
revived. The server still freshly verifies device, purchase, and subscription
on each attempt. The older local-Vault mirror runner does not yet use this
pre-recorded-ID protocol, so its crash gap remains; the hosted-only installed
runner and cleanup UX are still release gates.
The separate dark hosted-only runner now records that ID before its first
reserve request, pins the returned last-good base, and retries the same
snapshot after interruption. It accepts a lost publication response only when
the service reports that exact snapshot as published. It does not yet run on a
schedule or in the installed app. After publication it removes only recognized,
owner-only generated journal files; an unexpected file or unreceipted scratch
chunk keeps the run marker and requires review rather than being deleted.
Customer-facing cleanup and failure guidance remain release gates. None of
this makes hosted backup available to customers yet.
An opt-in synthetic macOS scale probe of the hosted-only runner staged and
restored 2,051 transcript files, including one approximately 72 MiB transcript
that crosses the 64 MiB staging window. It completed in 56 seconds on the
older Mac with an in-memory object store. This checks the client file-count and
window path; it does not measure real-R2 latency, 72–76 GB customer-scale
storage, a clean-account restore, or the service's authenticated publication.
A synthetic end-to-end runner test now encrypts two disposable Codex transcripts,
stages the whole object graph without a full local ciphertext Vault, checks
every staged object's bytes and digest before simulating publication, deletes
the test key, re-imports the saved recovery key, downloads, and restores both
transcripts. This connects the new runner to the real native crypto and restore
code, but uses an in-memory object store and the same macOS login. It is not
a real-R2 publication or clean-account recovery receipt. A second synthetic
run pins the first published ID, changes one transcript, reuses the unchanged
chunk, and restores the newer version. That test supplies an in-memory prior
catalog rather than exercising the authenticated remote catalog endpoint.
An explicit sandbox-only abandon operation now lets the same device quarantine
its owned pending reservation, including after a subscription lapses. It
refuses later grants and publication, retains reserved quota, and waits for
the existing operator's replay-window and provider-absence checks before
release. The owner-only journal now retains a `cleanup_pending` tombstone after
quarantine. A read-only, device-owned status query distinguishes active,
quarantined, released, and published reservations even after a subscription
lapses; a lost abandon response can be reconciled against that status. The
next upload refuses to proceed while cleanup is pending and removes the local
tombstone only after the service reports `released`. This is **not** yet a
buyer-facing cancellation/status flow: the installed app does not display this
state, and no cleanup worker is deployed. A local tombstone does not itself
prove object deletion or free quota.
The draft Worker also has an HMAC-bound batch verification route: a service
signs the exact JSON body for at most 512 scoped objects, and the Worker
performs provider-checked R2 metadata reads before returning success. The
request body is capped at 256 KiB; a mismatched, expired, forged, or altered
batch cannot become publication proof. A local test exercises the server
caller against the actual Worker handler. **This is not deployed.** The
512-object R2 subrequest pattern requires the applicable Workers Paid limits
and a realistic remote-scale performance/cost proof before customer use.
R2's published September 2026
pricing is $0.015/GB-month, $4.50/million Class A writes, $0.36/million Class B
reads, and no R2 ingress or direct egress bandwidth charge. The account-wide
free allowance must not be treated as a per-customer subsidy. Presigned direct
upload/download avoids moving the backup bytes through the application host;
hosting/API compute, payment fees, monitoring, failed retries, support, and
retained versions still cost money. See the [R2 pricing](https://developers.cloudflare.com/r2/pricing/)
and [presigned-URL contract](https://developers.cloudflare.com/r2/api/s3/presigned-urls/).

At **75 GB stored**, R2 storage alone is about **$1.13/month** before retention
growth and other costs. At 250 GB it is $3.75/month; at 500 GB it is
$7.50/month. These are pricing scenarios, not measurements of a complete
encrypted backup. Source-folder size does not establish stored size after
compression and version retention; measure actual encrypted bytes on both Macs
before locking an allowance. A $10 flat *unlimited* plan is not defensible. A
**250 GB at $10** is no longer a defensible initial allowance. Candidate
capacity tiers are recorded in the linked economics note, not launched
entitlements: measure incremental version growth and worst-case operations,
then approve the exact allowances and prices before publishing a subscription.
Near the limit, warn and stop new uploads without deleting the last good
snapshot or adding an unapproved overage charge. A second capacity tier
requires a visible choice.

Backblaze B2 remains a fallback candidate. It charges for storage, provides
free upload and usually free egress up to three times average monthly storage,
then charges for excess egress. A first partial month can have a smaller free
egress allowance. Do not claim that B2 restores are always free. See its
[pricing](https://www.backblaze.com/cloud-storage/pricing).

## Data and authority boundaries

- Reuse Vault v1/v2 encrypted chunks, manifests, and immutable references.
  The client creates and verifies a local snapshot before mirroring it. No
  Codex authentication credential, installation identity, repository,
  plaintext transcript, or recovery key enters the hosted service.
  This currently requires enough local space for that encrypted snapshot.
  A hosted-only customer flow cannot simply make a temporary Vault and delete
  its chunks after publication. Chunk IDs are stable for the same plaintext
  and key, but AES-GCM uses a fresh random nonce: recreating a deleted local
  chunk produces different ciphertext under the same remote object key. The
  immutable store correctly rejects that conflict. A synthetic regression
  proves this with the same key and source history. **Keep the current local
  Vault intact** while this adapter is used; do not describe it as a
  low-local-storage hosted-only option. The hosted-only release needs a
  remote-aware writer that reuses the exact previously published ciphertext
  and encrypts each new chunk only once into bounded temporary space. It must
  pass whole-snapshot publication and clean-account restore acceptance before
  that low-local-storage path is offered to buyers. An ambiguous upload cannot
  authorize local deletion: each temporary chunk may be discarded during
  staging only after exact remote read-back and an fsynced, reservation-bound
  receipt; the whole snapshot is not protected until independently published.
  The native helper now has a read-only `plan-chunks` first pass: for each
  plaintext chunk it returns only the keyed raw and (when useful) compressed
  candidate IDs, byte counts, and a whole-file digest. A synthetic parity test
  confirms that a normal stored chunk selects one of those candidates and that
  planning writes no objects. This is a building block, **not** remote-aware
  backup: no service lookup, ciphertext reuse proof, remote publication, or
  local-space reduction is implemented by that command alone. The eventual
  writer must recheck the source file after this first pass and fail closed on
  changes between planning and encryption.
  The native helper also has a separate `store-chunks-with-known` primitive.
  Given an owner-only file of keyed IDs that an authenticated service has
  established belong to this Vault's published objects, it can select a
  matching raw or compressed object without writing local ciphertext; unknown
  chunks are encrypted locally once. It reports which IDs were reused remotely
  and which have local ciphertext to upload, and refuses a source whose whole-
  file digest or length changed after planning. A synthetic test covers both
  legacy raw and compressed reuse, one new chunk, changed content, and an
  exposed lookup file. This is still **not** a hosted-only backup: the buyer
  path does not yet use the new dark authenticated, 256-candidate service
  lookup. That lookup returns size and ciphertext SHA-256 only for objects in
  an already published snapshot of the same purchased, subscribed account and
  Vault; staged and foreign objects are excluded. It grants no read or write
  capability and its database result is not proof that R2 still holds the
  object. An internal client can now run the two-pass plan, bounded published-
  object lookups, and remote-aware native writer for **one stable file**. The
  source identity, length, and digest are rechecked, and a changed transcript
  fails without a snapshot claim. The lookup has a scoped database index so
  it does not scan all prior daily snapshots for each candidate. Whole-
  snapshot assembly, provider re-verification, publication, and restore of the
  mixed inventory remain open. An internal per-file stage HEAD-checks reused
  ciphertext and uploads each new object with exact read-back. A separate
  owner-only, fsynced chunk journal records each verified new object; retries
  HEAD-check journaled objects before omitting their local ciphertext. A
  synthetic interrupted upload now resumes in bounded plaintext/ciphertext
  windows, retaining an ambiguous window's scratch and removing only its own
  exactly journaled scratch after successful staging. The test bounded a
  five-chunk file to two scratch chunks at a time. This is a dark per-file
  building block, not a complete hosted-only backup: no whole-snapshot
  assembly, independently verified publication, clean-Mac recovery, installed
  schedule, or buyer UI is wired to it. The existing local `store-chunks`
  behavior remains unchanged.
  A separate draft graph check now rejects missing, extra, or contradictory
  staged objects relative to a version-2 manifest before receipt-page
  submission. A separate dark manifest stage now durably binds the exact
  encrypted bytes and an authenticated plaintext fingerprint to one snapshot;
  retry reuses those bytes and refuses a changed or missing bound manifest
  rather than resealing under an immutable remote key. The same dark tail stage
  now checks and stages the small Vault metadata and immutable reference,
  then checks their exact object graph against the staged transcripts. It is
  not yet connected to whole-snapshot publication; passing client-side checks
  would not replace the server's R2 proof. A dark whole-snapshot stage now
  enumerates active and archived transcripts, reuses or stages their ciphertext
  in bounded windows, rechecks the complete file set and file identities,
  pins the snapshot time across retries, and assembles the same v2 manifest
  and loss warnings as local Vault. A synthetic two-transcript run needed no
  full local ciphertext Vault, retried without extra uploads, excluded auth
  and installation identity, and refused a transcript changed after staging.
  Its previous catalog remains an explicit input. A dark recovery adapter can
  now authenticate the hosted last-good pointer, reconcile its complete
  published inventory, fetch only the sealed manifest with exact size and
  SHA-256 checks, and decrypt its prior thread catalog locally. An empty
  catalog is accepted as a first backup only when the service explicitly
  reports no published snapshot. A changed last-good pointer or altered
  manifest fails closed. The installed backup path still must call this
  adapter. A draft database guard now captures last-good when a reservation
  starts and rejects any later publication if another upload advanced that
  Vault in the meantime. Overlapping uploads can continue, but the stale one
  cannot call itself protected or silently replace last-good. The dark
  publication endpoints now turn only that exact database conflict into an
  authenticated `409 stale_snapshot`; the native client treats it as a
  distinct failed upload that must be reviewed and abandoned before a new
  reservation. Other or uncertain database failures remain generic failures.
  A reservation now returns the exact last-good snapshot ID captured in the
  same database statement as the quota reservation, or `null` for a first
  backup. The native client can require its authenticated prior-catalog read
  to match that ID before staging transcript bytes; a changed pointer fails
  closed. A versioned owner-only chunk journal now persists that base through
  retry; an older unbound journal cannot be mistaken for first-backup history.
  A dark staging entry point checks the account, Vault, service and device
  identity, then requires the authenticated prior catalog to match the journal
  before staging any transcript. The installed path still must reserve, persist
  this journal, call the staging entry point, and retain the reservation
  identity through publication. These primitives are not an installed backup
  workflow or a customer protection receipt.
  The staged hosted-only object graph has also been recovered through the native
  download, key-import, verification, and restore path in a synthetic test
  without first creating a full ciphertext Vault on the source Mac. That test
  uses an in-memory object store and the same macOS login, not real R2 or a
  separate clean Mac account. The builder does not submit receipt pages or
  publish, and it has not passed real R2 or clean-Mac restore acceptance. A
  separate dark client method can now submit
  this exact staged graph through the existing bounded receipt-page and
  independent server verification path, returning only the server publication
  count. Synthetic lost-page and lost-publication-response retries pass. The
  full builder-to-real-R2 publication and clean-Mac restore chain is still a
  release gate, not a customer feature.
- Keep each local Vault in its own random, account-scoped remote namespace.
  Two Macs may each back up to separate Vaults under one subscription; this is
  not synchronization or a silent merge. Object names and snapshot times are
  visible to the service, as are the random key identifier and Vault-format
  metadata. Titles, conversation paths, and content remain encrypted.
- The master key stays in the customer's Keychain plus their separately saved
  recovery key. Neither Stripe nor the storage service can recover it. Losing
  both makes the ciphertext unrecoverable. Do not silently escrow keys.
- The service authenticates a customer independently of the one-time purchase
  download link, checks an active entitlement and capacity on every upload or
  reuse grant, and signs only short-lived, exact-object PUT/HEAD/GET capabilities scoped
  to that customer's remote Vault. Never ship bucket credentials in the app or
  accept caller-supplied bucket/key prefixes. Treat a presigned URL as a bearer
  secret and keep it out of logs, analytics, and support email.
  A GET for already published, still-retained ciphertext requires the owner's
  unrevoked device session and published-snapshot membership, but not an
  active upload subscription; the retention window remains unapproved.
- A draft server-only session boundary now uses a separate random device token
  whose domain-separated digest, account, Vault, device, expiry (at most 30
  days), and revocation state are stored in PostgreSQL. Each upload-scope
  authorization queries that record for a live, unrevoked session bound to the
  requested Vault, joins its server-stored original purchase, rechecks that
  purchase's current Stripe payment/refund/dispute state, loads the hosted
  subscription enrollment, and must fetch the current Stripe Subscription
  before granting a scope. The checked subscription
  allowance is carried in the one-use server scope; the publication coordinator
  rejects a receipt byte limit above that allowance before provider or database
  work. Aggregate retained-byte quota is still enforced separately by the
  database reservation/publication path. The publication
  coordinator rejects an ordinary client-shaped account/Vault object; it
  consumes a scope minted by this authorization path once, within 60 seconds.
  The actual identity
  enrollment-to-native-client delivery, token rotation and recovery,
  upload HTTP handlers, and trial/billing activation are **not implemented**.
  The recheck is a server-only primitive, not wired to a live endpoint. These draft
  primitives do not make the service customer-accessible or safe to launch.
- A versioned draft purchase-enrollment table now binds each enrolled hosted
  account to one recorded $49 Mac-app purchase, and prevents a purchase from claiming two
  hosted accounts. It uses the purchase session and environment, never email
  equality, to define that relationship. The commerce row is historical
  evidence only: before inserting an enrollment, the future service must
  revalidate the current Stripe payment/refund/dispute state and prove control
  of the purchase email with a short-lived, one-use challenge. Neither this
  schema nor an emailed download link issues a device session or starts the
  hosted trial. The database rejects device sessions for accounts without a
  recorded purchase enrollment. A further draft flow now rechecks the paid
  purchase, sends a separate one-use code to that purchase's email, limits
  issuance to one code per ten minutes and five per day, and atomically claims
  one zero-allowance account, first Vault, and hashed first-device session only
  after accepted delivery and code entry. Uncertain mail delivery never
  activates a code. The dark flow has the native helper generate
  and store the first-device bearer secret in ThisDeviceOnly Keychain *before*
  the claim. It sends only its
  domain-separated digest and random device ID to the server, and verifies
  local retrieval. The server claim returns no bearer secret. The helper can
  list its own stored device IDs and digests without revealing tokens; after a
  restart or lost claim response, the native client can authenticate with a
  saved token and resolve the same account/Vault IDs while the session remains
  valid. This is source
  and disposable-Keychain test evidence, **not** a wired buyer flow. There is
  no buyer-facing enrollment release, edge/IP abuse limit, second-device
  pairing or lost-Mac re-enrollment, hosted trial, subscription checkout, or
  production migration. The hosted option remains unavailable.
- A dark `/api/hosted-enrollment` handler now exposes the existing begin,
  claim, and resolve primitives **only** when the sandbox enrollment flag is
  explicitly open. It pins the test database and test-commerce configuration
  before network work, rechecks the original purchase, sends the one-use code
  only to that purchase email, stores the first-device token digest rather
  than the bearer, and returns only account/Vault/device IDs. A claim still
  starts with zero upload allowance; no live configuration can open the route.
  This is a test seam, not customer enrollment: there is no native buyer UI,
  subscription, second-device pairing, edge abuse protection, or hosted upload.
  A matching native test adapter now requires explicit `apply=True` for the
  email send, Keychain-device creation, and claim. It never puts the device
  bearer in a claim or browser response; only the domain-separated digest
  crosses the claim boundary. If the claim response is lost, it keeps the
  Keychain item and can resolve the same device using its bearer over the
  authenticated route. The native sandbox client can now open upload and
  recovery adapters from that validated Keychain item and the service-resolved
  account/Vault identity, without returning the bearer to browser code. This
  is source-level loopback evidence, not an
  installed-app or live-server enrollment acceptance.
- The dark sandbox now has a lost-Mac/second-device pairing path for an
  *already enrolled* purchase. It freshly rechecks the original purchase,
  emails a one-use 10-minute code to the purchase email, then lists only
  opaque owned Vault IDs and last-good timestamps. After the native helper
  creates a new ThisDeviceOnly bearer, the code can pair its digest to one
  selected existing Vault, without creating a Vault, changing quota, starting
  a trial, revoking the old device, or exposing ciphertext. Another Vault
  requires another code. A lost claim response can be resolved with the same
  saved bearer. This does not replace the separately held encryption recovery
  key. The route is still sandbox-only and closed to buyers; native buyer UI,
  live email abuse protection, session renewal, revocation, and a real
  clean-account remote restore remain mandatory before release.
- A provider-neutral subscription upload gate is implemented for a future
  service to call with a freshly retrieved Stripe Subscription, its
  server-held enrollment record, and a server-held catalog of approved price
  IDs, monthly prices, and byte allowances. Only the exact customer,
  subscription, catalog price and amount, environment, and `trialing` or
  `active` status can pass; paused collection and every other status fail
  closed. The returned allowance is not aggregate usage enforcement, and no
  candidate tier is activated merely by a test fixture. This evaluator does
  not create customer identity, checkout, enrollment, a signed webhook, a
  purchase-refund check, or an upload capability. Those are still mandatory
  before any service is exposed.
- The draft `hosted` database schema reserves upload bytes by an atomic
  account-row update shared by all Vaults. Its publication transaction records
  an independently verified encrypted-object inventory, counts reused objects
  once, consumes the reservation, and advances only that Vault's database
  last-good pointer. A failed publish leaves the previous pointer and counters
  unchanged; an exact retry cannot charge twice or roll back a newer pointer.
  A later draft migration makes reservation and publication apply the freshly
  checked subscription allowance under the same account-row lock. A downgrade
  after reservation cannot use an older stored allowance to publish new bytes;
  disposable PostgreSQL tests cover that transition and preserve last-good.
  Local PostgreSQL 18 tests cover those transitions and concurrent reservations
  across two Vaults. The service-side capacity planner agrees with the same
  physical-byte model. Neither the SQL function nor a client receipt proves
  storage: the service must authenticate ownership and pass only the frozen
  object list it checked with the actual provider. No hosted migration has
  been applied to either Neon commerce environment. The separate migration
  runner requires the exact direct database host and explicit confirmation.
  Expiry does not release reservations automatically: provider cleanup must
  first be proven. Orphan cleanup, retention/deletion, live identity enrollment,
  and authenticated end-to-end R2 service proof are still missing; these draft functions are not a
  customer API or a live entitlement.
- An upload first sends immutable encrypted objects and manifest, then a
  reference. Remote metadata is stored per snapshot under
  `metadata/<snapshot-id>.json`, never overwritten as a single mutable
  `vault.json`; chunks, manifests, and references keep their format paths.
  The client-side staging module checks every local object's exact bytes and
  pins a bounded encrypted object in memory before handing it to the upload
  store, so a same-size file change cannot cause different bytes to be sent
  after snapshot verification. The native helper reports ciphertext digests
  while authenticating the manifest and each chunk; staging compares them
  again before upload.
  The client returns a receipt of object key, byte count, and SHA-256 digest.
  It can compare those claims to authenticated provider-checked metadata without
  downloading unchanged ciphertext; stores lacking that capability retain the
  full read-back path. Either receipt is a client assertion, not service proof.
  The draft metadata path needs an authenticated service-identity test against
  real R2 before use; the synthetic Worker probe does not satisfy that gate.
  Staging does not write
  `latest` or claim protection. The service must independently establish each
  object's exact size and integrity, enforce account scope and required
  metadata/manifest/reference presence, and only then atomically advance the
  database last-good pointer. There is no mutable R2 `latest` object. Do that
  through provider-validated checksums or
  storage-adjacent verification proven against the actual provider; do not
  route whole backups through the website backend on every run, trust a bare
  PUT response, or assume an ETag is SHA-256. A reusable presigned PUT must
  also be constrained so it cannot replace an immutable object during its
  lifetime. The service cannot decrypt the manifest or independently infer its
  chunk list; the native client must first authenticate that list, and the
  clean-account recovery test must prove the combined contract. Failed uploads
  leave the previous verified remote snapshot intact
  and visible as the last good backup. Do not label a backup "protected"
  because a local snapshot or PUT alone succeeded.
- The draft R2 read adapter opens an encrypted object only when the same GET
  returns the expected scoped key, byte count, and stored SHA-256; it streams
  the body without buffering it in a Worker. This is not an authenticated
  download endpoint. The draft native recovery path now checks each downloaded
  ciphertext object's exact size and SHA-256, reuses only matching files after
  interruption, and builds a separate owner-only Vault. It marks the snapshot
  latest only after the native crypto helper verifies its manifest and chunks
  using the separately imported recovery key. Local tests cover missing keys,
  interrupted reads, corrupted objects, unsafe receipts, and linked folders;
  a September 27 synthetic CI run also staged two encrypted snapshots on one
  hosted macOS runner, interrupted the second staging attempt and retried it
  without re-uploading its first new object, then transferred only ciphertext,
  content-free receipts, and a disposable recovery key to a second independent
  runner. The second runner proved recovery fails without the key, restored the
  earlier version, rejected a corrupt newer manifest without marking that
  version latest, and then restored the repaired newer version while the prior
  copy remained readable. This proves cross-Mac ciphertext
  portability through the draft client staging/recovery modules, **not** the
  read path against R2, a real authenticated service, or first use of an
  installed buyer app in a clean account. Those remain release gates.
- The staging client now emits a version-1, content-free receipt with the
  snapshot ID and each remote object's key, byte count, and SHA-256. The
  provider-neutral service validator rejects malformed paths, missing required
  objects, duplicate chunks, bad sizes/digests, a failed independent
  object check, and missing service-owned account/Vault IDs. Verification
  prefixes every relative object key with those server-owned IDs, so a valid
  receipt cannot pass by reading an identically named object in another
  account or Vault. The caller still has to prove the authenticated customer
  owns both IDs; their syntax is not an authorization check. The draft
  server-only coordinator verifies the frozen list in batches of at most 512
  objects and passes it to the database transaction only after every batch
  succeeds. The default Vault chunk is 4 MiB, so a large snapshot can exceed
  the per-invocation R2 subrequest budget; one giant Worker verification call
  is not a valid implementation. The draft R2 adapter checks each 512-object
  batch in waves of 16 concurrent HEAD requests; a unit test bounds that
  concurrency and stops after a failed wave. The sandbox-only authenticated
  publication route now rechecks the purchase and subscription, assembles
  admitted receipt pages inside the service, refuses an inventory shorter than
  the immutable count/byte declaration on its first page, verifies the exact account/Vault-
  scoped objects against R2, and advances last-good only through the matching
  database transaction. The client cannot supply verification proof. This
  route is dark by default and does not make hosted protection available to
  customers. Realistic multi-batch latency, retries, and Vercel function
  duration still require a live R2 proof; a synchronous request may not be
  sufficient for large histories. The immutable receipt declaration detects
  dropped pages from the first-party client; it cannot prove the semantic
  completeness of an encrypted manifest against a deliberately dishonest
  client. Cloudflare currently allows 50 subrequests
  per Free Worker invocation and defaults to 10,000 on
  Paid; see [Workers limits](https://developers.cloudflare.com/workers/platform/limits/).
  The database transaction enforces aggregate
  retained-byte accounting and last-good publication. This is **not a hosted
  release**: realistic-scale provider verification, durable asynchronous
  publication for histories that exceed a request window, and clean-account
  recovery remain unproven. A per-receipt byte bound alone does not enforce
  aggregate quota.
- Preserve old snapshot references under a declared retention policy. Deleting
  an unreferenced chunk requires proof that no retained snapshot needs it.
  Cancellation, payment failure, account deletion, export grace, and final
  deletion need explicit customer-facing rules before billing begins.

## Build sequence and release gates

1. **Freeze the billing contract:** $49 for the app, an explicitly opted-in
   one-time free hosted month for any buyer, then the approved capacity-tier
   subscription while active;
   define the exact trial start and renewal dates, existing-buyer enrollment,
   included bytes, over-limit behavior, taxes/refunds, cancellation/read-only recovery period, and
   storage-region disclosure. Model heavy histories and retained versions
   without relying on account-wide free quotas.
2. **Prove storage transport in sandbox:** bounded encrypted-object inventory,
   resumable and idempotent upload, duplicate avoidance, object-size and
   checksum verification against R2's actual API behavior, per-account quota,
   short-lived direct transfers, tampered/missing-object failure, and no
   secret-bearing telemetry. Do not trust an ETag as a universal SHA-256.
   Prove the draft staging client's metadata-checked path through an authenticated
   service. A daily backup must not redownload an unchanged multi-gigabyte Vault
   merely to reuse it; the service still independently verifies every object
   before publishing protection.
3. **Prove the disaster scenario:** create a first and scheduled snapshot on
   one Mac, lose its local Vault/Keychain context in a clean account or second
   Mac, authenticate, import the separately saved recovery key, download the
   exact remote bytes, verify and read/export a known thread. Repeat with an
   interrupted upload and a corrupt remote object; the prior good snapshot
   must remain recoverable. Include two distinct Mac Vaults under one account.
   For the hosted-only choice, run the scheduled snapshot again after removing
   its temporary local chunks. It must reuse the exact previously published
   remote ciphertext, upload only new chunks, and leave both versions readable
   on a clean Mac. A fresh nonce under an existing object ID must fail rather
   than overwrite or silently count as protected.
4. **Prove commerce and operations:** separate Stripe *subscription* checkout
   and webhook state from the existing one-time purchase; enforce active,
   past-due, cancellation, refund, and dispute states; publish no entitlement
   from a success redirect alone. Exercise a real paid or sandbox end-to-end
   purchase without double-charge. Set provider spend caps/alerts and define
   outage, customer-support, export, and deletion runbooks.
5. **Release truthful UX:** setup clearly distinguishes local-only,
   customer-sync-unverified, hosted-uploading, hosted-verified, and hosted-
   failed states. Show last good remote backup, bytes used/allowance, and a
   recovery-key warning. The current $49 local edition and free source remain
   usable if the hosted service is unavailable or cancelled. Complete an
   independent user-facing review and only then change the public site and
   checkout.

No hosted launch, even for the Founder, is a substitute for the pending current
Mac-app release gates (paid updater, clean-account behavior, and real-history
recovery). Hosted backup must not delay or destabilize that existing offer.
