# Mac updater and Vault bug bash — September 23, 2026

This is an evidence ledger, not a claim that all supported Mac or Codex
configurations are certified. Use synthetic Codex homes for destructive tests;
do not modify customer transcripts or a live migration to prove a failure path.

## Current release

Build 16 remains the live, Developer ID signed and Apple-notarized Apple-silicon
beta. Its private ZIP matched the release receipt after upload, its Sparkle
signature verified, and an isolated build-15 app updated in place from that
exact ZIP and relaunched. The public appcast advertises build 16; the unauthenticated
archive endpoint refuses access. See [release readiness](release-readiness.md)
and [in-app update acceptance](in-app-updates.md).

## This bug-bash candidate

| Area | Current evidence | Boundary |
| --- | --- | --- |
| Python regression | Current candidate ran 845 tests: 830 passed, 15 skipped, including the new native install-location check, scheduled external-Vault safeguards, and existing notarization/rotation resume fixtures. The real LaunchAgent case is opt-in and passed separately against the packaged engine. | Release/notarization results printed by mocked fixture tests are not real Apple receipts. Opt-in physical filesystem and clean-account tests are separate; a green suite is not buyer acceptance. |
| Website/commerce regression | 309 passed, 1 skipped after the first-party archive change; 84 focused checkout, entitlement, and update-archive tests passed on merged `main`. | Does not substitute for a browser file save or real in-app installation. |
| App-size archive stream | A 9.6 MB synthetic ZIP-sized response streamed with exact byte count and SHA-256 | Local handler test, not the hosted Production proxy |
| Backup scheduling | Found that a loaded schedule could look healthy with a days-old last success or stalled run; candidate now marks overdue runs unhealthy and disregards receipts from before reinstallation. A real macOS LaunchAgent ran the freshly packaged engine against a disposable Codex home and Vault: the packaged CLI installed the schedule, `launchctl` started it, the second snapshot verified, and the packaged CLI removed the agent. This exposed a Keychain failure when the Codex source folder differed from the signed-in account's home; the generated agent now sets `HOME` to the account home while preserving the explicit source path. The corrected packaged run passed. | The agent was triggered with `launchctl kickstart`, not by waiting through a 24-hour interval or a sleep/restart cycle. The fixture did not use a buyer account's real Codex history. The app package was ad-hoc signed and is not distributable. |
| External Vault disconnect | A synthetic Vault on a real detachable APFS disk image survived eject and remount. The freshly packaged arm64 engine ran the scheduled-backup command: while detached it failed without creating a replacement Vault on the internal volume; status showed unhealthy. After remount, its next capture verified successfully. The schedule is now bound to the verified Vault key ID; a changed destination fails closed. The local app passed strict code-signature verification. A local browser render of an older schedule showed the original Vault path, an unhealthy status, and instructions to turn scheduling off, run a verified backup there, and turn it back on. | The actual LaunchAgent test above used a local disposable Vault; disconnecting a physical USB drive while that agent runs remains untested. The app was ad-hoc signed, not notarized. The rendered check used a synthetic home without Codex history. |
| Standalone CLI dashboard | A browser check found that `codex-migrate serve` linked to Vault routes it does not serve; those links returned 404. The standalone navigation now exposes only its working Mac-migration route, with a regression assertion. | The paid `launch` dashboard continues to expose its real Vault routes. This CLI fix does not prove a packaged buyer install. |
| Updater preferences | Review found that Sparkle's automatic download normally installs on quit. Merged source `c357399` adds a private idle probe and an opt-in quit/retry path, with a final shutdown recheck. CI passed on Python 3.9 and 3.12; the bundled engine from that exact source passed 8 desktop tests with 1 filesystem skip. A running scheduled backup refuses the idle probe and shutdown. A focused HTTP test also proves that a backup starting after the idle probe blocks the final shutdown request. | The existing notarized build-17 ZIP predates this change. Rebuild, notarize, and physically verify unattended installation, including a separately scheduled Vault backup, before release or marketing claims. |
| Packaged helper | Local-test-only app's bundled engine passed 8 desktop cases with 1 filesystem skip | Not a clean-account first launch or notarized buyer installation |
| Real APFS disk pressure | Five opt-in tests passed on an isolated sparse disk image: low space before and after backup blocked replacement; actual ENOSPC retained the original and backup; retry succeeded; end-of-install pressure ended with a verified terminal receipt; forced rollback under pressure was verified. The disposable image was detached and removed. | Synthetic Codex and workspace fixtures, not a buyer account or all possible write-failure points. |
| Packaged permission denial | The build-17 bundled engine passed two real filesystem-denial probes against synthetic Codex and workspace directories without changing the protected files. | Does not prove macOS TCC, Files and Folders picker, or Full Disk Access behavior. |
| Case-sensitive APFS | The build-17 bundled engine rejected a nested `README`/`readme` collision on an isolated case-sensitive APFS image; the image was detached and removed. | One collision safety check, not a full case-sensitive migration. |
| Paid checkout | One real $49 Founder purchase verified. The connected `segerej@gmail.com` inbox has the buyer-delivery email dated September 23, 2026. | That address was also an operator-alert recipient, so deduplication correctly sent it the buyer copy rather than a separate alert. The separate alert to `joshua@segeren.com` has not been inspected. No private download link is recorded here. |
| Browser download | A clean Chrome session exposed a real 403: the purchase page's `no-referrer` policy made its archive form send `Origin: null`. Hotfix PR #27 changed only that page to `same-origin`; CI passed and Production deployment `dpl_9H6PS1DBJZ7JaX8xUWGnuCFbNfYB` is READY. The unmodified live page then verified the paid link and saved the 9,591,579-byte build-16 ZIP. Its SHA-256 matched the page's published `60eff4dcb07088d01c966587e808f21d5fa74b8afb4eba45ed326543f07241f7`. | This proves one real Chrome latest-build download on this Mac. Recheck the original-build choice and other supported browsers during release acceptance. |
| Buyer install guidance | Candidate purchase page and delivery email now explain how to install ZIP or DMG downloads in Applications; 81 focused purchase/commerce tests and 35 site tests passed locally. | This copy is not yet deployed. Physically verify a buyer-installed app is not running from Downloads or a mounted DMG before accepting automatic-update behavior. |
| Unsafe launch location | Candidate app warns before starting its helper when opened from Downloads, a mounted disk image, or App Translocation. Native path-classification checks and Swift typecheck passed. The final Developer ID signed, Apple-notarized build-17 app physically displayed the correct **Move Codex Migrate to Applications** alert when opened as a disposable copy in Downloads and directly from its read-only mounted DMG. The Downloads copy was moved to Trash, test processes stopped, and the image detached. | These are real location-warning UI checks, but not a browser-quarantined first launch, App Translocation proof, or a pristine buyer-account installation. |
| Paid updater proxy | Production `/api/update-archive` accepted the same buyer entitlement and streamed build 16 with the published byte length and SHA-256; unauthenticated access remains denied. | This proves the paid archive path, not automatic installation. |
| Earlier build-17 artifact | Clean `e1552b340214abf3c5218499ff9880c96b8f3b5d` source produced a signed, Apple-notarized, stapled, Gatekeeper-accepted arm64 app and 9,596,033-byte ZIP (SHA-256 `118fbe0c8560cab663e8ad0678ab92b011a3bbea1dcb27e664c281f24db21406`). Bundled engine passed 8 desktop tests with 1 filesystem skip; the separate case-sensitive check above passed. | It predates the idle-install safety change and must not be promoted as the final candidate. A second Sparkle-signing attempt still stopped at the login Keychain authorization prompt and was canceled. Build 17 is not in the release catalog or appcast. |
| Final-source build-17 candidate | Clean `e2f362f` source produced a Developer ID signed, Apple-notarized, stapled arm64 ZIP (9,599,345 bytes; SHA-256 `8bfeba3db03ffa8977118794f03dcde7d7f90074d8aa4a4969e8485eed10a524`). Apple receipt `943e5684-9717-4e5c-9f27-d7d03db83eba` is Accepted. Strict code-signature verification and Gatekeeper passed on this Mac and the second Mac (macOS 26.5); the exact ZIP hash matched there. The bundled engine passed 8 desktop tests with 1 case-sensitive-filesystem skip. | This candidate still lacks a Sparkle archive signature and a paid 16-to-17 installation receipt. It is not in the release catalog or public appcast and must not be advertised or distributed as the update. The second-Mac copy was moved to Trash after verification; no app was launched there. |
| Rotated-key local package | Current PR head `ae2fce7` compiled into an arm64 local-test app. Strict code-signature verification passed and its Info.plist contains the rotated Sparkle public key. The bundled engine passed 9 of 10 desktop tests, with only the case-sensitive-filesystem fixture skipped. A new disposable-home packaged-engine test made two encrypted, verified snapshots, restored both versions to separate folders, and confirmed that authentication and installation identity files were not restored; its test Keychain key was removed. | This is ad-hoc signed and not notarized. It does not prove the key-rotation DMG, buyer installation, clean-account first launch, or scheduled backups on either real Mac. |
| Latest local package | Source `e4a82a3` produced a local-only arm64 build. Strict code-signature verification passed, and its bundled engine passed 10 desktop tests with one case-sensitive-filesystem skip. The opt-in packaged LaunchAgent test above used this build and completed a verified scheduled snapshot. | This build is ad-hoc signed and not notarized or offered to buyers. It does not prove the paid key-rotation update, buyer installation, or first run on a clean account. |
| Rotation packager path check | A direct call against the live signed build 16 exposed that the certificate inspector failed for a relative app path because it changed into a temporary working directory. The packager now resolves the app path before invoking `codesign`; a regression test and the same real-certificate check pass. | This removes a local packaging failure, but does not prove a final notarized DMG or a paid in-app upgrade. |
| Final rotation artifact | Clean source `004d3e28f8d40c656784b17af523bf8237a42d19` produced a Developer ID signed, Apple-notarized and stapled build-17 app (Apple Accepted receipt `ea31c59b-da11-415e-8357-dbfbba7cc198`). A separately signed, notarized and stapled 10,356,114-byte DMG has SHA-256 `861b7f1341d79da87a64e0399a7450904e89241d507ff877dfa1a3ce428efe70` and Apple Accepted receipt `03552619-b676-492b-bd80-80f9a3b79972`. The new Sparkle signature verified against the public key embedded in the app and the exact DMG bytes. A read-only mounted-image inspection passed strict code signing, Gatekeeper, build-number and key checks. The exact image was uploaded to private **sandbox** Blob storage and streamed back with matching size and digest. | Sandbox storage and signature checks do not prove build 16 installs the rotation through Sparkle or that the paid Production proxy serves build 17. The image is not in the live release catalog or appcast. Build 16 remains live. |
| Physical Sparkle rotation smoke | An isolated Developer ID re-signed build-16 app in `/Applications` used a loopback test appcast pointing at the exact final build-17 DMG. Sparkle discovered build 17, fetched the DMG, extracted it, offered Install and Relaunch, and replaced the app in place. The installed bundle reports build 17 and the rotated public key; strict code-signature verification and Gatekeeper both pass as Notarized Developer ID. The relaunched app started its helper. The loopback server was stopped and the test installation moved to Trash afterward. | The old test copy's feed and automatic-check settings were changed locally, so this proves the Sparkle DMG/key-rotation mechanism, not the Production paid-entitlement path or a pristine buyer install. Relaunch produced a second app process that displayed an already-running warning while the first updated process and helper were healthy; eliminate or explicitly accept that duplicate-launch UX before release. |
| Same-copy relaunch UX fix | After the smoke test, source now distinguishes a second process of the same installed bundle from a genuinely different app copy. The duplicate process exits quietly only when another process from that exact bundle path is running; a different copy still gets the existing safety warning. Native Swift check, full Swift typecheck, 847 Python tests (15 skipped), and 318 Node tests (1 skipped) passed. | This changes source after the notarized artifact above. Rebuild, sign, notarize, and retest the final image before release; the existing DMG is now a mechanism proof, not the final candidate. |
| Rebuilt rotation candidate and second physical smoke | Clean source `35c775d4854525a8f49f1c2b78582926821a8c6c` produced a signed, stapled, Apple-notarized build-17 app (Accepted receipt `3d92ba3e-4f16-438a-b332-8a9676983a95`) and 10,354,263-byte DMG, SHA-256 `e61280cf3045db6deb559fa9c70e434513883ef9d731080fcd732fad9d9ae330` (Accepted DMG receipt `9d526d9a-b67e-422c-b598-00f75ca27095`). Its Sparkle Ed25519 signature independently verified against the embedded rotated public key; mounted app passed strict signing and Gatekeeper. The exact image was streamed back from private **sandbox** Blob with matching length and digest. A fresh local build-16 test app in `/Applications` fetched this exact image through Sparkle, offered Install and Relaunch, installed build 17 in place, and relaunched one healthy app process and helper. The embedded release receipt matched the clean source. The exact candidate is now catalogued as `testingOnly` in sandbox; an explicit test confirms it is ineligible for live distribution. | The test app used a loopback appcast and locally changed automatic-check settings. The UI observation immediately after Install and Relaunch timed out, so the absence of a duplicate warning is supported by process state, not a direct captured dialog check. This does **not** prove Production paid authorization, automatic idle installation, pristine-account behavior, or failure paths. Build 16 remains live. |
| Physical updater failure paths | With the same isolated build-16 app, changing one character of the appcast Ed25519 signature caused Sparkle to fetch the image and show its improper-signature error; build 16 remained installed and strictly signed. Restoring the valid signature but changing one byte of a same-length copy of the DMG produced the same rejection, again leaving build 16 intact. With the loopback server stopped, an automatic check advanced its check timestamp but installed nothing; the app and helper stayed running on build 16. The test server was stopped, and all test installations were moved to Trash; the original app preference timestamp was restored. | These are local failure tests, not a revoked/refunded Production entitlement, wrong architecture, low-space installation, or a buyer's private archive stream. No Codex/Vault data mutation was requested; no before/after data digest was taken, so they do not prove byte-level data invariance. |
| Automatic idle-install smoke and deadlock fix | An isolated Developer ID re-signed test app in `/Applications` reported build 16 while carrying build-17 source. It used a loopback appcast, a synthetic purchase token saved by that test app, and the exact notarized rotation DMG. Sparkle downloaded and staged the image. A process sample showed the first implementation blocked inside AppKit's `applicationShouldTerminate` while waiting for a main-queue `terminateLater` reply, so the idle install did not complete. Source now cancels the first quit while the helper shuts down and requests a fresh quit after its termination handler runs. Repeating the physical test installed build 17 in place without manual quit or SIGTERM; the installed app passed strict code signing and Gatekeeper. The test app, fake Keychain item and temporary preferences were removed or restored afterward. | This test does not prove the live build-16 binary, a real paid entitlement, Production proxy, or busy-operation behavior. The automatically installed menu-bar app did not relaunch. The DMG used in this smoke predates the source fix; rebuild and notarize the fix before any release. |
| Idle-install-and-relaunch correction | Sparkle's bundled `SPUUpdaterDelegate` header specifies that returning `YES` from `willInstallUpdateOnQuit` and later invoking its immediate-install callback installs **and relaunches** the app. Source now waits for a successful final `/api/shutdown` and actual helper exit before calling that callback; a busy refusal keeps the helper alive and retries. An isolated Developer ID re-signed test copy reporting build 16 fetched the freshly notarized 10,356,805-byte DMG through a loopback appcast and automatically installed build 17. One relaunched app process and helper were running; the installed source receipt `1d90604cec80b2bf34e8d7d8137c5414cb2dc18e` matched the DMG, and strict signing and Gatekeeper passed. The synthetic Keychain item and temporary preferences were removed/restored; the test app was moved to Trash. | The test app had new client source, a synthetic token, and a loopback feed. It proves the relaunch mechanism, not pristine live build-16 or a Production paid 16→17 upgrade. The installed DMG predates the immediate-install callback change and is superseded as a release candidate. Busy-operation and other failure paths remain open. |
| Final relaunch-source candidate | Clean source `ee40e565d3c5890e818dd2c6cbc2f1e30de97d40` produced a Developer ID signed, stapled build-17 app (Apple Accepted receipt `c36e16c2-637f-498d-9e68-ee3ff44a090b`) and a separately signed, stapled 10,355,906-byte DMG, SHA-256 `bc0da26470268ff37f9d37cd512d0a957dc502b7074256554e5ef051c040d383` (Accepted DMG receipt `22e674ea-e5e0-4b67-bb61-520c2f020221`). The Sparkle signature independently verified against the app's embedded public key. The exact DMG was uploaded to private **sandbox** Blob and streamed back with matching bytes. An isolated re-signed test app in `/Applications`, reporting build 16 and running the same updater code plus synthetic-token diagnostics, fetched this final DMG over a loopback feed, installed automatically while idle, and relaunched one healthy app and helper. The installed source receipt matched `ee40e56`; strict signing and Gatekeeper passed. Test app, synthetic Keychain item and temporary preference changes were removed/restored. | This is a loopback/synthetic-token test, not a pristine live-build-16 or Production paid update. The final candidate remains sandbox-only and unaccepted; busy-operation, paid/revoked entitlement, low-space, clean-account and second-Mac physical checks remain open. |
| Second-Mac artifact acceptance | The final `ee40e56` DMG was copied over verified SSH to the Founder's other Apple-silicon Mac (macOS 26.5). Its 10,355,906-byte length and SHA-256 matched the final receipt. The image was mounted read-only; the embedded build-17 app passed strict code-signature verification and Gatekeeper as Notarized Developer ID. The image was detached and the temporary copy moved to Trash. | The app was not opened and no migration or Vault operation ran on that Mac. This is cross-device artifact validation, not a clean-account first launch or a purchase-link test. |
| Exact live build-16 key-rotation path | The archived build-16 ZIP matched the live catalog SHA-256 `60eff4dc…543f07241f7`; its embedded Sparkle key was the old `xm7MLPjJ…52GwUoHs=`. A test copy changed only its feed URL and was re-signed with the same Developer ID identity; the original app code, build number 16, and old public key were retained. It showed build 17 through the loopback feed, downloaded the exact final DMG, reached **Ready to Install**, installed, and relaunched one app and helper. The installed bundle reports source `ee40e56`, build 17, and the new public key; strict signing and Gatekeeper passed as Notarized Developer ID. The test installation was moved to Trash, its synthetic Keychain entitlement removed, update preferences restored, and the loopback server stopped. | This proves the shipped build-16 updater's signing-key rotation mechanism, not Production paid entitlement or an untouched buyer install: the feed URL and test copy signature were changed locally, and the token was synthetic. The install UI observation timed out after the final click; on-disk and process checks prove installation and relaunch. |

