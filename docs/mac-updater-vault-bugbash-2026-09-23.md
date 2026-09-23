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
| Python regression | The idle-install candidate ran 830 tests: 818 passed, 12 skipped. | Opt-in physical filesystem and clean-account tests are separate; a green unit suite is not buyer acceptance. |
| Website/commerce regression | 309 passed, 1 skipped after the first-party archive change; 84 focused checkout, entitlement, and update-archive tests passed on merged `main`. | Does not substitute for a browser file save or real in-app installation. |
| App-size archive stream | A 9.6 MB synthetic ZIP-sized response streamed with exact byte count and SHA-256 | Local handler test, not the hosted Production proxy |
| Backup scheduling | Found that a loaded schedule could look healthy with a days-old last success or stalled run; candidate now marks overdue runs unhealthy and disregards receipts from before reinstallation | 12 focused tests pass; must check the rendered customer status and a real scheduled run |
| Updater preferences | Review found that Sparkle's automatic download normally installs on quit. Merged source `c357399` adds a private idle probe and an opt-in quit/retry path, with a final shutdown recheck. CI passed on Python 3.9 and 3.12; the bundled engine from that exact source passed 8 desktop tests with 1 filesystem skip. A running scheduled backup refuses the idle probe and shutdown. | The existing notarized build-17 ZIP predates this change. Rebuild, notarize, and physically verify unattended installation, including a separately scheduled Vault backup, before release or marketing claims. |
| Packaged helper | Local-test-only app's bundled engine passed 8 desktop cases with 1 filesystem skip | Not a clean-account first launch or notarized buyer installation |
| Real APFS disk pressure | Five opt-in tests passed on an isolated sparse disk image: low space before and after backup blocked replacement; actual ENOSPC retained the original and backup; retry succeeded; end-of-install pressure ended with a verified terminal receipt; forced rollback under pressure was verified. The disposable image was detached and removed. | Synthetic Codex and workspace fixtures, not a buyer account or all possible write-failure points. |
| Packaged permission denial | The build-17 bundled engine passed two real filesystem-denial probes against synthetic Codex and workspace directories without changing the protected files. | Does not prove macOS TCC, Files and Folders picker, or Full Disk Access behavior. |
| Case-sensitive APFS | The build-17 bundled engine rejected a nested `README`/`readme` collision on an isolated case-sensitive APFS image; the image was detached and removed. | One collision safety check, not a full case-sensitive migration. |
| Paid checkout | One real $49 Founder purchase verified, and the buyer delivery email arrived | The buyer was one of the two operator addresses, so that inbox received the buyer delivery rather than a separate operator alert; the other operator inbox has not been inspected. |
| Browser download | Production now links to the same-origin `/api/purchase-archive` endpoint. Both latest and original requests with the paid credential returned 9,591,579 bytes and the published build-16 SHA-256. | This Chrome session displayed `ERR_BLOCKED_BY_CLIENT` for both the old private-host navigation and the new first-party download navigation. The server path passed, but an ordinary browser file save still needs independent confirmation. |
| Paid updater proxy | Production `/api/update-archive` accepted the same buyer entitlement and streamed build 16 with the published byte length and SHA-256; unauthenticated access remains denied. | This proves the paid archive path, not automatic installation. |
| Earlier build-17 artifact | Clean `e1552b340214abf3c5218499ff9880c96b8f3b5d` source produced a signed, Apple-notarized, stapled, Gatekeeper-accepted arm64 app and 9,596,033-byte ZIP (SHA-256 `118fbe0c8560cab663e8ad0678ab92b011a3bbea1dcb27e664c281f24db21406`). Bundled engine passed 8 desktop tests with 1 filesystem skip; the separate case-sensitive check above passed. | It predates the idle-install safety change and must not be promoted as the final candidate. A second Sparkle-signing attempt still stopped at the login Keychain authorization prompt and was canceled. Build 17 is not in the release catalog or appcast. |
| Merged-source signing attempt | Clean `9b3159d` source produced a Developer ID signed build-17 app; strict code-signature verification and 8 bundled desktop tests passed (1 case-sensitive-filesystem skip). The other Mac was reachable but had neither the existing Sparkle Keychain item nor the Developer ID signing identity. | Apple's notarization submission failed before a receipt ID was returned using the separate notary Keychain profile. This candidate is not notarized or distributable; inspect notarization history before retrying after credential access is restored. No Sparkle archive signature or real 16-to-17 installation exists for it. |

## Release blockers for this candidate

1. Confirm an actual browser file save from the first-party download page in
   an ordinary customer browser, and inspect the remaining operator-alert inbox.
   Both authenticated Production server streams have already matched build 16.
2. Resolve Sparkle private-key access without bypassing Keychain security, or
   explicitly approve a key rotation and one-time manual update from build 16.
   Rebuild and notarize the final build-17 source; sign its final ZIP for Sparkle,
   upload/read back exact bytes, and test build 16 → 17 with a real paid entitlement.
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
On this Mac, `vault schedule-status` currently reports that automatic Vault
backups are disabled; do not describe this Mac as protected by a schedule.
