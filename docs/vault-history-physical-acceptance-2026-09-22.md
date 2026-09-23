# Vault history two-Mac acceptance — 2026-09-22

## Result

The thread-history candidate at `60d2a32` passed isolated, synthetic acceptance
in both directions between two physical Apple-silicon Macs. It did not read or
change either Mac's real Codex history, credentials, or workspaces. This receipt
supports the versioned Vault, key-recovery, and selected-thread safety claims;
it does **not** establish desktop `PreCompact` coverage or zero-loss protection.

| Machine | macOS | Python | Vault tests | Cross-Mac role |
| --- | --- | --- | --- | --- |
| Original Mac | 26.5.1 | 3.12.3 | 52 passed | Source, then recovery destination |
| Larger Mac | 26.5 | 3.9.6 | 52 passed | Recovery destination, then source |

Each machine used the same pushed source commit. The original Mac's complete
Python suite also passed (813 tests, 12 skips), and the pull request's Python
3.9 and 3.12 CI checks passed. A Developer ID signed **local-test** app from
that commit passed strict signature verification and bundled-engine startup;
it was not notarized or distributed.

## What was proved on each Mac

1. A long synthetic rollout received a first encrypted snapshot, which verified
   before any subsequent changes. No recovery key or conversation text was
   logged.
2. The isolated scheduled-backup runner created and verified a second snapshot
   after a title rename and transcript append. Its private run receipt reported
   `completed`. The test did **not** install the singleton LaunchAgent, which
   could disturb a real user's existing Vault schedule.
3. The old title still found the thread after a rename and after the synthetic
   live file was removed. Its timeline retained the intact earlier version.
4. A conspicuous shrink produced `needs_attention`; a later identical capture
   could not clear the warning. The pre-shrink snapshot remained verifiable.
   The fixture used a long >1 MiB rollout and a small truncated version. The
   separate unit case models the reported 851 MB to 7 MB metadata precisely;
   no 851 MB customer or synthetic file was required.
5. The focused Vault suite passed v1 snapshot verification and staged restore,
   plus its existing key, schedule, identity, and no-clobber cases.
6. Before import, the other Mac could not verify the encrypted snapshot. After
   importing the test recovery key into its own `ThisDeviceOnly` Keychain, it
   verified, searched by historical title, restored into a separate folder,
   and exported the preserved transcript as Markdown.
7. A missing synthetic thread was copied back without changing an unrelated
   pre-existing synthetic conversation. A different local file with the same
   thread ID was refused, with its bytes unchanged. The account-wide
   `codex_running` predicate alone was patched out for these isolated test
   homes, because the user's real Codex app remained open. Snapshot
   verification, collision checks, atomic addition, and post-write comparison
   ran unchanged. The customer guard is unchanged.

The test fixtures and recovery keys were exchanged only over authenticated SSH.
Test-only Keychain entries were deleted after both directions passed, and the
ephemeral GUI test jobs were unloaded. The signed-in GUI context was necessary
for Keychain use on the larger Mac; plain SSH returned “User interaction is not
allowed.” No user workflow was interrupted.

## Packaged-browser check on the original Mac

A freshly built, local-test-only app at source `5e70ad0` opened its bundled
engine against a disposable synthetic Codex home through the real loopback
browser UI. The browser found a missing conversation using its old title,
showed three distinct saved versions, labelled the shrunken version “Needs
review,” and opened an intact earlier version. A narrow 390-pixel viewport
kept the search and recovery actions readable. The folder chooser was not
exercised: the test supplied the disposable Vault path to the read-only field
in the browser, then used the ordinary UI controls. No live Codex home or
schedule was changed. This is packaged-engine and browser evidence, not
Gatekeeper acceptance or a complete buyer installation.

An initial isolated launch changed `HOME`, making the login Keychain
unavailable to the packaged helper. That test setup was discarded; the
successful pass retained the signed-in account's normal `HOME` while pointing
`--source-home` and `--state-dir` only at synthetic paths. Both disposable
test Keychain entries were removed afterward.

