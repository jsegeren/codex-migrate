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
memory. It has no
deployment configuration, live signing key, grant-issuing service, or customer
route. The eventual service must check device identity, purchase, subscription,
Vault ownership, quota reservation, and published-snapshot membership before
signing the appropriate capability. This code is not evidence of a usable or
safe hosted backup yet.
The native Python side now has a test-only `CapabilityHttpStore` that can
transfer frozen encrypted objects to that Worker with exact per-object grants.
It pins one HTTPS origin, refuses redirects and mismatched or out-of-scope
objects, streams recovery reads, and distinguishes a missing object from a
checksum conflict during staging. Loopback HTTP is permitted only when
explicitly enabled for a synthetic test. There is still **no authenticated
grant issuer**, customer endpoint, hosted schedule, publication path wired to
the app, or clean-account hosted recovery proof. A passing transport test must
not change the release status above.
The draft database now records each distinct PUT grant against one active
reservation and refuses conflicting retries or aggregate granted bytes beyond
that reservation. A server-only coordinator consumes a fresh, purchase- and
subscription-checked scope before it signs one exact 30-second PUT; the SQL
gate stops issuing grants when under one minute remains on the reservation.
Future orphan cleanup must wait beyond the last token's expiry. This is a tested
building block, not an activated grant API: cleanup after failed/expired
reservations and customer identity
enrollment still need the same fail-closed review before deployment.
The draft HEAD reuse grant requires a fresh upload entitlement and active
reservation, then checks that the exact key, size, and checksum already belong
to a published snapshot of that Vault. It grants only a 30-second HEAD probe,
not a read or overwrite. A missing or unrecorded object must use the reserved
PUT path; a HEAD response alone never becomes publication proof.
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
customer-accessible**. Enrollment and client wiring are still absent, so this
route is not a disaster-recovery proof.
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
still does not close the hosted release gate: no authenticated HTTP route,
real-scale R2 run, or clean-account recovery has passed.
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
  authenticated HTTP handlers, and trial/billing activation are **not implemented**.
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
  no buyer-facing enrollment route, edge/IP abuse limit, second-device
  pairing or lost-Mac re-enrollment, hosted trial, subscription checkout, or
  production migration. The hosted option remains unavailable.
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
  a September 27 synthetic CI run also staged encrypted objects on one hosted
  macOS runner, transferred only those objects, a content-free receipt, and a
  disposable recovery key, then imported the key and restored the known
  transcript on a second independent runner. It first proved the download
  could not be completed without the key. This proves cross-Mac ciphertext
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
  concurrency and stops after a failed wave. The eventual authenticated
  service must bind each batch to the account and Vault, then prove realistic
  multi-batch latency and retry behavior against R2. Cloudflare currently allows 1,000 internal
  service subrequests per Free Worker invocation and defaults to 10,000 on
  Paid; see [Workers limits](https://developers.cloudflare.com/workers/platform/limits/).
  The database transaction enforces aggregate
  retained-byte accounting and last-good publication. This is **not yet an authenticated publish endpoint**:
  real provider checksum behavior, account ownership, entitlement, upload
  grants, and clean-account recovery remain unproven. A per-receipt byte bound
  alone does not enforce aggregate quota.
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
