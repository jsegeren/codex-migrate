# In-app updates: release gate

The updater is a candidate until a signed, notarized build has installed a
newer release and relaunched successfully on a real Mac. Do not call this an
automatic updater on the website or in buyer email before that test passes.

## Design

- Sparkle checks the public `/api/appcast` feed. The feed advertises only the
  current approved Apple-silicon release with a valid EdDSA archive signature.
- A buyer links the private purchase email URL once in the Mac app. The app
  verifies it against the server and saves the token in this Mac's Keychain.
  The token is not sent to Sparkle's public feed.
- For the exact first-party `/api/update-archive` URL, the app adds the token
  to an Authorization header. The server rechecks the HMAC, paid Stripe charge,
  and refund/dispute state before issuing a fresh private Blob URL and
  streaming the approved release. It never embeds a private Blob URL or buyer
  token in the appcast.
- Sparkle verifies the archive signature and installs the replacement. The
  app's existing termination hook must shut down its local helper cleanly
  before replacement. An update never changes or migrates Codex/Vault data.
- After an opted-in automatic download, the app holds Sparkle's immediate
  installation callback until its token-protected loopback `/api/update-idle`
  endpoint reports no active migration or Vault worker or running LaunchAgent
  backup. `/api/shutdown` rechecks under the action lock before the helper
  exits; a new helper operation wins the race and cancels the installation.
  Only after confirmed helper exit does Sparkle install and relaunch. Physical
  paid-update acceptance is still required before this behavior is advertised.
- A buyer can still download the newest compatible build from their original
  purchase link, or retrieve the original build. This is the fallback if
  in-app installation cannot complete.

## Required acceptance before release

The September 23 signing-key rotation is a one-time exception to the ZIP
archive steps below: Sparkle requires a separately Developer ID signed and
Apple-notarized DMG because this app enables
`SUVerifyUpdateBeforeExtraction`. Follow
[the rotation runbook](sparkle-key-rotation-2026-09-23.md), then perform the
same paid physical installation and failure-path checks. Build 16 remains live
until those checks pass.

### Private paid-path canary (not release approval)

The update archive handler has an opt-in operator test route for the exact
build-17 sandbox artifact. It remains off unless Production has all three
`COMMERCE_UPDATER_CANARY_RELEASE`, `COMMERCE_UPDATER_CANARY_SHA256`, and
`COMMERCE_UPDATER_CANARY_SESSION` set to the reviewed catalog ID, exact DMG
digest, and one already-paid Founder Checkout session. A fourth setting,
`COMMERCE_UPDATER_CANARY_EXPIRES_AT`, must be a UTC time no more than 48 hours
ahead; the route refuses expired requests even from an older deployment.
A request also needs
that session's valid private purchase bearer token and an exact
`X-Codex-Migrate-Canary` header naming the catalog ID. Payment, refund, dispute,
artifact metadata, and exact private Blob URL are rechecked. The public
appcast and normal paid downloads still use build 16. Do not store the session
ID or bearer token in Git or a test log.

Use the canary only in a disposable test installation; a test-only client/feed
may add the header while exercising the Production proxy. That proves the
paid server stream, not an unmodified buyer app. Keep the physical Sparkle
install and unmodified-client checks separate. After the test, remove all
four Production canary variables, redeploy Production so the active deployment
drops them, and verify the special request is denied
while the public appcast and ordinary buyer downloads still return build 16.
Never use the canary route as a shortcut for catalog promotion or a public
claim that automatic updates are accepted.

