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
Production's `entitlement` action separately returned HTTP 403 for a forged
credential. A refunded purchase was not exercised against a real buyer.
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
The exact packaged build-17 engine also passed the opt-in detachable-APFS Vault
test: when its synthetic Vault volume was absent, scheduled backup failed
without creating a local replacement; after remount, the next capture verified.
The real macOS LaunchAgent fixture then passed with that packaged engine and
cleaned up its temporary job. A read-only check afterward found no loaded
Vault backup agent or account LaunchAgent plist on this Mac. These synthetic
fixtures do not establish buyer-account backup protection or a full update
while a physical external disk disconnects.

The latest PR #26 head `394a7f9` completed all four CI checks on September 24
(Python 3.9 and 3.12 across both active runs). An isolated copy of the exact
live build-16 app downloaded the current 10,368,949-byte candidate through a
loopback appcast. Sending SIGINT to **that copy's helper only** caused its
normal AppKit termination path to run; Sparkle replaced the app in place with
build 17. Its installed executable matched the clean-source candidate byte
for byte, the embedded receipt named `4797808`, and strict code-signature and
Gatekeeper checks passed. It did **not** relaunch: this was build 16's
install-on-quit behavior, not a manual Install and Relaunch or build 17's new
idle-install callback. No paid Production entitlement was involved.

A second isolated copy used the candidate's current updater code, changed only
its reported version and feed for a local 16-to-17 test, and was re-signed by
the same Developer ID. It fetched the exact image with automatic checks
enabled. A synthetic Keychain item created by the `security` CLI then blocked
its main thread in `SecItemCopyMatching` during Sparkle's automatic-install
handoff; this is **not** an idle-install acceptance result and must not be
called a product Keychain failure without an app-owned purchase-link test.
The synthetic item was deleted, the isolated processes were stopped, both
test apps and the loopback feed were moved to Trash, and the test-only 60-second
Sparkle check interval was removed. No buyer purchase or Codex/Vault data was
changed.

The idle test was then repeated with an **app-owned** synthetic token. A
disposable Developer ID re-signed copy of the candidate's current client
source reported build 16 and used only a loopback feed; its test-only bootstrap
called the same `UpdateEntitlement.save` routine the app uses after purchase
verification. This avoided the CLI-created item's Keychain prompt. With
automatic checks and downloads enabled, Sparkle fetched the exact current
10,368,949-byte DMG, installed build 17 without a manual quit, and relaunched
one app and one helper. The installed executable and bundled engine matched
the clean-source candidate byte for byte, its source receipt named `4797808`,
strict signing and Gatekeeper passed as Notarized Developer ID, and the Vault
update guard was absent after relaunch. The test app and loopback feed were
moved to Trash, the synthetic Keychain item was deleted, and no test process
or port remained. This proves the candidate's idle-install-and-relaunch
mechanism with an app-owned token, **not** a paid Production entitlement,
busy-operation deferral during the full Sparkle replacement, or a pristine
buyer install.

A full replacement-under-contention smoke used a new disposable home and Vault
with the exact packaged engine. An actual scheduled-run process had written
its `running` receipt and held `update.lock` when it was deliberately paused
with SIGSTOP (simulating a stalled backup). A Developer ID re-signed test copy
of the candidate client pointed its helper at that disposable home, used an
app-owned synthetic token, and reported build 16. Sparkle fetched the exact
10,368,949-byte DMG but left the app and helper on build 16 while the job held
the lock for over a minute. After SIGCONT, the job completed a 156,714,428-byte
encrypted snapshot, and the packaged engine verified that snapshot. Only then
did Sparkle replace the test app, install build 17, and relaunch one app and
helper. Installed executable and engine bytes matched the clean-source
candidate; strict signing and Gatekeeper passed.

The test-only client had supplied a synthetic `--source-home`; the real
installed app correctly dropped that test modification and therefore could
not clear the synthetic home's guard on its own. While that guard remained, a
packaged scheduled run recorded a safe deferred failure and left the verified
snapshot unchanged. Launching the exact packaged engine with the synthetic
home and `--resume-after-update-build 17` cleared the guard and triggered the
loaded LaunchAgent, which made a second verified snapshot. This proves the
packaged catch-up mechanism but **not** its automatic execution on a buyer's
real home. The disposable LaunchAgent was unloaded, Vault and entitlement
test keys were deleted, and app, feed, and synthetic home were moved to Trash;
no real Codex data or second-Mac work was changed. Migration and restore
contention, a real paid entitlement, and clean-account acceptance remain open.

On September 24, the complete Python regression suite was run with
`CODEX_MIGRATE_TEST_ENGINE` set to the exact build-17 packaged engine from
clean source `479780861710a857dedde8d8de0716999320721a`: 853 tests passed,
14 opt-in tests skipped. The same app bundle reports build 17, passes strict
code-signature verification, and is Gatekeeper accepted as Notarized Developer
ID. All four PR #26 CI checks on head `ce6282f` passed (Python 3.9 and 3.12).
This is broad packaged-engine regression evidence, not a paid Production
update, a clean-account run, or execution of the skipped physical fixtures.

On September 24, two additional opt-in physical fixtures ran against that
exact packaged engine. A disposable APFS Vault volume was detached before a
scheduled backup: the run failed safely without creating a replacement Vault
at the now-missing mount path. After remount, the next run created and verified
an encrypted snapshot, and the fixture removed its test Keychain key. A
separate disposable **case-sensitive APFS** image let the packaged inventory
engine see both `README` and `readme` in one workspace; it rejected the
collision without changing either file. Both tests passed, and the mounted
images were detached. These are synthetic filesystem checks, not evidence for
an actual buyer's external disk, cloud-sync completion, or a paid app update.