The real LaunchAgent check was rerun against the final `ee40e56` packaged
engine. It created and verified a second encrypted snapshot, but inspection
found that the test harness had only *planned* schedule removal: its CLI call
omitted `--apply`, leaving a loaded job pointing at a deleted temporary home.
That orphan was explicitly unloaded. The harness now applies removal and
asserts the job is absent; the packaged test passes and the account has no
loaded test backup job afterward. This validates scheduled capture and cleanup,
not deferral of an actual in-app update while a backup is running.

The opt-in physical test now also starts the final `ee40e56` packaged helper
and a real LaunchAgent capture of disposable transcript data. While the capture
was running, both the token-protected updater idle probe and final shutdown
request returned 409. After the new encrypted snapshot completed and verified,
the same helper returned 200 for the idle probe and shutdown; the helper exited
cleanly. The temporary LaunchAgent and test key were removed. This proves the
packaged helper's deferral protocol against a live scheduled backup on this Mac,
not a full Sparkle replacement during that backup or the race after helper exit.

The next source change closes that after-exit scheduler window: update-specific
shutdown now takes an owner-only cross-process lock and leaves a bounded update
marker. A scheduled run holds the lock through its capture; if the marker is
present it leaves the last verified snapshot intact and records a deferred
failure instead of starting from the bundle being replaced. The installed app's
next safe-location launch clears the marker and requests an immediate catch-up
run if one was deferred. The marker expires after two hours if the app never
relaunches, so later daily backups are not permanently disabled. Unit tests
cover lock contention, deferral, relaunch catch-up, and expiry. An ad-hoc local
build from the then-dirty working tree passed the real LaunchAgent test: the
packaged helper refused update shutdown during a running capture, accepted it
after completion, and a packaged scheduled run was deferred while the marker
remained. This is **not** yet a notarized release artifact or a full Sparkle
installation-under-contention observation; the native app was edited again
after that local build to restrict marker clearing to safe install locations.