For the current `1fdf640` provisioned-Vault build-17 candidate, `python3
ops/paid-update-canary-client.py prepare` verifies the archived live build-16
ZIP and local candidate DMG against their catalog digests, then creates a
**disposable, locally re-signed, unnotarized** build-16 app in `build/`. Only
that test app adds the canary request header; it retains the shipped old
Sparkle key and points to a loopback appcast. `python3
ops/paid-update-canary-client.py serve` binds that feed to `127.0.0.1:8898`
and advertises the exact sandbox candidate through the first-party paid archive
URL. The script contains no bearer token or Checkout session. A real paid test
still needs the temporary four-variable Production canary, the Founder's
purchase linked privately in the app, and physical install/relaunch evidence.
Do not put this locally re-signed copy into buyer delivery or count its
unnotarized Gatekeeper status as first-launch acceptance. Run the feed only
for the active test and stop it afterward. The disposable app retains the
production bundle ID and Keychain service so Sparkle can validate the real
replacement; before opening it, quit other copies, record the current update
preferences, and use an isolated test account or restore those preferences
and remove only the test-linked entitlement afterward. Never erase an
existing buyer entitlement to make the test work.
The harness requires a local byte-verified copy of the archived live build-16
ZIP at `build/live-build16/` and the exact notarized DMG in the candidate
build directory. The test-only catalog entry must be deployed before the
Production canary can select it; a private Blob upload alone is insufficient.
This candidate has passed signing, notarization, the synthetic legacy-key
transition, second-Mac recovery-key decryption, and the limited paid native
process-exit installation canary recorded below. The remaining buyer release gates are
still open.

1. Bump the app's build number; commit the exact source before release build.
   Build with the Developer ID identity, obtain Apple's Accepted notarization
   receipt, staple, and verify Gatekeeper. Keep the prior release available.
2. Sign the **final ZIP bytes** with Sparkle's EdDSA `sign_update` tool. Add the
   signature to the immutable release-catalog entry only after checking the
   archive SHA-256, byte length, embedded version, and accepted Apple receipt.
3. Upload the exact ZIP to private storage and independently read it back;
   verify its byte length and SHA-256. Promote only that catalog entry.
4. Install the buyer download in Applications and open it from there. Check
   that the purchase page and delivery email give the correct ZIP/DMG steps,
   and that the app warns from Downloads, mounted images, and App Translocation;
   do not count an app launched from Downloads or a mounted disk image as an
   updater acceptance test. On a test Mac with an older updater-capable app,
   link a paid test purchase; check manually and via automatic check. Confirm download, signature
   verification, helper shutdown, in-place installation, relaunch, and new
   version. Confirm an active migration, Vault backup, restore, or scheduled
   backup makes shutdown refuse the update safely rather than interrupting
   the operation. Confirm the opted-in idle path actually installs without a
   manual quit, and that it retries after an operation becomes idle.
5. Verify a missing/forged token, refund/dispute, wrong architecture, corrupt
   archive, wrong EdDSA signature, and unavailable network do **not** replace
   the installed app or expose a private artifact. Verify the email purchase
   link still downloads the previous release.
6. Only after this receipt exists, update public copy and buyer email to say
   that linked purchases receive in-app updates. Until then, say only that
   buyers can retrieve compatible newer builds from the original email link.

If a release is bad, stop promotion and restore the prior approved catalog
entry. Do not remove old private artifacts or revoke valid purchases. Sparkle
does not make rollback automatic; publish a corrected build with a strictly
higher build number.

## Paid Production canary receipt — September 24, 2026

- A short-lived Production canary was scoped to the already-paid Founder
  purchase and the exact testing-only build-17 DMG from source `27ef9bf`.
  The public appcast and normal buyer delivery continued to advertise build 16.
- The authenticated first-party `/api/update-archive` request returned HTTP
  200 and exactly 10,376,201 bytes. Its SHA-256 was
  `bf33da502e15a012c287efc5cec6c9b3057bf544c9ebbf8d9aebb1d91d2c1dc6`,
  matching the signed, notarized candidate and private storage readback.
  An anonymous request with the canary header returned 403.
- All four temporary canary environment variables were removed, Production
  was redeployed, and the active deployment again advertised only build 16.
  The canary variables were absent from Production and anonymous canary
  requests still returned 403. No purchase credential or session identifier
  was saved in this receipt.
- This proves the paid Production archive stream, **not** Sparkle installation
  from an unmodified buyer app. The native paid-install, busy-operation,
  clean-account, and failure-path gates above remain open; build 17 remains
  unaccepted and must not be promoted from this receipt alone.

## Native paid-update canary receipt — September 24, 2026