Sparkle's [published appcast format](https://sparkle-project.org/documentation/publishing/)
supports `arm64` as the Apple-silicon hardware requirement; it does not define
`x86_64` as a negative requirement. A local test that substituted `x86_64` in
the feed still installed, so it is **not** evidence of a wrong-architecture
guard. The actual public feed retains `arm64`. Intel-Mac rejection requires a
supported test environment before being called physically verified.
The exact build-17 candidate's app executable, packaged engine, and Vault
CryptoKit helper each report `arm64` through `lipo -archs`. This verifies the
three primary native executables, not every bundled framework or an Intel-Mac
install rejection.

On September 24, the narrowly scoped paid-stream canary from PR #28 passed
all four CI jobs and merged to `main` as `8d74587`. A Production-environment
deployment was staged without assigning the public domain. Its appcast still
advertised build 16, and an unauthenticated archive request returned 403. For
the Founder's real, already-paid purchase session, an exact-release,
short-lived canary request returned the private build-17 DMG: 10,368,949 bytes,
SHA-256 `8aace2577a612bc9dcc064cad3f63dad57a0ecb02b042ac2b06d1748ad0b8486`,
matching the notarized sandbox catalog entry. The same paid token with a wrong
candidate header returned 403. No bearer token or private download URL was
recorded in Git or this receipt. All four canary environment settings were
then removed. A clean Production deployment was staged; the same exact paid
canary request returned 403 there. That clean deployment was promoted to
`migrate.segeren.com`, where the public appcast still advertises build 16,
unauthenticated archive access returns 403, and the Founder's paid token
downloads the current 9,591,579-byte build-16 archive. The temporary canary
deployment was then removed without affecting the live domain; the test DMG
copy was moved to Trash after its digest was checked. The canary proves the
hosted paid server stream for the exact candidate, **not** Sparkle installing
that release through an unmodified buyer app, scheduled installation on a
buyer Mac, or approval to publish build 17.

A quarantined disposable copy of that exact notarized build-17 candidate was
accepted by Gatekeeper but opened under App Translocation. First open showed
a Keychain authorization prompt for a pre-existing updater entitlement item
and left AppKit unresponsive while the prompt was pending. This account is
not a pristine buyer account, so the prompt is not evidence that every buyer
would see it. Source now performs automatic Keychain reads with a noninteractive
authentication context, saves a newly linked purchase off the AppKit thread,
and refuses to start Sparkle or the local helper from unsafe launch locations.
An initial local ad-hoc build from Downloads exposed a second helper-start
path through reopening; that path was closed. A rebuilt ad-hoc test app then
showed only the move-to-Applications warning, started no helper, and exited
when the warning was dismissed. Both disposable test copies were moved to
Trash. This is local-source evidence, **not** a notarized replacement artifact
or pristine-account proof; the existing build-17 candidate does not include
these fixes and remains unpublished. The full Python regression suite passed
854 tests with 15 opt-in skips, and Swift typecheck passed without warnings.

Clean source `90f1cb29e377675f730aeee1207d6cb5fe7f090b` then produced a
Developer ID signed, Apple Accepted and stapled build-17 app (submission
`5f19c6ed-d861-4e0c-9d1e-d3f0e71bcfee`) and a separately signed, Apple
Accepted and stapled rotation DMG (submission
`77cc1e96-8b28-446b-836d-cafbf8941b03`). The image SHA-256 is
`f9d4f5b580a7637f3a5dcc73e58598760824f7d8475934a71bb05379b0a76f51`;
its Sparkle signature independently verified with the app's embedded public
key. From the mounted read-only DMG, this exact app showed the unsafe-location
warning, started no helper, and exited after dismissal. A separate installed
copy in Applications started its helper, with its AppKit main thread idle in
the event loop rather than blocked in Keychain; the test copy was stopped and
moved to Trash. An initial manually quarantined ZIP extraction stalled before
app code after macOS displayed an approval dialog; its test process was stopped.
A second disposable copy with a current quarantine timestamp was accepted by
Gatekeeper and launched from an actual `/AppTranslocation/` path. It showed
only the move-to-Applications warning, started no helper, and exited after
the warning was dismissed. That copy was moved to Trash. This proves the
translocated code path under a synthetic quarantine flag, **not** a complete
browser-download first launch or pristine buyer-account installation. The new
image was uploaded to the private sandbox store and all 10,372,434 bytes were
read back with the matching SHA-256. Its catalog entry is `testingOnly: true`
and `accepted: false`; the public appcast remains build 16. A pristine-account
paid update is still required.

The exact 10,372,434-byte DMG was copied by verified SSH to the Founder's
second Apple-silicon Mac (macOS 26.5). Its SHA-256 matched the local release
receipt. The DMG passed code-signature, staple, and Gatekeeper checks there;
its read-only mounted app passed strict code-signature and Gatekeeper checks,
reported build 17, and its app, packaged engine, and Vault helper each reported
`arm64`. The image was detached and the disposable remote copy moved to Trash.
The app was not opened on that Mac, so this is cross-device artifact acceptance,
not a second-Mac first-run, Vault, migration, or updater result.