A further source hardening binds the update guard to Sparkle's target
`CFBundleVersion`: the helper accepts an update shutdown only with that build
number, and an installed app clears the marker only when its own build is at
least the target. Reopening the old installed copy therefore cannot resume a
deferred scheduled backup while Sparkle is still replacing it. The full local
Python suite passed (852 tests, 15 opt-in skips), Swift typecheck passed, and
an ad-hoc app built from this source passed the real LaunchAgent/packaged-helper
contention and deferral test. This remains source and ad-hoc evidence, **not**
a signed/notarized buyer update or proof of Sparkle's full replacement path.

Clean source `fc127ec746eecaea4494d4567d91ec28e32b2683` subsequently
produced an Apple Accepted, stapled build-17 app (submission
`a8ffdccc-1967-42a0-90de-22d7f25d9d57`) and a separately signed, Apple
Accepted, stapled rotation DMG (submission
`3f8c2492-9165-4f46-ad8f-60ca0bc15b69`). The final image is 10,371,481
bytes with SHA-256
`f1fba3b4a7b60909d912005187e0c0d97de34a7c1b15df878a5adf1708ac9944`;
Sparkle's rotated key independently verified its signature. Exact bytes were
uploaded to private **sandbox** Blob and read back successfully. The release
catalog marks this image `testingOnly: true` and `accepted: false`; build 16
remains live. This is an artifact and storage receipt, not yet a paid 16→17
installation or clean-account acceptance.