- The disposable, locally re-signed build-16 test client used the old shipped
  Sparkle public key, a loopback appcast, and a test-only canary request header.
  To avoid touching the Founder's Keychain, this disposable copy read the
  already-paid purchase token once from a closed stdin pipe. A test-only
  startup hook requested one background update check. Neither hook exists in
  the shipped build 16 or candidate build 17; no token was put in argv, an
  environment variable, the helper, a file, or Git.
- Production's four canary variables were limited to that paid session, exact
  build-17 candidate and a short expiry. During the test the public appcast
  still advertised build 16, and an anonymous canary archive request returned
  HTTP 403.
- Sparkle downloaded a 10,376,201-byte DMG with SHA-256
  `bf33da502e15a012c287efc5cec6c9b3057bf544c9ebbf8d9aebb1d91d2c1dc6`.
  With automatic updates enabled, a normal quit of the idle build-16 app let
  Sparkle replace it in `/Applications` with build 17. The installed app
  passed strict code-signature and notarized Developer ID Gatekeeper checks.
  It did not visibly relaunch itself after that intentional quit. Opening the
  installed copy manually started build 17 and its helper with the
  `--resume-after-update-build 17` argument.
- Afterward all four temporary Production canary variables were removed and
  Production was redeployed. The live appcast again showed build 16, an
  anonymous canary request still returned 403, and the local feed and
  disposable `/Applications` installation were removed. The original
  developer app was reopened. The purchase-link Keychain item remained absent;
  automatic-check and automatic-update preferences remained enabled.
- This passes **paid native download and install-on-quit for a modified test
  client**. It does not pass unmodified buyer-client linkage, unattended
  install/relaunch while the app stays open, busy-operation retry, failure
  injection, or a clean-account purchase/download/install test. Build 17
  remains unaccepted and the public release remains build 16.

## Provisioned Vault build-17 paid canary — September 25, 2026

- Catalog-only PR #36 placed the exact `1fdf640` provisioned Vault DMG in
  Production's release catalog as `testingOnly: true`, `accepted: false`.
  Production continued to advertise build 16 to ordinary buyers. The
  temporary canary was limited to an already-paid Founder session, the exact
  catalog ID and SHA-256, and a two-hour expiry.
- The authenticated first-party archive stream returned HTTP 200 and exactly
  10,513,015 bytes. SHA-256 was
  `e365674834112941ce1085ec92b78f030f883a0223491e829b51c6c73b03cbf3`,
  matching the notarized DMG and private sandbox-storage readback. The
  disposable Developer ID re-signed build-16 test app used the old shipped
  Sparkle key, a loopback appcast, a test-only canary header, and a paid token
  passed through closed stdin. Sparkle fetched the paid DMG and replaced the
  test app in `/Applications` after its process received `SIGTERM`. That is
  **not** a user Quit action and does not exercise the app's normal termination
  callback or protected helper shutdown. The installed build 17
  embedded source receipt `1fdf640`, passed strict code-signature verification,
  and Gatekeeper accepted it as Notarized Developer ID.
- The app **did not visibly relaunch** after that signal-induced exit. Its old test helper
  remained running independently and was stopped before cleanup. This test
  therefore proves paid native download and installation after process exit,
  not a normal Quit handoff, unattended idle installation, relaunch, or clean
  helper handoff. Because the starting
  client was a modified disposable build 16 launched directly for the canary,
  do not attribute the old-helper behavior to the unmodified buyer client or
  count this as the final update experience.
- All four temporary Production canary variables were removed, and Production
  was redeployed without them. A paid-token canary request again returned
  HTTP 403; an anonymous canary request also returned 403. The public
  `/api/appcast` still advertised build 16. The loopback feed was stopped,
  the test helper was stopped, the disposable app was moved to Trash, and the
  original developer app was reopened. No token or session ID is recorded here.
- **Release gate remains closed.** The unmodified buyer-client purchase-link
  flow, paid native Quit handoff, paid automatic idle install and relaunch,
  busy-operation deferral/retry,
  adverse-path injections, clean-account first install, and scheduled backups
  of real history with off-device recovery on both Macs still require physical
  acceptance. Build 17 remains
  testing-only and unaccepted.
