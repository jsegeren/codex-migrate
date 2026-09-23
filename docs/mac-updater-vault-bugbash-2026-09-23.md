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
| Python regression | 826 tests passed, 12 skipped after the first candidate edits; 12 focused schedule tests pass after the latest status guard | CI and final-diff full run still required |
| Website/commerce regression | 309 passed, 1 skipped after the first-party archive change | Does not substitute for a live paid download |
| App-size archive stream | A 9.6 MB synthetic ZIP-sized response streamed with exact byte count and SHA-256 | Local handler test, not the hosted Production proxy |
| Backup scheduling | Found that a loaded schedule could look healthy with a days-old last success or stalled run; candidate now marks overdue runs unhealthy and disregards receipts from before reinstallation | 12 focused tests pass; must check the rendered customer status and a real scheduled run |
| Updater preferences | Candidate has a menu control for periodic checks and opt-in automatic installation; Swift typecheck and local packaged build pass | Not yet a signed build-17 release or a physical unattended installation test |
| Packaged helper | Local-test-only app's bundled engine passed 8 desktop cases with 1 filesystem skip | Not a clean-account first launch or notarized buyer installation |
| Paid checkout | One real $49 Founder purchase verified, and the buyer delivery email arrived | Chrome blocked the private-storage download host; candidate routes buyer downloads through a first-party streaming endpoint, still awaiting deployed full-archive proof. Operator alerts not yet verified. |

## Release blockers for this candidate

1. Deploy and verify the first-party buyer download fix. Confirm both operator
   alerts and a full authenticated Production download whose size and checksum
   match the current release. Keep the original-purchase download fallback.
2. Freeze and notarize build 17, sign its final ZIP for Sparkle, upload/read
   back exact bytes, and test build 16 → 17 with a real paid entitlement.
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