The exact build-17 DMG's **bundled engine** was then exercised from a read-only
mount on this Mac. All 16 focused desktop tests completed (15 passed, one
case-sensitive-filesystem skip), including two encrypted synthetic snapshots,
versioned restore without authentication or installation identity, and a real
dashboard/helper startup and shutdown. The opt-in real macOS LaunchAgent test
created and verified a scheduled capture with the packaged engine, then
removed its disposable schedule; read-only checks found no loaded test job or
account LaunchAgent plist afterward. The opt-in external-volume test detached
its synthetic APFS Vault, confirmed a scheduled run failed without creating a
replacement local Vault, remounted it, and verified the next capture. A
separate case-sensitive APFS volume let the packaged engine reject a nested
`README`/`readme` collision without changing either file. Two real
filesystem-denial probes confirmed the packaged engine did not treat protected
Codex or workspace directories as fully readable or change their sentinels.
These are disposable-fixture checks, not a clean buyer account or paid updater
installation. Both mounted images and all temporary jobs were removed.
The full regression suite with this exact packaged engine selected also
completed: 854 tests ran, 14 opt-in cases skipped, no failures. That suite uses
synthetic homes and mocked Apple receipts for many cases; it does not replace
the pending native paid-update and pristine-account checks.

All four PR #26 CI checks passed on Python 3.9 and 3.12 at head `0065d1a`.
Build 16 remains the public appcast release; the new
build-17 candidate remains private, testing-only, and unaccepted.

Review then found a quit race in the native updater: a helper that exited
before its `/api/update-shutdown` HTTP response arrived could previously let
AppKit terminate without proof that the cross-process Vault guard was set.
The native source now waits for the successful response before allowing
Sparkle's replacement, retries through a restarted helper if that response
fails, and treats a completely downloaded archive as potentially installable
even if Sparkle's session flag changes during quit. Swift typecheck and focused
regressions pass; the full source suite ran 855 tests with 15 opt-in skips and
no failures. The previously notarized `90f1cb29` image does **not** contain
this race fix. It must be rebuilt, re-signed, re-notarized, and retested before
release; build 16 remains live.

Clean source `b510f2166f30fe2856b0ec04599237c07d4a570d` now produced a
Developer ID signed, Apple-notarized and stapled build-17 app (Accepted receipt
`c0f3b663-ebc1-4b00-a38f-217edcdfbfb2`) and a separately signed,
Apple-notarized and stapled 10,375,160-byte rotation DMG (Accepted receipt
`a904a709-5c83-4459-bb50-887f3e7b6486`). Its SHA-256 is
`9890bffb25ca30c9d080dfe9ae6ed2f61902fec6f26c103965fba8f902ba7b79`;
the Sparkle signature independently verified against its embedded rotated
public key. The exact image was uploaded to private sandbox Blob and streamed
back with the same size and digest. It is catalogued as testing-only and
unaccepted. This is the current candidate; physical quit-race, paid-updater,
and clean-account acceptance remain open. Build 16 remains live.

The exact `b510f216` DMG was copied over the existing authenticated SSH link
to the Founder's second arm64 Mac (macOS 26.5) solely for read-only artifact
verification. Its SHA-256 matched the catalog receipt. A read-only mount
passed strict deep code-signature verification, staple validation, and
Gatekeeper assessment as Notarized Developer ID; the mounted app reports build
17. The image was detached and its temporary copy removed. No app was
launched, installed, or used against Codex or Vault data on that Mac. This
proves cross-device artifact integrity, not a paid update or clean-account
first launch.

An isolated `/Applications` copy of the `b510f216` app was made to report
build 16 with the old Sparkle public key and a loopback feed for the exact
10,375,160-byte notarized build-17 DMG. Test-only code supplied a synthetic
Codex home, a separate synthetic entitlement Keychain service, and an immediate
background update check; the release app and DMG were not modified. Sparkle
fetched the appcast and exact DMG, then automatically replaced the isolated
app. The synthetic home's owner-only update marker recorded target build 17,
which is evidence that the helper's guarded update-shutdown path ran. The
installed executable matched the `b510f216` release app byte-for-byte, its
bundle reported build 17, and strict signing and Gatekeeper both passed as
Notarized Developer ID. The synthetic transcript's SHA-256 remained unchanged.
The isolated app and HTTP server were stopped, its test-only Keychain item
removed, and the changed Sparkle check time restored. Because another copy of
Codex Migrate was already running on this account, the installed test copy did
not retain a healthy helper after relaunch. This is a successful guarded
replacement with synthetic data, **not** proof of a clean-account relaunch,
real paid entitlement, Production feed, or buyer-data protection.

Two further physical failure-path probes used the same disposable build-16
test app and separate synthetic homes. First, a loopback appcast offered the
exact candidate DMG with an intentionally invalid Sparkle signature. Sparkle
fetched the DMG twice but did not replace the app: it remained signed build 16,
its helper stayed alive until a normal AppKit quit, and the transcript hash
was unchanged. On that quit, the helper **did** reserve an owner-only Vault
update marker for target build 17 although signature validation ultimately
prevented replacement. This is fail-closed for snapshot safety, but scheduled
backups on that synthetic home would defer until the marker's two-hour expiry
unless a later successful update clears it. Treat this backup-delay behavior as
an explicit release concern, not a clean negative-path pass. Second, an
appcast with the correct signature but a missing archive returned HTTP 404.
The app remained build 16, the transcript hash was unchanged, and normal
AppKit quit left **no** update marker. Neither probe used a buyer credential
or the Production feed.

Instrumenting Sparkle's delegate during the invalid-signature probe confirmed
that `didAbortWithError` and the failed update-cycle callback fire **before**
the user quits. The native source now discards uncommitted update readiness on
abort, failed download, or canceled download, while preserving the guard if
shutdown has already begun. Swift typecheck and a focused regression passed.
A second isolated physical probe compiled that change into a test-only signed
app with the same invalid-signature feed. Sparkle again fetched and rejected
the DMG; normal AppKit quit left build 16 and the synthetic transcript unchanged
**and created no update marker**. This fixes the observed backup-delay case
when the rejection is reported before quit. The notarized `b510f216` app and
DMG predate this source change and must be rebuilt and reaccepted.

