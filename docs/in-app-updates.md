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

For the exact September 24 build-17 candidate, `python3
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