An isolated copy of the exact live build-16 ZIP, installed separately in
`/Applications` with only its feed changed to loopback and re-signed by the
same Developer ID, fetched this exact 10,371,481-byte DMG. A test-only
`SIGTERM` then caused Sparkle to replace that copy in place with build 17;
the installed source receipt matched `fc127ec`, and strict signature and
Gatekeeper checks passed. **This is not a successful normal updater flow:**
the signal bypassed AppKit's guarded quit, the app did not relaunch, and its
old helper briefly remained orphaned. That helper was stopped; the isolated
test app and local feed were moved to Trash/stopped. Repeat the normal
Install-and-Relaunch UI path and busy-operation checks before release. This
test used a loopback feed, not a real paid Production entitlement.

The same final image was copied over the existing authenticated SSH link to
the Founder's other Apple-silicon Mac. Its SHA-256 matched exactly; a read-only
mount passed strict app-signature verification and Gatekeeper as Notarized
Developer ID. The image was detached and the temporary copy moved to Trash.
No app launch, Vault operation, or Codex data mutation occurred there; this is
cross-device artifact verification, not a clean-account installation test.

On September 24, all four current PR #26 CI checks passed (Python 3.9 and
3.12 for both active runs). The live Production update archive returned HTTP
403 with no bearer token and with a forged bearer token. The actual live
`/api/appcast` returned HTTP 200 and still advertised build 16. These are
read-only Production denial and feed receipts; they do not prove revoked-token
behavior, the candidate's paid entitlement path, or native installation.
The Founder's existing paid purchase credential from the buyer-delivery email
also returned HTTP 200 from Production's `entitlement` action. The private
credential was not copied into this ledger or command arguments. This confirms
positive entitlement for the current live release, not paid access to the
unpromoted build-17 candidate.
Sparkle's release verification tool accepted the exact build-17 DMG and its
rotation signature, then rejected a deliberately altered signature for the
same DMG (exit status 1). This proves the local signature verifier's negative
path, not that a running app leaves itself and Vault data untouched after a
failed update attempt.
Review of Sparkle's bundled delegate contract found that `sessionInProgress`
includes appcast checks and incomplete downloads. The candidate's quit path
previously treated either as an impending install and could reserve the Vault
update guard for two hours if the user quit mid-download. Source now reserves
the guard only after a successful download or an actual install handoff;
download failure and cancellation clear readiness. Swift typecheck passed,
15 focused desktop tests passed with 2 opt-in skips, and the full Python suite
passed 853 tests with 15 opt-in skips. Clean source
`479780861710a857dedde8d8de0716999320721a` was then rebuilt: the app is
Developer ID signed, stapled and Gatekeeper accepted under Apple Accepted
submission `2ed37213-04bc-46bf-860e-12ca8d6e457e`. Its one-time rotation
DMG is separately signed, stapled and Accepted under submission
`111275c0-d44e-4ff1-b903-b046db98321f`: 10,368,949 bytes, SHA-256
`8aace2577a612bc9dcc064cad3f63dad57a0ecb02b042ac2b06d1748ad0b8486`.
Sparkle independently verified its new-key signature. The exact bytes were
uploaded to private sandbox Blob and read back byte-for-byte. The catalog entry
is `testingOnly: true`, `accepted: false`; build 16 remains live. JavaScript
tests passed 318 with 1 skip. The operator-only Chrome download check clicked
the private sandbox link without printing it; Chrome saved the expected DMG
filename and all 10,368,949 bytes matched the catalog SHA-256. This is browser
transport, not a buyer entitlement or installation test. A read-only mount of
this exact DMG passed
strict app-signature verification and Gatekeeper as Notarized Developer ID;
the mounted bundle reports build 17. The newly packaged engine passed 14 of
15 focused desktop tests, with only the opt-in case-sensitive fixture skipped.
The image was detached after verification. The same exact DMG reached the
Founder's other Apple-silicon Mac over the authenticated SSH link: its SHA-256
matched, and a read-only mount passed strict signing and Gatekeeper as
Notarized Developer ID with build 17. No app was launched or Codex data
changed there. That mount was detached and its temporary DMG moved to Trash,
so it remains recoverable. The isolated build-16 test app's loopback feed
now points at this exact new DMG, but native Install and Relaunch, paid
build-16-to-17 entitlement, and the broader failure-path matrix still require
direct acceptance before release.