Clean source `27ef9bf1d4c89ae9fb1853ed0e37a57458db39cf` produced that
rebuild. The Developer ID signed app was Apple Accepted under submission
`0ee9063e-e017-4283-b646-434c81337cd7`; the separately signed rotation
DMG was Accepted under `f3179da8-56d6-4cb5-b43c-a3e19d2aa7af`. The final
10,376,201-byte DMG has SHA-256
`bf33da502e15a012c287efc5cec6c9b3057bf544c9ebbf8d9aebb1d91d2c1dc6`.
Sparkle verified its new-key signature. A read-only mount passed strict app
signing, app and disk-image staple validation, Gatekeeper assessment, build-17
and rotated-key checks; the embedded source receipt names `27ef9bf` and is
clean. The exact bytes were uploaded to private **sandbox** Blob and streamed
back with the same length and digest. The catalog entry remains
`testingOnly: true`, `accepted: false`; the public appcast still advertises
build 16. The full source suite passed 856 tests with 15 opt-in skips, Swift
typecheck passed, and the commerce suite passed 324 tests with one skip. This
is a new signed candidate, **not** release acceptance: the full paid install,
clean-account and remaining failure-path matrix still need proof against this
exact image.

An isolated `/Applications` copy of the `27ef9bf` client code, configured as
build 16 with the old Sparkle key and a loopback feed, automatically fetched
and installed that **exact** 10,376,201-byte DMG. The helper's owner-only
update marker recorded target build 17. The relaunched installed copy reported
build 17 and clean source `27ef9bf`; its executable matched the notarized app
byte-for-byte, and strict signing plus Gatekeeper accepted it. The synthetic
transcript hash was unchanged. The loopback server, test app, synthetic
Keychain item and temporary Sparkle check time were cleaned up. Because the
Founder's real app was already running under the same macOS account, the
installed test copy did not retain a separate healthy helper. This proves
the exact signed archive's guarded replacement, **not** clean-account
relaunch or paid Production delivery.

The same exact DMG was copied read-only to the Founder's second Mac
(`Joshuas-MacBook-Pro-128.local`, macOS 26.5, Apple silicon). Its remote
SHA-256 and 10,376,201-byte length matched the candidate. From a read-only
mount, the app passed strict deep code-signature verification, stapled-ticket
validation, and Gatekeeper assessment as Notarized Developer ID. It reported
build 17, the rotated public key, and the clean `27ef9bf` source receipt.
The image was detached and the disposable copy moved to Trash there; no app
was launched and no Codex or Vault data was touched. This is cross-Mac
artifact compatibility evidence, **not** a second-Mac install or clean-account
acceptance test.

The focused paid-archive canary tests now pin this exact abort-safe catalog
entry rather than the superseded quit-guard image; all 12 update tests pass.
A fresh read-only Production check still returned build 16 from `/api/appcast`
without a build-17 or sandbox path, and an anonymous `/api/update-archive`
request returned 403 without a private Blob redirect. This proves the
unreleased image remains private, not a paid installation of it.

The **exact `27ef9bf` packaged engine** then passed the opt-in real macOS
LaunchAgent test on disposable transcript data. A scheduled encrypted capture
ran through the bundled engine; while it was active, the helper returned 409
for both updater idle and update-shutdown requests. Once the capture completed
and verified, it returned 200 to a target-build-17 shutdown request, left an
owner-only update guard whose recorded target was 17, and deferred a subsequent
scheduled run without changing the last good snapshot.
The packaged backup/restore smoke also passed without copying authentication
files. The exact bundled engine's loopback-dashboard test passed too: it
started without a destination, returned active and old-title search results
from a disposable transcript, denied an unauthenticated updater idle probe,
rejected protected workspace selections, and shut down cleanly. These are
functional checks of the packaged helper, not a visual review. The scheduled
test unloaded its LaunchAgent and removed its plist and test key;
a post-run check found no loaded backup job or plist on this account. This is
physical **packaged-helper contention and cleanup** evidence, not a Sparkle
replacement while busy or a buyer-home catch-up observation.

A real loopback HTTP test of the paid archive handler now interrupts its
private upstream stream after a partial body. The client cannot receive a
completed update response; the server closes the failed stream instead of
delivering a seemingly complete archive. The web/commerce suite passes 325
tests with one skip. This covers proxy behavior under one network-break shape,
not Sparkle's physical offline/resume experience or a Production Blob outage.

The exact `27ef9bf` candidate also passed the sandbox-only Chrome download
check: a trusted browser click downloaded the private DMG as an attachment,
with its expected filename, 10,376,201-byte length and SHA-256 verified. The
short-lived signed Blob URL remained in process/browser memory and was not
recorded. The browser session closed after the check. This proves browser
transport of the testing-only archive, **not** purchase-page choice, a paid
entitlement, or an installed buyer update.

