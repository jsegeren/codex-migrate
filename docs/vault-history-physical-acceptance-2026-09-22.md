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
API key for notarization, avoiding the locked notary-profile Keychain. This is
an unexercised route until a real authorized `.p8` key is available. It does
not solve Developer ID signing or establish a prompt-free release by itself.

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
