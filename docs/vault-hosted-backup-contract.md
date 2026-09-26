# Optional hosted Vault backup — product and release contract

Status: approved direction, **not implemented or for sale**. This document does
not authorize a production bucket, a live subscription price, or changing the
current $49 one-time checkout. Codex Migrate remains the product name.

## Customer choice

The Mac app will offer two destinations for the *same* portable, encrypted
Vault format:

1. **A folder the customer controls.** It is included in the $49 one-time Mac
   app. That folder may be local, on an external drive, or in the customer's
   cloud-sync provider. A detected cloud folder is not proof that its remote
   copy has synced; a local-only folder does not insure against Mac loss.
2. **Segeren-hosted backup.** An optional subscription priced at **no less than
   $10/month**, additive to the Mac app. It uploads already encrypted Vault
   objects to operated object storage and independently reports the last
   remotely verified snapshot. Existing Mac-app buyers retain their local
   edition and may add hosting without repurchasing it. A subscription is not
   needed to browse/search current local history or backups they control.

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
realistic object counts and a clean-Mac restore. Its published September 2026
pricing is $0.015/GB-month, $4.50/million Class A writes, $0.36/million Class B
reads, and no R2 ingress or direct egress bandwidth charge. The account-wide
free allowance must not be treated as a per-customer subsidy. Presigned direct
upload/download avoids moving the backup bytes through the application host;
hosting/API compute, payment fees, monitoring, failed retries, support, and
retained versions still cost money. See the [R2 pricing](https://developers.cloudflare.com/r2/pricing/)
and [presigned-URL contract](https://developers.cloudflare.com/r2/api/s3/presigned-urls/).

At the measured **approximately 75 GB** first restorable backup across the
Founder's two Macs, R2 storage alone is about **$1.13/month** before retention
growth and other costs. At 250 GB it is $3.75/month; at 500 GB it is
$7.50/month. A $10 flat *unlimited* plan is not defensible. A **250 GB included
allowance** is the initial candidate, not a launched entitlement: measure
incremental version growth and worst-case operations, then approve the exact
allowance and price before publishing a subscription. Near the limit, warn and
stop new uploads without deleting the last good snapshot or adding an
unapproved overage charge. A second capacity tier requires a visible choice.

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
  visible to the service, but titles, paths, and content remain encrypted.
- The master key stays in the customer's Keychain plus their separately saved
  recovery key. Neither Stripe nor the storage service can recover it. Losing
  both makes the ciphertext unrecoverable. Do not silently escrow keys.
- The service authenticates a customer independently of the one-time purchase
  download link, checks an active entitlement and capacity on every capability
  grant, and signs only short-lived, single-object PUT/GET capabilities scoped
  to that customer's remote Vault. Never ship bucket credentials in the app or
  accept caller-supplied bucket/key prefixes. Treat a presigned URL as a bearer
  secret and keep it out of logs, analytics, and support email.
- An upload first sends immutable encrypted objects and manifest, then a
  reference. Advance a remote `latest` pointer only after remote completeness
  and integrity have been checked. Failed uploads leave the previous verified
  remote snapshot intact and visible as the last good backup. Do not label a
  backup "protected" because a local snapshot or PUT alone succeeded.
- Preserve old snapshot references under a declared retention policy. Deleting
  an unreferenced chunk requires proof that no retained snapshot needs it.
  Cancellation, payment failure, account deletion, export grace, and final
  deletion need explicit customer-facing rules before billing begins.

## Build sequence and release gates

1. **Freeze the billing contract:** exact monthly price (at least $10), included
   bytes, over-limit behavior, taxes/refunds, cancellation/read-only recovery
   period, and storage-region disclosure. Model heavy histories and retained
   versions without relying on account-wide free quotas.
2. **Prove storage transport in sandbox:** bounded encrypted-object inventory,
   resumable and idempotent upload, duplicate avoidance, object-size and
   checksum verification against R2's actual API behavior, per-account quota,
   short-lived direct transfers, tampered/missing-object failure, and no
   secret-bearing telemetry. Do not trust an ETag as a universal SHA-256.
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