On September 24, the original paid purchase email was opened in Chrome
without recording its private link. The purchase page reverified the payment,
showed “Download for Mac,” and routed that action to the first-party
`/api/purchase-archive` form. In this Chrome profile, the attempted form
navigation displayed `ERR_BLOCKED_BY_CLIENT`; no new Codex Migrate archive
appeared in Downloads. Returning to the page showed its “Download requested”
recovery state. A separate top-level GET navigation to the public appcast was
also blocked by this client, while a direct HTTPS request returned 200. This
is a **failed browser-path observation**, not evidence that the server rejected
the entitlement or that a different browser would fail. Do not count the
sandbox-only successful download as closing it. This branch's purchase page offers
an explicitly short-lived direct file link as a fallback after verification;
that fallback still needs a live browser download receipt after deployment.
The page also keeps the buyer's original-build selection when an expired link
is refreshed instead of silently switching to the latest build. A local
browser fixture rendered the fallback at desktop and 390px mobile widths;
status and fallback copy computed to 17px at the mobile breakpoint. Focused
purchase-page/archive tests passed, as did the full web/commerce suite (327
passed, one skipped). This is UI and handler verification, not a paid live
fallback download receipt.
The original-versus-latest choice cannot be observed on the live page yet,
because the public latest release is still build 16. The PR checks for Python
3.9 and 3.12 passed on the September 24 branch state.

The buyer-page fallback and original-build refresh fix were isolated from
the held build-17 release in PR #29 and merged to `main` as `5f7f341`.
All four remote CI jobs passed. Production deployment
`dpl_G8okmz5mMeQNqbpNgdLG5KiAuuyJ` is Ready; independent HTTPS reads
confirmed the new purchase HTML and JavaScript, while the public appcast still
advertises build 16. A repeat paid-browser download could not be observed
because this Chrome control session stopped responding. Keep the real
browser-download acceptance open; neither successful deployment nor the
earlier sandbox-only save substitutes for it.
On a fresh Production check, the public appcast still advertised build 16.
The live `/api/update-archive` returned 403 for both a missing bearer and a
structurally valid but forged bearer; `/api/purchase` returned 403 for that
same forged token's entitlement check. No private file URL or buyer material
was requested or logged. A further Gmail-link browser attempt reached the
same unresponsive Chrome purchase tab, so a successful paid browser save
remained unverified. A subsequent keyboard-open created a fresh verified
purchase tab, but Chrome returned `ERR_BLOCKED_BY_CLIENT` for the short-lived
private Blob download as well. As a control, that same automated Chrome
profile also blocked a public GitHub source ZIP download while loading an
ordinary site SVG. No archive appeared in Downloads. This points to a
download/navigation restriction in the client profile or automation path; it
does not establish that our paid endpoint is broken or that a normal buyer
browser succeeds. The temporary test tabs were closed. Keep a non-blocked
browser download receipt as an acceptance gate.

A later live paid Chrome retry opened the verified purchase page from the
buyer's delivery email without copying its private credential. Chrome's
native **Save Link As** action on the deployed direct-download fallback saved
the build-16 archive. The file was 9,591,579 bytes and its SHA-256 was
`60eff4dcb07088d01c966587e808f21d5fa74b8afb4eba45ed326543f07241f7`,
exactly matching the live release catalog. This closes the fallback's
real-browser transport check for one paid purchase, not the primary
first-party form or a build-17 update. Chrome had defaulted the save dialog
to an unrelated OneDrive folder; the exact newly saved ZIP was moved into
Downloads immediately and verified there. No other file in that folder was
changed. Whether OneDrive briefly synchronized the ZIP is unknown.
That exact browser-downloaded ZIP carried macOS quarantine metadata. Extracted
into an isolated temporary folder, its build-16 app passed strict deep
code-signature verification and Gatekeeper assessment as **Notarized Developer
ID**, and the extracted bundle retained quarantine metadata. The temporary
extraction was moved to Trash. This is not a first launch in a clean buyer
account; the Founder's running developer copy was not interrupted.

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

