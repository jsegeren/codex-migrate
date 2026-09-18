# Codex Vault product plan

## Decision

Codex Vault is the planned umbrella product for preserving local Codex work.
It extends this repository, engine and Mac app; it is not a second competing
application or a rewrite. **Migrate** remains a named, independently purchasable
job inside Vault and remains an important search/landing-page term.

Do not rename the public app, repository or website until the backup and browser
experience is usable. Existing Codex Migrate links and customers must continue
to work after the umbrella name changes.

The product promise is:

> Back up, find, restore and move your Codex work.

## Customer jobs

1. **Find:** browse and search local active and archived Codex conversations,
   including valid transcripts that the current Codex UI does not show.
2. **Back up:** create automatic, versioned, integrity-checked backups without
   copying credentials or installation identity.
3. **Restore:** recover selected conversations or a verified point-in-time set
   through a staged, reversible operation.
4. **Migrate:** safely move the complete supported Codex environment and chosen
   workspaces to another Mac using the existing migration engine.

Continuous merging of two active Codex installations is not part of this
product. That is a different synchronization and conflict-resolution problem.

## Editions and pricing

Keep the offer modular while the market is being proven:

- **Open source:** portable archive format, manual CLI inspection/export,
  verification and recovery primitives.
- **Codex Vault — $5/month or $49/year:** continuously maintained automatic
  backup to a customer-owned folder, browse/search, verified restore, updates
  and best-effort support. Cancellation stops automation and support but leaves
  portable existing backups readable and exportable.
- **Codex Migrate for Mac — $49 one time:** the current complete Mac migration.
- **Complete annual plan:** Vault plus one full migration during the paid year;
  validate willingness to pay before fixing a permanent bundle price.

Existing paid Codex Migrate buyers should receive the first Vault beta or a
nominal upgrade rather than being asked to buy the same foundation twice.

The recurring value is the continuously maintained backup agent, health checks,
format compatibility, version retention and viewer/restore path—not ownership
of the customer's storage bytes. Do not promise lifetime maintenance for a
one-time price. A later **Vault Cloud** tier adds client-side encrypted managed
storage, off-device monitoring and cross-device web access at a higher recurring
price with an explicit storage allowance. Prefer monthly or annual billing over
literal weekly charges.

## Delivery sequence

### 1. Read-only browser and search

- Discover only documented active and archived transcript trees.
- Never read `auth.json`, `installation_id`, SSH material or browser sessions.
- Tolerate versioned transcript event shapes without inventing missing data.
- Keep all content local; provide explicit Markdown and JSON exports.
- Clearly distinguish "stored locally" from "visible in the current Codex UI."
- Export a selected thread to Markdown. Use the browser's print dialog for PDF
  and its native share sheet when file sharing is supported; otherwise download
  the Markdown file for email or another sharing app.

The first implementation slice is the streaming `codex-migrate vault`
inspector/search command. It creates no index or duplicate content.

### 2. Versioned backup

- Take a consistent SQLite snapshot using SQLite's backup mechanism; never copy
  a live database file and assume it is complete.
- Freeze transcript manifests and content hashes around the snapshot.
- Use content-addressed chunks and immutable manifests for incremental backup.
- Exclude authentication, installation identity, logs, caches and runtime locks.
- Require client-side authenticated encryption before recommending cloud-synced
  folders or operated object storage.
- Verify every completed version and make retention policy visible.

The first backup implementation uses immutable 4 MiB chunks (configurable for
testing), private HMAC-SHA256 object identifiers and AES-256-GCM authenticated
encryption. Separate keys are derived for encryption and object identifiers
from a random 256-bit master key held in the macOS Keychain. The encrypted
manifest is verified by completely decrypting and hashing every referenced
chunk before its reference can become `latest.json`. The one-time recovery key
must be stored in a password manager so a new Mac can import it; it is never
written into the backup repository.

The storage folder exposes only format/version metadata, an opaque Keychain key
identifier, encrypted chunks, encrypted manifests and snapshot timestamps. It
does not contain plaintext conversation names or contents. Interrupted work can
leave unreferenced encrypted objects, but cannot replace the last verified
snapshot.