- Separate packaged-engine fixtures with this exact notarized image passed
  restore contention on this Mac and a real scheduled-backup/updater-guard
  interaction on **both** Founder Macs using disposable histories. The
  second-Mac test ran inside its logged-in GUI session, exited 0, and removed
  its temporary Keychain item and LaunchAgent. These checks do not replace a
  full-app Sparkle test during a busy operation, a locked-screen run, or
  scheduled backups of the Founder's real history to an off-device folder.

### Local-only native Quit check with the exact provisioned image

The canary harness also supports `--local-archive`: it verifies the exact DMG
digest, serves that image only from `127.0.0.1`, and builds a disposable
Developer ID re-signed copy of the archived build-16 client. The test uses a
synthetic, format-valid purchase token passed through stdin; it does not call
Production's archive route, create a Keychain entitlement, or require a
Production canary. Its loopback appcast retains the exact Sparkle signature.

On September 25, this local-only build-16 app downloaded and staged the exact
provisioned build-17 DMG. It remained on build 16 while open. A native Apple
Quit event, rather than `SIGTERM`, caused its helper to exit and Sparkle to
replace the app in `/Applications`. The installed app reported build 17 and
embedded source `1fdf640`; strict code-signature verification passed and
Gatekeeper accepted it as Notarized Developer ID. It did not relaunch after
that user-requested Quit. The archived build-16 client does not have build
17's automatic-idle installation code, so this test cannot prove or disprove
that newer path. The loopback server was stopped, the disposable app and build
output were moved to Trash, and the original developer app was reopened.
The unmodified buyer purchase-link, Production paid native Quit, paid automatic
install/relaunch and busy-operation full replacement gates remain open.

### Local-only automatic-idle check with current updater code

The harness's `--current-app` option accepts only the exact signed build-17
source receipt and `--local-archive`. It creates a disposable test wrapper
that reports build 16 to Sparkle while compiling the exact build-17 native
updater code and retaining the provisioned build-17 engine/helper. It replaces
only that test wrapper's Sparkle feed and public key, adds a one-shot background
check and synthetic stdin entitlement, and locally re-signs the wrapper. It
does not alter the notarized DMG, public appcast, buyer app, or Production.

On September 25, with automatic checks and downloads enabled, this current-code
test client fetched the exact signed DMG from the loopback server. Without a
manual Quit, its helper exited, Sparkle replaced the wrapper, and build 17
**relaunched** with one helper carrying `--resume-after-update-build 17`.
The installed source receipt matched `1fdf640`; strict signing and Notarized
Developer ID Gatekeeper checks passed. The temporary update guard was absent
after relaunch. The test app and generated wrapper were moved to Trash, the
loopback feed and image were detached, and the original developer app was
reopened. This is meaningful physical evidence for the new idle path, but the
starting app was deliberately modified and the token synthetic. The real paid
unmodified buyer flow, full-app contention/retry, adverse update paths, and
clean-account first launch still gate the public build-17 release.

### Local-only updater failure checks

The same disposable current-code wrapper was restarted against three
loopback-only failure fixtures: archive HTTP 404, a full-length DMG with its
first byte altered, and an appcast with an incorrect Sparkle Ed25519
signature. Server-side fixture output confirmed an appcast and archive request
in each case (the bad-signature fixture still fetched the archive). After each
attempt, the app remained at build 16 with its helper running and no Vault
update guard. A native Quit then stopped the test app and helper. The loopback
server, mounted image, app and generated wrapper were cleaned up, and the
original developer app was reopened. These are physical negative-path checks
for the modified local wrapper, not proof of a paid buyer-client failure path,
refund/dispute handling, offline reconnection, low disk space during Sparkle
installation, or untouched customer Vault contents.

On September 25, after the temporary Production canary was removed, the
Founder's existing paid purchase token still streamed the normal public
build-16 archive through `/api/update-archive`: HTTP 200, exactly 9,591,579
bytes, SHA-256
`60eff4dcb07088d01c966587e808f21d5fa74b8afb4eba45ed326543f07241f7`.
The token was passed only through closed stdin and was not saved in this test
or recorded in the receipt. This verifies paid archive continuity after
canary cleanup, not the unmodified app's purchase-link UI or build-17 paid
promotion.

### Exact candidate first launch on the second Mac — September 26, 2026