## Interactive Keychain interruption

A later local verification rerun produced an unexpected macOS Keychain password
prompt. The run was stopped without asking the Founder to enter or disclose a
password. No signing, notarization, customer-data migration, or release switch
was performed. The interrupted rerun is **not** a passing release check; the
pull request's Python 3.9 and 3.12 CI checks remain separate passing evidence.
Do not resume local Keychain, signing, or notarization tests until the exact
prompting operation is identified and a noninteractive, explicitly authorized
verification path is established. An unknown Keychain password is never a
reason to request a credential from the Founder in chat.
The source helper now supplies a noninteractive Local Authentication context
for its Keychain operations, so an interaction requirement should fail with an
explicit error instead of opening a helper password dialog. Its real
create/export/delete/import recovery-key round trip passed on disposable
macOS CI runners for both Python matrix jobs. That does not identify the
source of the earlier local prompt or clear the signed-release gate. Signing
and notarization can invoke Keychain independently of this helper.

## Disposable signing-path probe

A September 23 hosted macOS CI probe tried to sign a disposable executable
using a separate, temporary Keychain and a synthetic one-day identity. It
never imported the release certificate or key and did not access either
physical Mac's Keychain. A compatible PKCS#12 bundle imported, but the
self-signed identity was not trusted for code signing. An attempt to establish
test-only trust stalled and hit a two-minute step timeout. The experimental
probe was removed from the release branch rather than leaving a failing or
misleading check. This is **not** evidence that a dedicated Keychain can sign
the release without prompting; Developer ID signing and notarization remain
unverified for build 15.

The release builder now also accepts an existing, owner-only App Store Connect
Team API key for notarization, avoiding the locked notary-profile Keychain. This is
an unexercised route until a real authorized `.p8` key is available. It does
not solve Developer ID signing or establish a prompt-free release by itself.

## Read-only discovery check on the larger Mac

After the initial two-Mac synthetic acceptance, the source search was changed
to return one result per conversation, newest first, with paged results instead
of allowing repeated message hits to fill the first page. The complete local
suite passed 819 tests (12 skips) at `263c2a3`; both hosted Python CI jobs
passed. The larger Mac then passed all 13 focused search tests on an isolated
copy of the source, without changing its real Codex history.

A read-only check against the larger Mac's real, still-active history found a
conversation under one of its former indexed titles. A common content word
found that same conversation within the first 50 distinct results. The title
index and the app's displayed task name did not agree on the latest name; the
opaque thread identity, rather than either name, linked them. No private title,
thread ID, snippet, or transcript content is recorded here.

That Mac has tens of gigabytes of local rollout data, including a single
multi-gigabyte active transcript. A rare full-text query exceeded a bounded
30-second read-only probe. This is a real performance limitation, not a search
failure or proof of missing content. A separate **current and old titles**
search now reads the existing local title index without scanning transcript
content; on the same Mac it found the formerly named active conversation as
the only title match in 0.16 seconds. The title-only behavior passed focused
tests on both physical Macs. Full-text search remains available, but large
histories may take longer and are not claimed to have instant indexed search.

A fresh **local-test-only** build 15 from `c1c8705` passed strict ad-hoc
signature verification and the packaged-engine desktop suite (8 passes,
1 filesystem skip). That suite now requests the actual bundled Vault page,
creates a disposable renamed-title fixture, and finds it through the bundled
HTTP search route. This checks the packaged source path, not Developer ID
signing, Apple notarization, Gatekeeper acceptance, or buyer delivery.