Sparkle's [published appcast format](https://sparkle-project.org/documentation/publishing/)
supports `arm64` as the Apple-silicon hardware requirement; it does not define
`x86_64` as a negative requirement. A local test that substituted `x86_64` in
the feed still installed, so it is **not** evidence of a wrong-architecture
guard. The actual public feed retains `arm64`. Intel-Mac rejection requires a
supported test environment before being called physically verified.

## Release blockers for this candidate

The Founder approved a Sparkle key rotation. A new local signing seed and
public key exist, and the source supports the required Developer ID signed
DMG. A byte-verified, owner-only second copy of the seed exists on the
Founder's other FileVault-enabled Mac. The separate Apple notarization
Keychain remains locked, but a Founder-approved App Store Connect Team API
key with Developer access was created and accepted by `notarytool`; its
private file is owner-only outside Git. The final DMG is notarized and
stored privately for testing, but has not been distributed or promoted.
See [the rotation runbook](sparkle-key-rotation-2026-09-23.md).

1. Inspect the remaining operator-alert inbox and recheck the original-build
   browser choice. The latest-build file save now has a clean Chrome and SHA-256
   receipt; both authenticated Production server streams matched build 16.
2. The rebuilt clean-source app, rotation DMG, Sparkle signature, private
   sandbox Blob readback, and isolated local build-16-to-17 Sparkle install
   pass. Test the same upgrade with a real paid entitlement before promoting
   a live release-catalog entry. The sandbox-only catalog entry is not a live
   release approval. Verify the automatic idle-install path and
   confirm the duplicate-launch warning is absent by direct UI observation.
   Relaunch the app and prove periodic checks still run. If the customer opts
   into automatic installation, prove it waits for an idle helper and does not
   interrupt migration, Vault backup, or restore.
