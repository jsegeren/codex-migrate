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
| Python regression | Current candidate ran 843 tests: 829 passed, 14 skipped, including the new native install-location check, scheduled external-Vault safeguards, and existing notarization/rotation resume fixtures. | Release/notarization results printed by mocked fixture tests are not real Apple receipts. Opt-in physical filesystem and clean-account tests are separate; a green suite is not buyer acceptance. |
| Website/commerce regression | 309 passed, 1 skipped after the first-party archive change; 84 focused checkout, entitlement, and update-archive tests passed on merged `main`. | Does not substitute for a browser file save or real in-app installation. |
| App-size archive stream | A 9.6 MB synthetic ZIP-sized response streamed with exact byte count and SHA-256 | Local handler test, not the hosted Production proxy |
| Backup scheduling | Found that a loaded schedule could look healthy with a days-old last success or stalled run; candidate now marks overdue runs unhealthy and disregards receipts from before reinstallation | 12 focused tests pass; must check the rendered customer status and a real scheduled run |
| External Vault disconnect | A synthetic Vault on a real detachable APFS disk image survived eject and remount. The freshly packaged arm64 engine ran the scheduled-backup command: while detached it failed without creating a replacement Vault on the internal volume; status showed unhealthy. After remount, its next capture verified successfully. The schedule is now bound to the verified Vault key ID; a changed destination fails closed. The local app passed strict code-signature verification. A local browser render of an older schedule showed the original Vault path, an unhealthy status, and instructions to turn scheduling off, run a verified backup there, and turn it back on. | The account-wide LaunchAgent and a physical USB drive were not exercised. The app was ad-hoc signed, not notarized. The rendered check used a synthetic home without Codex history, so it did not exercise a successful first backup. |
| Standalone CLI dashboard | A browser check found that `codex-migrate serve` linked to Vault routes it does not serve; those links returned 404. The standalone navigation now exposes only its working Mac-migration route, with a regression assertion. | The paid `launch` dashboard continues to expose its real Vault routes. This CLI fix does not prove a packaged buyer install. |
| Updater preferences | Review found that Sparkle's automatic download normally installs on quit. Merged source `c357399` adds a private idle probe and an opt-in quit/retry path, with a final shutdown recheck. CI passed on Python 3.9 and 3.12; the bundled engine from that exact source passed 8 desktop tests with 1 filesystem skip. A running scheduled backup refuses the idle probe and shutdown. A focused HTTP test also proves that a backup starting after the idle probe blocks the final shutdown request. | The existing notarized build-17 ZIP predates this change. Rebuild, notarize, and physically verify unattended installation, including a separately scheduled Vault backup, before release or marketing claims. |
| Packaged helper | Local-test-only app's bundled engine passed 8 desktop cases with 1 filesystem skip | Not a clean-account first launch or notarized buyer installation |
| Real APFS disk pressure | Five opt-in tests passed on an isolated sparse disk image: low space before and after backup blocked replacement; actual ENOSPC retained the original and backup; retry succeeded; end-of-install pressure ended with a verified terminal receipt; forced rollback under pressure was verified. The disposable image was detached and removed. | Synthetic Codex and workspace fixtures, not a buyer account or all possible write-failure points. |
| Packaged permission denial | The build-17 bundled engine passed two real filesystem-denial probes against synthetic Codex and workspace directories without changing the protected files. | Does not prove macOS TCC, Files and Folders picker, or Full Disk Access behavior. |
| Case-sensitive APFS | The build-17 bundled engine rejected a nested `README`/`readme` collision on an isolated case-sensitive APFS image; the image was detached and removed. | One collision safety check, not a full case-sensitive migration. |
| Paid checkout | One real $49 Founder purchase verified. The connected `segerej@gmail.com` inbox has the buyer-delivery email dated September 23, 2026. | That address was also an operator-alert recipient, so deduplication correctly sent it the buyer copy rather than a separate alert. The separate alert to `joshua@segeren.com` has not been inspected. No private download link is recorded here. |
| Browser download | A clean Chrome session exposed a real 403: the purchase page's `no-referrer` policy made its archive form send `Origin: null`. Hotfix PR #27 changed only that page to `same-origin`; CI passed and Production deployment `dpl_9H6PS1DBJZ7JaX8xUWGnuCFbNfYB` is READY. The unmodified live page then verified the paid link and saved the 9,591,579-byte build-16 ZIP. Its SHA-256 matched the page's published `60eff4dcb07088d01c966587e808f21d5fa74b8afb4eba45ed326543f07241f7`. | This proves one real Chrome latest-build download on this Mac. Recheck the original-build choice and other supported browsers during release acceptance. |
| Buyer install guidance | Candidate purchase page and delivery email now explain how to install ZIP or DMG downloads in Applications; 81 focused purchase/commerce tests and 35 site tests passed locally. | This copy is not yet deployed. Physically verify a buyer-installed app is not running from Downloads or a mounted DMG before accepting automatic-update behavior. |
| Unsafe launch location | Candidate app now warns before starting its helper when opened from Downloads, a mounted disk image, or App Translocation. Native path-classification checks and Swift typecheck passed. A fresh ad-hoc-signed arm64 app built; its bundled engine passed 10 desktop tests with 1 case-sensitive-filesystem skip, and strict code-signature verification passed. | The warning was not opened from a real quarantined download or DMG, and this is not a notarized release. Physical buyer-install acceptance remains open. |
| Paid updater proxy | Production `/api/update-archive` accepted the same buyer entitlement and streamed build 16 with the published byte length and SHA-256; unauthenticated access remains denied. | This proves the paid archive path, not automatic installation. |
| Earlier build-17 artifact | Clean `e1552b340214abf3c5218499ff9880c96b8f3b5d` source produced a signed, Apple-notarized, stapled, Gatekeeper-accepted arm64 app and 9,596,033-byte ZIP (SHA-256 `118fbe0c8560cab663e8ad0678ab92b011a3bbea1dcb27e664c281f24db21406`). Bundled engine passed 8 desktop tests with 1 filesystem skip; the separate case-sensitive check above passed. | It predates the idle-install safety change and must not be promoted as the final candidate. A second Sparkle-signing attempt still stopped at the login Keychain authorization prompt and was canceled. Build 17 is not in the release catalog or appcast. |
| Final-source build-17 candidate | Clean `e2f362f` source produced a Developer ID signed, Apple-notarized, stapled arm64 ZIP (9,599,345 bytes; SHA-256 `8bfeba3db03ffa8977118794f03dcde7d7f90074d8aa4a4969e8485eed10a524`). Apple receipt `943e5684-9717-4e5c-9f27-d7d03db83eba` is Accepted. Strict code-signature verification and Gatekeeper passed on this Mac and the second Mac (macOS 26.5); the exact ZIP hash matched there. The bundled engine passed 8 desktop tests with 1 case-sensitive-filesystem skip. | This candidate still lacks a Sparkle archive signature and a paid 16-to-17 installation receipt. It is not in the release catalog or public appcast and must not be advertised or distributed as the update. The second-Mac copy was moved to Trash after verification; no app was launched there. |
| Rotated-key local package | Current PR head `ae2fce7` compiled into an arm64 local-test app. Strict code-signature verification passed and its Info.plist contains the rotated Sparkle public key. The bundled engine passed 9 of 10 desktop tests, with only the case-sensitive-filesystem fixture skipped. A new disposable-home packaged-engine test made two encrypted, verified snapshots, restored both versions to separate folders, and confirmed that authentication and installation identity files were not restored; its test Keychain key was removed. | This is ad-hoc signed and not notarized. It does not prove the key-rotation DMG, buyer installation, clean-account first launch, or scheduled backups on either real Mac. |

## Release blockers for this candidate

The Founder approved a Sparkle key rotation. A new local signing seed and
public key exist, and the source now supports a Developer ID signed DMG for
the rotation. A byte-verified, owner-only second copy of the seed now exists on
the Founder's other FileVault-enabled Mac. The separate
Apple notarization Keychain is locked, so no new DMG has been notarized or
distributed. See [the rotation runbook](sparkle-key-rotation-2026-09-23.md).

1. Inspect the remaining operator-alert inbox and recheck the original-build
   browser choice. The latest-build file save now has a clean Chrome and SHA-256
   receipt; both authenticated Production server streams matched build 16.
2. The Founder approved rotating the inaccessible Sparkle key. Rebuild and
   notarize the clean final build-17 source, then create the separately signed
   and notarized rotation DMG while retaining the live build-16 Apple signing
   certificate. Sign that final DMG with the new Sparkle key, upload/read back
   exact bytes, and test build 16 → 17 with a real paid entitlement.
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