The same local-test-only build was rebuilt from `8fdfc77` after the packaged
smoke assertion landed. Its ZIP SHA-256 was
`bbd4416668cd7d9c5714f1bd982a0c2d9e92e1b290a1ffe56b90ba9c092cc6f1`
on **both** physical Macs after authenticated SSH transfer. On the larger Mac,
the extracted app passed strict ad-hoc signature verification. Its bundled
engine launched against an isolated synthetic home and returned the same
active conversation for both an old title and a word in its appended message,
with the current title attached to each result. The loopback helper shut down
cleanly; the disposable test copy was not installed as the user's app. This
does not prove notarization, quarantined first launch, or a live buyer restore.

On the original Mac, a subsequent read-only full-text search for a distinctive
word found a **current, active** conversation in 0.14 seconds. This exposed a
usability gap: opening the result initially showed the beginning of a long
thread rather than the matching message. The candidate now records the match's
byte offset and opens there. The real matching record exceeded the 1 MiB page
preview budget, so the candidate shows a clearly labelled excerpt at the match
while leaving the exact full-thread Markdown export available. A read-only
recheck opened that match in 0.22 seconds. The complete local suite passed 822
tests (12 skips), including active and restored-backup jump-to-match cases and
an oversized-message excerpt case. No private conversation text or identifier
is recorded in this receipt. This is source-level evidence; the improvement is
not in the currently distributed signed/notarized build 14.

A fresh local-test-only build 15 from clean pushed source `9ca2c4f` then passed
strict deep ad-hoc signature verification and the exact bundled-engine desktop
suite (8 passes, 1 case-sensitive-filesystem skip). The bundled loopback
server found a synthetic active conversation by message text and returned its
matching message when opened at the search result's byte offset. The local
ZIP SHA-256 is
`38274369a2f83d3a6ee41c6ca0a87c39b2638c1b00b9f999087ac6082e1c681a`.
This is packaging evidence, not Developer ID signing, notarization, Gatekeeper
acceptance, or buyer delivery.

The larger Mac independently cloned pushed source `96c5a40` into an isolated
temporary checkout and passed all 69 focused Vault and setup tests under its
Python 3.9.6 runtime, including active search-to-match, restored-backup
search-to-match, oversized matching-message excerpt, and mismatch refusal.
The checkout was clean and deleted after the run. This test neither read nor
changed that Mac's real Codex history, Vault schedule, or installed app.

A final identity review found that two `needs_review` captures at the same
source path but with different bytes could otherwise appear as one history.
The candidate now keeps those captures in distinct review-only groups without
changing verified-ID grouping or the path hint for a missing ID. The local
suite passed 823 tests (12 skips), including a regression for this boundary.
On the larger Mac, an isolated checkout of exact pushed source `7ec3028`
passed all four identity-only tests under Python 3.9.6. Two encrypted-history
tests in the same focused file could not create a disposable Keychain key in
that SSH session; this is a Keychain test-environment failure, not a passing
two-Mac encrypted-backup result for this exact commit. Earlier physical
encrypted-history acceptance remains recorded above. The isolated checkout
was clean and removed; neither Mac's real Vault or Codex history was changed.

An exact-source local-test build 15 at `d5f973a` passed strict deep ad-hoc
signature verification and the nine-case packaged desktop suite (eight passes,
one case-sensitive-filesystem skip). Its bundled build receipt names that
commit and `local-test`; ZIP SHA-256 is
`d2531f81467fa8081f05cea184d86dfd3e2ddec067d5cc5b1123d757563074c0`.
This artifact is not Developer ID signed or notarized and is not for customers.

## Claim boundary

This is evidence for the tested Codex Vault engine on these two Macs, not every
future Codex format or macOS version. A scheduled runner invocation is not
proof that launchd fires at the desired time days later. A local snapshot is
not off-device insurance unless the selected folder's sync actually completes.
Read/export of a verified version is the dependable recovery path; reopening a
copied thread inside Codex remains best-effort. Protection begins only after a
verified snapshot, and the full automatic-protection state requires a later
successful scheduled run. The `PreCompact` hook remains unshipped and
unadvertised pending desktop rewrite-order and encrypted-checkpoint proof.