The exact testing-only build-17 DMG from source
`3d990b96fda666ceee9ae548a5e5349a14767a10` was copied to the second
Founder Mac. Its SHA-256 matched the catalog digest
`3697889980f5fcb0a3717752cb0c46068efe0d207b181f6266980f87ae218401`,
and the disk-image checksum verified. No Codex Migrate copy was installed or
running there before this test. The app was copied from the mounted image into
`/Applications`; the image was detached. The installed app reported build 17
and the exact source receipt. Strict code-signature verification, Notarized
Developer ID Gatekeeper assessment, and staple validation passed.

The app launched in the logged-in user session with one native process and
one loopback helper. The authenticated Vault dashboard found a real active
thread by an earlier title even though its current title had changed, and a
separate local-content search found that same thread by message text. No
backup, restore, installation, or migration was running. A normal AppleScript
Quit requested the app's asynchronous helper shutdown; AppleScript reported
`-128` because `applicationShouldTerminate` initially returns
`.terminateCancel` while shutdown completes. Both app and helper subsequently
exited. The copied test media was moved to Trash; the exact installed app was
left in `/Applications` for subsequent protection setup.

This is an installed-app launch and real-history search check on the second
Mac, not a clean *macOS account* test or proof that no UI/Keychain prompt
appeared. It does not exercise purchase-link entry, paid automatic replacement,
or real scheduled backup and off-device recovery. Those release gates remain
open; build 17 remains testing-only and unaccepted.

## Build 16 physical update receipt — September 23, 2026

- The final Developer ID signed, Apple-notarized and stapled arm64 archive is
  `Codex-Migrate-0.1.0-build16-arm64.zip`, 9,591,579 bytes, SHA-256
  `60eff4dcb07088d01c966587e808f21d5fa74b8afb4eba45ed326543f07241f7`.
  The Sparkle Ed25519 signature in `commerce/releases.json` verifies against
  the public key embedded in the signed app. The private Blob upload was read
  back in full with the same byte count and SHA-256.
- An isolated, older build-15 app copy on the first Mac used a local appcast
  carrying that exact signature and archive. Sparkle discovered build 16,
  downloaded the ZIP, offered Install and Relaunch, and replaced the app in
  place. The resulting app reports build 16; strict code-signature verification
  and macOS Gatekeeper both pass as Notarized Developer ID. A relaunched copy
  started its local helper. A concurrent duplicate launch showed the expected
  already-running warning and did not modify migration data.
- The same final ZIP was copied to the second Mac solely for a non-invasive
  artifact check. Its SHA-256 matched, and strict code-signature verification
  and Gatekeeper both passed there. No app or migration was launched on that Mac.
- CI passed on Python 3.9 and 3.12 for the updater implementation. The
  purchase-token, appcast and private-archive failure cases have automated
  coverage. This local physical smoke does **not** by itself prove a paid
  purchase-link update through the Production proxy, automatic scheduled
  installation, or a clean-user-account first launch. Keep those as explicit
  post-deployment checks and retain the original-email download fallback.

## Private paid build-17 canary — September 25, 2026

Catalog-only PR #34 passed main-branch CI and was deployed with build 17
`testingOnly: true`, `accepted: false`; the public appcast stayed on build 16.
A two-hour canary scoped to an already-paid Founder session streamed the exact
10,397,434-byte build-17 rotation DMG (SHA-256
`09159745ee1e5ba08a3dc9e9baf37d23419310a4a49daca16032de890e15dd6e`).
A disposable, Developer ID re-signed copy derived from the archived live
build-16 ZIP retained the old Sparkle public key, used a loopback feed and
test-only canary header, and read the paid token from closed stdin. Sparkle
fetched the Production-paid archive, installed it in place on graceful quit,
and relaunched build 17 with a healthy helper. The installed source receipt,
strict code signature, and Notarized Developer ID Gatekeeper check passed.

The four canary settings and the unaliased canary deployment were removed.
Afterward, the same paid token received 403 for the canary and still downloaded
the exact build-16 ZIP through the normal paid route; the public appcast
remained build 16. This is **not** proof of an unmodified buyer client's
purchase-link setup or idle installation without a quit. Clean-account and
remaining failure-path acceptance still gate public build-17 promotion.
