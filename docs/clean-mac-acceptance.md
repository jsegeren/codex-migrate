# Clean-Mac release acceptance

Run this against an exact committed, packaged candidate. This is an execution
checklist, not a completed receipt. Local unit tests and matching copied bytes
cannot substitute for these observations. Keep checkout closed until the
release gates in [release readiness](release-readiness.md) pass.

## Access and isolation

- Use two different physical Macs and disposable standard macOS accounts on
  both. Do not select the maintainer's active workspace or home. Other users can
  remain logged in; use Fast User Switching for graphical checks.
- A maintainer creates/unlocks the accounts and approves required macOS
  permissions. Never place passwords, private keys, login tokens, or personal
  transcripts in a test receipt, shell command, screenshot, or public issue.
- Enable Remote Login for the receiving test account only as needed. Open the
  same candidate app in both test accounts and exchange its connection cards
  directly. Do not bypass host verification or copy existing private SSH keys.
- Confirm both Macs' account names, home paths, OS versions, architecture,
  Codex version, available space, and connection route. Redact private machine
  details in published evidence. Different test usernames are required for
  home-path acceptance.
- The new Mac must launch the packaged helper without developer-installed
  Python or this repository. Record which system tools were already installed
  and which the guided setup required; hiding developer tools from PATH on the
  old Mac is not a clean-Mac test.

## Two separate data checks

**Synthetic engine fixture.** The existing maintainer script
`tests/manual_disposable_fixture.py` is restricted to the dedicated
`codexmigratesource` account and refuses nonempty fixture roots. It creates
local Git branches, a stash, a linked worktree, uncommitted/untracked files,
skills, transcript-shaped files, and a fixture SQLite database. Run it only
after validating that disposable account; do not rerun it over existing data.
Use it for safe copy, backup, corruption, and interruption exercises.

**Real Codex application fixture.** The synthetic database and transcript-shaped
files are not authentic Codex conversations. They cannot prove a chat opens.
In a separate disposable source account, open Codex and create harmless real
test conversations through its supported UI: a project conversation, a loose
conversation, and an archived conversation. Use only invented test content.
Add a recognizable non-secret setting and a harmless custom skill through the
normal supported setup. On the destination test account, install Codex and
sign in once before migration. Do not fabricate or hand-edit Codex's database
schema to make this check pass. Record the exact app versions tested.

## Candidate checks

1. **First launch and setup:** open the package from Finder. Confirm there is
   one browser setup flow, working keyboard navigation and Help, readable
   zoom/reflow, and usable VoiceOver labels/focus. Test a denied folder permission
   and an invalid connection card; both must explain the next action without
   omitting selected data. Reopen at each card step and confirm saved setup.
2. **Scope and destination:** inspect full migration and a skills-only repair.
   Compare the discovered/selected lists against the fixtures. Confirm excluded
   login identity and unrelated destination folders remain excluded. Reject a
   wrong destination or unsupported configuration before copying.
3. **Interruption:** during a sufficiently long synthetic transfer, test Pause,
   Resume, Stop safely, helper restart, loss of Wi-Fi, and cable removal where a
   supported wired route exists. Restore connectivity and resume the same scope.
   Confirm retained staging is reused and the route/status are understandable.
   Do not disconnect during a protected replacement merely to test staging.
4. **Backup and replacement:** create distinct harmless destination data before
   finalization. Verify a backup is required, preserved, and checked before
   replacement. Exercise low space and failed verification with disposable data;
   they must stop rather than report success. Record the original destination's
   recovery result, not just the existence of a backup directory.
5. **Protected-phase recovery:** use only synthetic accounts/data for a planned
   interrupted installation. Follow [recovery](recovery.md); first check the
   saved transaction and verified backup, then explicitly restore if offered.
   Confirm original destination data and displaced newer files are preserved as
   described. Keep both endpoints and backups until the outcome is verified.
6. **Workspace usability:** after a successful full migration, verify the
   different-username home-path check, branches, stash, index/status, untracked
   files, and linked worktree with the old Mac disconnected. Open all three
   real test conversations and continue an active one. Verify the chosen setting,
   project organization, and custom skill in Codex. A count or checksum is not a
   replacement for these application-level observations.
7. **Selective repair:** transfer only the selected custom skills. Confirm the
   skill works and unrelated conversations, settings, repositories and skills
   are unchanged. Exercise interrupted staging and explicit finalization here too.
8. **Access cleanup:** remove the dedicated connection access from the receiving
   helper after recovery testing. Verify a new connection with that key is
   refused; existing independent access must remain usable. Do not confuse an
   already-open session with a new login. Retain test data until review is complete.

## Signed release and evidence

After the intended Apple membership activates, build with the existing
`desktop/build.py --release --identity <Developer-ID-name> --notary-profile
<keychain-profile-name>` workflow. Never put credential values in those arguments.
Verify the exact artifact's signature, notarization/staple, version, checksum,
and quarantined download/first launch on the clean Mac. An unsigned candidate
does not satisfy this final gate. Payment/delivery/refund acceptance is separate
and remains closed pending the selected Stripe route's account/tax setup,
verified delivery, and an approved artifact.

For each numbered check record: candidate SHA and artifact checksum, environment,
date/tester, action, observed result, pass/fail, and any redacted evidence location.
Record skips and failures explicitly. Do not publish raw logs or workspace data.
Any unresolved safety, usability, or accessibility failure blocks release; the
maintainer decides how to resolve it before rerunning the affected checks.