3. Exercise missing/forged/refunded credentials, wrong architecture, corrupt
   archive, invalid Sparkle signature, unavailable network, and insufficient
   disk space against the actual update path. No failure may replace the app
   or mutate Codex/Vault data.
4. On a disposable clean macOS user account, complete quarantined download,
   Gatekeeper open, purchase linking, first Vault backup, recovery-key save,
   scheduled run, search/export, and selected-thread recovery. Do not treat
   an existing developer account as pristine acceptance.
5. Extend the configuration matrix: oldest declared macOS version and newest
   macOS version; supported Codex desktop/CLI layouts; different usernames;
   case-sensitive APFS; permission denial; local, external, and cloud-sync
   folders; low free space; sleep/restart during backup and staging; large
   histories; and direct-cable interruption. Mark an untested combination as
   such rather than assuming support.

The current local Vault guarantees the last verified capture, not zero loss
between snapshots, completed off-device cloud sync, or every Codex UI resume.
The separate desktop pre-compaction proof remains open; a tested Codex hook
timed out fail-open. See [thread history contract](vault-thread-history-contract.md).
On this Mac, `vault schedule-status` reports that automatic Vault backups are
disabled. A read-only check on the other Mac found no Vault backup LaunchAgent
plist or loaded job there either. Neither account should be described as
protected by scheduled Vault backups; setup requires a chosen destination,
verified first snapshot, and recovery-key custody.