1. Inspect the remaining operator-alert inbox; repair the buyer-facing
   primary download and recheck the original-build choice after a new
   accepted release exists. In a live paid Chrome test on September 24, the
   first-party form download reached Chrome's Save dialog but was marked
   “Suspicious download blocked.” The existing direct private-Blob fallback
   worked through Save Link As, producing all 9,591,579 build-16 bytes with
   the catalog SHA-256. Making that direct URL the sole primary button passed
   unit/CI tests but an ordinary click in this Chrome profile navigated to
   `ERR_BLOCKED_BY_CLIENT`; the exact client blocker is unknown. That candidate
   was briefly promoted, then the prior production deployment was restored.
   PR #31 returned `main` to the prior source tree after PR #30's failed live
   experiment. Do not tell a buyer to bypass a Chrome warning or call either
   button reliable until an ordinary-click delivery passes in a buyer browser.
   Both authenticated Production server streams previously matched build 16.
   The verified `https://migrate.segeren.com/` property showed **No issues
   detected** in Google Search Console's Security issues report on September
   24. That rules out a reported site-level issue there, not an unfamiliar-file
   warning or a client-extension block. Google's
   [Chrome download guidance](https://support.google.com/chrome/answer/6261569)
   explicitly lists uncommon files and ZIP archives as possible reasons for a
   “Suspicious” classification.
2. The rebuilt clean-source app, rotation DMG, Sparkle signature, private
   sandbox Blob readback, isolated build-16-to-17 quit-path install, and
   candidate-code idle install/relaunch with an app-owned synthetic token pass.
   The real paid entitlement streamed this candidate from the staged hosted
   server and the temporary canary was disabled afterward. This is not a
   buyer-app update or release approval; the sandbox-only catalog entry stays
   unaccepted. Directly observe
   that the duplicate-launch warning is absent and prove periodic checks still
   run after relaunch. A synthetic scheduled backup now proves the full
   replacement waits and resumes safely. An opt-in physical test using the
   exact notarized build-17 packaged engine also proves that the updater's
   idle and shutdown requests refuse a real synthetic Vault restore, create
   no update guard while it runs, and permit shutdown only after the restored
   transcript matches the source. It passed under macOS system Python 3.9 and
   Python 3.12. This is helper-level contention, not a full Sparkle bundle
   replacement during restore. Migration contention, full replacement under
   restore contention, and catch-up from an unmodified buyer home remain open.
3. The invalid-signature and missing-archive probes above left the app and
   synthetic transcript unchanged. Source now clears aborted-update state, and
   the isolated repeat of the bad-signature case creates no update guard on
   quit. Rebuild and repeat against the final notarized artifact. A fresh
   September 24 Production probe of `/api/update-archive` returned 403 with
   zero response bytes and no redirect for missing bearer, a syntactically
   valid forged bearer, and the forged bearer plus the disabled build-17
   canary header. The public appcast still advertised build 16 with no
   build-17 or sandbox reference. These are live server-denial checks, not a
   paid native-client failure-path receipt. Still exercise
   missing/forged/refunded credentials, wrong architecture, corrupt archive,
   unavailable network, and insufficient disk space against the actual update
   path. No failure may replace the app or mutate Codex/Vault snapshots.
4. On a disposable clean macOS user account, complete quarantined download,
   Gatekeeper open, purchase linking, first Vault backup, recovery-key save,
   scheduled run, search/export, and selected-thread recovery. Do not treat
   an existing developer account as pristine acceptance.
5. Extend the configuration matrix: oldest declared macOS version and newest
   macOS version; supported Codex desktop/CLI layouts; different usernames;
   case-sensitive APFS; permission denial; local, external, and cloud-sync
   folders; low free space; sleep/restart during backup and staging; large
   histories; and direct-cable interruption. Mark an untested combination as
   such rather than assuming support. A September 24 opt-in test with the exact
   packaged build-17 engine now passes backup, snapshot verification, safe
   absent-volume failure, remount, and scheduled catch-up on both ordinary and
   **case-sensitive APFS external Vault volumes**, under Python 3.9 and 3.12.
   It verifies each mounted
   filesystem's actual case behavior. That test does not cover a case-sensitive
   source home or Mac-to-Mac migration.
   A separate real-APFS sparse-volume test filled an external Vault destination
   to under 32 MiB free, then ran the exact packaged build-17 backup engine
   against a larger synthetic transcript. The write failed without changing
   the previous `latest.json` reference; that prior encrypted snapshot still
   verified, the source stayed byte-identical, and a retry published a new
   verified snapshot after the disposable pressure file was removed. It passed
   on Python 3.9 and 3.12. This proves Vault destination disk-pressure
   recovery, not insufficient-space handling inside Sparkle's app update.

An opt-in packaged-engine test now puts a synthetic Codex source home on a
**case-sensitive APFS** volume with two distinct transcripts whose filenames
differ only by case. The exact build-17 engine backed up and verified both,
then restored both byte-for-byte on a case-sensitive volume. Restoring that
snapshot to ordinary case-insensitive APFS refused the name collision: it
published no restore receipt, left only an incomplete disposable staging
folder, and did not change the source or encrypted Vault. This is fail-closed
behavior, not full cross-filesystem recovery support; such a snapshot needs a
case-sensitive restore destination or separate thread export. The opt-in test
is in `tests/test_vault_external_volume.py`.

The exact build-17 packaged engine also passed an opt-in **process-kill during
Vault backup** test on this Mac. After an initial verified snapshot, the test
added a large synthetic transcript, observed a new encrypted chunk, and sent
SIGKILL to only the disposable backup process group. The previously published
`latest.json` remained byte-identical and its snapshot still verified; the
synthetic source was unchanged. A fresh packaged-engine retry then published
and verified a new snapshot. The test passed twice consecutively in its final
form and removed its disposable Keychain key. This proves recovery from one
mid-write process interruption, not a power loss, sleep/restart, or interruption
of a buyer's real history. The opt-in test is
`tests/test_packaged_vault_interruption.py`.

The current local Vault guarantees the last verified capture, not zero loss
between snapshots, completed off-device cloud sync, or every Codex UI resume.
An opt-in synthetic large-history probe now creates 2,048 distinct Codex
transcripts, publishes and verifies a first encrypted snapshot, appends to one
thread, then publishes and verifies a second. Only one new encrypted chunk is
added on the second run. It passed on this Mac under system Python 3.9 and
Python 3.12 in 53.3 and 52.7 seconds respectively. This exercises file-count
and incremental-backup behavior, not multi-gigabyte histories, live Codex
data, search latency, or a scheduled run. The opt-in test is in
`tests/test_vault_backup.py`; ordinary CI skips it.
An opt-in 2,048-thread synthetic **search** probe now verifies that one query
finds both the newest and a near-oldest matching conversation in recency
order. It passed on this Mac under Python 3.12 in 0.30 seconds and system
Python 3.9 in 0.34 seconds for the complete test. A separate read-only search
of the Founder's existing 1,984 active and 69 archived local transcripts,
using a phrase the Founder supplied, returned the first 25 matches; inspection
plus search took 1.04 seconds and printed no conversation content. These
checks cover local file-count and current source-code search. The exact
Developer ID signed, notarized build-17 DMG from source `27ef9bf` was then
mounted read-only; its bundled engine returned the first 25 matches from the
same live history in 1.53 seconds without printing conversation content. The
image was detached and the temporary mount directory removed. This still
does not measure browser rendering, very large individual transcripts, or an
exhaustive count of all matches. The synthetic probe is in `tests/test_vault.py`
and is skipped by ordinary CI.
The backup test file also deterministically rewrites a synthetic transcript
immediately after the encrypted chunk helper reads it. On Python 3.9 and
3.12, backup rejected the changed source, published no new snapshot
reference, and the previous snapshot still verified. This checks the
mid-read failure boundary without racing or changing a real Codex thread.
On September 24, the complete source suite ran from a disposable checkout on
the Founder's second Mac (macOS 26.5, Apple silicon, system Python 3.9.6).
It ran 856 tests in 254.6 seconds: 834 passed, 15 skipped, and seven Vault
backup/history tests errored at `create-key`. A separate read-only Keychain
check in that SSH login returned `User interaction is not allowed`; the Vault
helper deliberately refused to publish a snapshot. This is a headless SSH
Keychain-context limitation, not a second-Mac GUI acceptance receipt or proof
of a product failure. All Python 3.9/3.12 CI jobs for the same branch passed.
The clean 23 MB remote checkout was removed after the test; no live Codex
content was used or changed.
The separate desktop pre-compaction proof remains open; a tested Codex hook
timed out fail-open. See [thread history contract](vault-thread-history-contract.md).
On this Mac, `vault schedule-status` reports that automatic Vault backups are
disabled. A read-only check on the other Mac found no Vault backup LaunchAgent
plist or loaded job there either. Neither account should be described as
protected by scheduled Vault backups; setup requires a chosen destination,
verified first snapshot, and recovery-key custody.

Keychain access during a locked-screen scheduled run remains an acceptance
question. The Vault helper requests `WhenUnlockedThisDeviceOnly` and refuses
interactive Keychain prompts; a failed run leaves the previous verified
snapshot intact and makes schedule status unhealthy. Apple describes that
accessibility class as available only while unlocked, whereas
`AfterFirstUnlockThisDeviceOnly` is designed for background access after the
first unlock following restart. However, Apple's macOS documentation also
says `kSecAttrAccessible` requires the Data Protection Keychain or a
synchronizable item, so the constant alone does not prove current behavior
on this Mac. Do not change key accessibility or advertise locked-screen
coverage from source inspection: use a disposable key and synthetic Vault
to verify a real locked-screen LaunchAgent run, then review the key-custody
tradeoff and existing-key migration if a change is needed. The daily cadence
can otherwise fail repeatedly when the Mac is locked at the same hour.
On this Mac, a disposable generic-password item using the helper's current
legacy-Keychain attributes was added and queried successfully, but its
returned attributes contained no `kSecAttrAccessible` value. It was deleted
successfully. A second disposable item requesting the Data Protection
Keychain returned Security status `-34018` on add; no item was created. These
nonsecret metadata probes do not establish actual locked-screen behavior or
authorize a Keychain migration. They do show that merely swapping the
accessibility constant in source is not an evidence-backed fix.
Apple references:
[`WhenUnlockedThisDeviceOnly`](https://developer.apple.com/documentation/security/ksecattraccessiblewhenunlockedthisdeviceonly),
[`AfterFirstUnlockThisDeviceOnly`](https://developer.apple.com/documentation/security/ksecattraccessibleafterfirstunlockthisdeviceonly),
and [`kSecAttrAccessible` on macOS](https://developer.apple.com/documentation/security/ksecattraccessible).

The exact notarized build-17 DMG in this ledger was mounted read-only again.
Its embedded `CodexVaultCrypto` executable and enclosing app have no
code-signing entitlements. Apple says the Data Protection Keychain derives
access groups from those entitlements; the current helper therefore cannot
simply opt into it by adding a query flag. A disposable Swift probe signed
with the available Developer ID identity and a claimed access group, but no
provisioning profile, exited with status 137 before it could report a Keychain
result. An ad-hoc-signed copy with the same claimed entitlements did likewise.
The image was detached and the probe moved to Trash. These attempts are **not**
evidence that the needed entitlement is provisioned or that the existing
legacy-Keychain key has the documented `ThisDeviceOnly` semantics. Hold that
specific security claim until a provisioned signed helper and existing-key
migration are physically proved; keep using the recovery key for portability.
Apple references: [Mac keychain implementations](https://developer.apple.com/documentation/technotes/tn3137-on-mac-keychains),
[Data Protection Keychain](https://developer.apple.com/documentation/security/ksecusedataprotectionkeychain),
and [access-group entitlement checks](https://developer.apple.com/documentation/security/errsecmissingentitlement).

On September 24, the synthetic recovery-key portability test passed on two
independent GitHub-hosted macOS runners in
[CI run 36058234998](https://github.com/jsegeren/codex-migrate/actions/runs/36058234998).
The producer created and verified an encrypted one-transcript snapshot, then
deleted its disposable Keychain key. The consumer had no producer Keychain key,
imported the recovery key, verified the snapshot, and restored the synthetic
transcript byte-for-byte. The one-day CI artifact contains only synthetic test
material and a disposable recovery key, never Founder or customer content.
This proves the format and recovery-key round trip across distinct macOS runner
Keychains; it is **not** a clean account or GUI recovery test on the Founder's
two physical Macs, and it does not prove `ThisDeviceOnly` key accessibility.

On September 24, the existing paid buyer-delivery link verified on the live
purchase page. Its primary button targeted the first-party
`/api/purchase-archive` handler. In the controlled Chrome session, clicking it
navigated to `ERR_BLOCKED_BY_CLIENT` and saved no file; this is not evidence of
an HTTP failure or of normal customer Chrome behavior. An independent POST to
that same Production handler, with the existing purchase entitlement and the
expected same-origin form headers, returned HTTP 200 and exactly 9,591,579
bytes. The ZIP digest matched build 16's published SHA-256
`60eff4dcb07088d01c966587e808f21d5fa74b8afb4eba45ed326543f07241f7`;
ZIP integrity, strict app code signature, and Gatekeeper's Notarized Developer
ID assessment all passed after extraction to a disposable directory. No buyer
token or private download URL is recorded here. The browser-button observation
remains unresolved for that controlled session and must not be described as a
verified ordinary-click purchase flow from this run.
Production request logs independently show that the controlled Chrome click
did reach `/api/purchase-archive` and received HTTP 200 at 23:07:43 UTC. They
do not identify which local client component blocked the attachment after the
response. Do not disable browser security or attribute the block to a specific
extension without evidence.
Opening that same already-paid link in the isolated Codex in-app browser then
verified the purchase and produced a real download event from the **primary**
button. Its saved, quarantined ZIP in Downloads was 9,591,579 bytes and
matched build 16's exact published SHA-256. Thus the live first-party buyer
flow works in a second browser surface, while this Chrome profile's block is
still unexplained. This is not a Safari/Firefox or pristine-Chrome acceptance
result, and the browser-quarantined app has not been installed from that ZIP.
The same ZIP's macOS quarantine attribute propagated to an extracted app.
Gatekeeper assessed that quarantined app as Notarized Developer ID. Opening
the disposable copy from outside Applications triggered App Translocation;
the test process ran from a translocated path, while no second helper started
and the existing developer app/helper remained running. Computer-use control
timed out before its alert could be observed, so this is **not** first-open UI
acceptance. The test process was stopped, and the extra ZIP and extracted app
were moved to Trash, where they remain recoverable.
The exact held build-17 DMG from source `27ef9bf` then passed a separate
synthetic-quarantine first-open UI test. Its digest still matched the private
test-only catalog; a copied app passed strict signing and Gatekeeper as
Notarized Developer ID. With a current Safari-style quarantine attribute,
macOS displayed its downloaded-app approval, reported that Apple found no
malicious software, and launched the disposable app from an actual
`AppTranslocation` path after approval. Computer-use inspection captured the
app's **Move Codex Migrate to Applications** warning. No second helper started;
dismissing the warning exited only the disposable app while the original
developer app/helper remained running. The image was detached and the test
copy moved to Trash. This closes the warning observation for the exact
notarized candidate under *synthetic* quarantine, not the browser-downloaded
build-16 ZIP or a clean buyer-account first launch.
Safari verified the same purchase, but its first primary-button click opened
the browser's site-specific **Allow Downloads** permission. That permission
was not granted without Founder approval; the prompt was canceled and the
temporary tab closed. No Safari file-save conclusion can be drawn yet.
The same Production handler's `original` choice returned HTTP 200 and the
same verified build-16 byte count and digest, as expected while build 16 is
both the paid original and the latest live release. This does not exercise
the purchase page's original-build button after a newer release is promoted.

PR #26's latest source and receipt commit `a760fbb` passed both Python 3.9
and 3.12 macOS CI checks in the push and pull-request runs; the opt-in
portability workflow did not run on this ordinary commit. The exact
10,376,201-byte signed, notarized build-17 candidate DMG was mounted read-only
on this Mac and its packaged engine passed the opt-in physical restore/update
contention fixture again: the token-protected idle and shutdown requests
refused a running restore, the recovered synthetic transcript matched the
source, then idle and shutdown succeeded and the helper exited. The test
removed its disposable Keychain key and temporary data; the image was
detached. This repeats the helper-level guard against the current candidate;
it still does not prove a full Sparkle replacement during a restore or a
pristine buyer-account installation.

The exact held build-17 DMG was also mounted read-only for a bounded package
audit. A filename inventory found no packaged `.env`, `auth.json`, private-key
file, `.codex`, `.ssh`, `.git`, or `.vercel` directory. A byte-pattern scan found
no matches for the application's live purchase-token format, Stripe live-secret
format, SendGrid key format, or PEM private-key headers. The image was detached
afterward. This is a negative check for those known patterns, not proof that
every possible secret format is absent.

The September 24 updater-location review found that a symlinked app path could
hide an actual Downloads or mounted-image location from the first-open guard.
Source `9afee8a` now checks both the visible and resolved app path. A native
filesystem test covers an app symlink and a parent-directory symlink into a
disposable Downloads folder; all 18 focused desktop tests passed (two expected
fixture skips). This source change is newer than the held notarized build-17
DMG, so that image remains mechanism evidence only. Rebuild, notarize, sign,
and repeat the exact-candidate installation checks before release.

A local-only arm64 app was built from clean source `5f913b2` with the new
location guard. Strict code-signature verification passed. Its packaged engine
completed a synthetic encrypted backup and restore without moving authentication
or installation identity; a second opt-in physical test kept the updater idle
and shutdown endpoints closed during a 128-MiB Vault restore, then permitted
shutdown only after the recovered transcript matched. The test Keychain item
and temporary data were removed. This ad-hoc-signed package is not notarized,
distributed, or proof of a paid buyer update.

From clean PR source `134d4f2`, a disposable local-only arm64 build reported
build 17 and the same source revision in its packaged receipt. All four opt-in
external-volume Vault tests passed with that packaged engine on real APFS disk
images: ordinary and case-sensitive volumes did not silently become local
Vaults when unavailable; a case-sensitive source with colliding names restored
on case-sensitive APFS but refused to merge on ordinary APFS; and an external
volume filled during a new backup retained its last verified snapshot, then
accepted a retry after space was freed. The tests used synthetic conversations,
removed their temporary Keychain keys, detached the images, and removed their
disposable data. This expands exact-source filesystem evidence; the package is
not notarized and does not prove a paid Sparkle install or a clean-account run.