The packaged app now exposes this manual backup flow in the local Vault page:
choose an empty folder or existing Vault, watch content-free progress, receive
the first Vault's recovery key once, and acknowledge that it has been saved.
The UI and its private local APIs are covered by desktop/mobile rendering and
authorization tests.

The automatic-backup slice adds a macOS LaunchAgent only after the latest
snapshot in an existing Vault verifies with a key already present in the local
Keychain. It runs every 24 hours by default, reuses the same backup lock and
publish-after-verification contract, and records only content-free run health.
Disabling it removes the schedule but leaves every snapshot intact. Unattended
runs never create or display a recovery key. Retention controls and richer
cloud-folder health reporting remain the next backup milestone.

### 3. Verified restore

- Default to inspection and a restore plan.
- Require explicit apply intent and Codex shutdown.
- Back up displaced destination state before replacement.
- Stage, verify, install, verify again and roll back on failure.
- Support selected transcript recovery before whole-state replacement.
- Never claim a recovered transcript is visible in Codex until that is tested.

The packaged local Vault page now lists the published backup versions and
restores the selected snapshot into a separate new or empty folder. Every
restore re-verifies the selected encrypted snapshot before recovery. The
operation runs in the background, never replaces live `~/.codex`, and reports
only bounded content-free status.

The whole-history slice adds separately confirmed, whole-history
installation of the chosen verified snapshot. Codex and its CLI sessions must
be closed. Before replacement, the installer records an owner-only crash
journal and moves the existing `sessions` and `archived_sessions` trees into a
private rollback folder. It installs only those two trees, verifies the full
content digest, verifies the displaced history, and automatically restores the
old history if anything fails. A crash or power loss leaves durable state for
an explicit rollback operation. Backup and install also share a local lock so a
scheduled backup cannot race a replacement. Authentication, installation
identity, settings, skills, and unrelated Codex state remain untouched.

Physical-device acceptance on September 18, 2026 confirmed that the current
tested Codex binary could resume a verified whole-history snapshot installed on
a second Mac. The test also confirmed that destination authentication and
installation identity were unchanged and that the displaced history matched
its rollback backup. This does not claim compatibility with every past or
future Codex version or every desktop UI surface. See the
[acceptance receipt](vault-physical-device-acceptance-2026-09-18.md).

Selected-thread recovery is now implemented in both the local browser and CLI.
The customer opens a verified encrypted snapshot into private temporary
staging, searches and reads it, then explicitly restores one exact transcript.
The installer re-verifies the snapshot, requires Codex and its CLI sessions to
be closed, and only adds a missing thread. An identical local thread returns
`already_present`; a matching identity with different bytes fails closed. It
never overwrites or merges an existing conversation. Every pre-existing
transcript is verified unchanged, an owner-only receipt records the addition,
and a final failure removes the newly added file and verifies rollback.

Physical-device acceptance on September 18, 2026 also exercised the additive
selected-thread path across two Macs with an encrypted snapshot and the
receiving Mac's GUI Keychain context. The selected transcript matched the
source bytes, pre-existing history and unrelated configuration stayed
unchanged, the receipt verified, and a repeated plan returned
`already_present`. See the
[selected-thread acceptance receipt](vault-selected-thread-acceptance-2026-09-18.md)
for its deliberately bounded claim.

### 4. Optional Vault Cloud

- The client encrypts before upload; the service never receives plaintext keys.
- The hosted reader either decrypts locally in the browser or is omitted.
- Storage, retention, deletion, export, recovery and provider exit are explicit.
- Keep the local/user-owned destination available so cloud service is optional.

## Launch gate

The umbrella rename is ready only when a nontechnical customer can:

1. see what local history was found;
2. create and verify a backup;
3. find a known conversation through the browser;
4. restore a disposable deleted conversation through the guarded workflow; and
5. understand exactly what is and is not encrypted, uploaded and recoverable.

Until then, public commerce remains the truthful Codex Migrate beta.
