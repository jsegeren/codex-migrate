# Scoped cross-Mac acceptance — September 5, 2026

Status: **engineering progress, not release approval**.

## Receiving-Mac reboot: verification still pending

The maintainer reported an unexpected receiving-Mac crash and restart after the
synthetic installation, while home-path compatibility remained unresolved.
Fresh SSH inspection confirmed roughly four minutes of uptime and the same
independently pinned host identity. The personal-account SSH connection worked
without a password prompt. Metadata checks found the disposable destination
account, its installed `.codex` directory, its recorded full-install backup,
and the workspace-skills fixture still present. No destination migration helper
was running. The separate time-limited source acceptance runner had exited;
the source browser helper remained alive.

These are presence and process checks, not post-reboot content verification or
proof of recovery from a crash during replacement. Protected test-account
contents remain unreadable through the personal-account connection. No
migration was restarted, no permissions were relaxed, and no backup was removed.

A fixed-scope home-path setup launcher was copied exclusively to the receiving
Mac's `/Users/Shared/Finish Codex Migrate Test Setup.command`. Its received bytes
and shell syntax were checked; it has **not been executed**. It verifies the
receiving Mac's pinned public host identity and personal administrator account,
then invokes the production exclusive compatibility command only for the two
disposable home paths. It requires an administrator prompt, rejects conflicting
paths, and cannot overwrite an existing entry. The missing link and subsequent
Git/content verification remain open. Restarting the source acceptance runner
also requires renewed authorization to execute as the isolated source account.

Candidate source: `54cfa832753e70d10bf3b07b935d1e8e059b92ff`.
Unsigned arm64 ZIP SHA-256:
`dd429acebf7139e061338f86f57412a359388741bb64ce2a8d584902e2833ccc`.
Tester: supervising Codex, using two physical Apple Silicon Macs and separately
authorized disposable standard accounts with different usernames. Personal
workspaces were outside the test scope. Private connection material stayed in
the source test account; SSH host verification remained strict.

## Full synthetic migration

The prior candidate successfully staged the fixture, but final delta failed on
Apple openrsync's handling of a bracketed, scoped IPv6 destination. The fixed
packaged engine resumed retained staging rather than deleting it. It selected
the direct IPv6 interface among four candidate addresses. Reported in-memory
route probes were approximately 371–387 Mbps; these are not sustained workspace
transfer benchmarks or proof of a particular cable specification.

Installation evidence verified one active and one archived synthetic transcript,
retained Codex state, both selected Git and managed-worktree roots, one personal
skill, backup correctness, and preservation of the dummy destination identity.
An independent SSH read checked these outcomes:

- Original destination rules, transcript and workspace are retained in backup.
- Installed rules and SQLite fixture match the expected synthetic content.
- Main and linked-worktree unfinished files and an untracked main file match.
- A relative symlink and empty directory are preserved.
- An unrelated destination skill is unchanged.
- The terminal receipt records installation, and no pending transaction remains.

The app remains `needs_attention / path_compatibility`: the old home path is
missing on the new Mac. It does not silently claim a working restored workspace.
The fixture's Git branches and stash were within the content-verified copy, but
different-home Git command usability remains unproved until compatibility is
resolved. Synthetic JSONL/database fixtures are not authentic Codex chats.

## Controlled interrupted transaction and packaged recovery

This exercise used new destination-only synthetic folders, separate from the
installed migration fixture. The exact candidate's production transaction writer
and destination lock created a frozen, verified backup and pending record.
The harness moved aside the original test entry, introduced newer entries, and
killed the remote shell with SIGKILL before transaction completion. No production
guard was weakened, and no source data was changed.

The unmodified packaged engine ran in a separate, token-protected loopback
dashboard with the same pinned SSH destination:

1. Check recovery returned `backup_verified` for the exact two-item scope.
2. Explicitly confirmed Restore backup returned `restore_verified`.
3. Its state was `interrupted / restored`, with no migration completion receipt.
4. After helper shutdown and restart, Check recovery again returned
   `restore_verified`.
5. Independent reads verified original content restored, newer content retained
   in the recovery slots, the originally absent entry absent again with its new
   content preserved, backup content unchanged, a complete recovery record, and
   no pending transaction. The full-migration fixture remained present.

The temporary recovery helper was stopped. Original backups, recovery evidence,
and displaced data are retained in the disposable accounts. This proves real
cross-Mac packaged recovery for the injected transaction. It does **not** prove
a crash during the complete packaged installer, a disk-full/power-loss outcome,
or authentic Codex application usability.

## Packaged personal-skills-only export

The actual bundled engine's `export --apply --component personal-skills` path
completed across the two Macs with exit zero, `applied: true` and
`backup_verified: true`. Private before/after content-and-structure snapshots
proved that the destination Git tree, unrelated skill, and Codex tree (excluding
the two identity files, which the independent snapshot never opened) were
unchanged. No source file was modified. This verifies the packaged CLI repair
path, not the separate browser skills-only pause/resume UI. The local bounded
report is `CodexMigrate-Synthetic-4aw_ahb7/result.json`; its unused
`skills_verified: null` field reflects a nonexistent CLI result property, not a
failed verification. The CLI's real receipt fields were `applied` and
`backup_verified`.

## Browser skills controls and newly discovered preflight issue

A separate 128 MiB synthetic workspace skill was transferred through the
packaged setup/dashboard HTTP controls. Pause interrupted a live rsync process
and retained 3,425,962 bytes. Stop safely preserved that partial tree. After
helper restart, mode/scope and the staging owner ID were retained; Resume was
rejected while changes were disabled. Re-enabling changes and Resume reused the
same staging. Finalize without its separate confirmation was also rejected.
These are real packaged control-API checks, not rendered browser/accessibility
acceptance. Local reports: `CodexMigrate-Synthetic-3zazb77m/result.json` and
`CodexMigrate-Synthetic-53f6tbt_/result.json`.

Confirmed finalization then failed before backup/replacement because this new
test project did not yet exist on the receiving Mac. Recovery inspection found
no pending transaction. The old package exposed only `remote command failed`
and discovered the requirement after transferring the whole skill. This is a
real UX defect, not a successful browser-repair result. The source fix moves
the existing-project requirement into shared CLI/browser preflight, rejects
linked or missing parent paths without creating folders, and explains that a
workspace-skills repair updates an existing project rather than migrating it.
A regression covers both missing and linked destination project roots before
any staging or backup.

The retry used clean source `12f63334509f26b501cdaf24b78449f210f4dc4b`,
packaged ZIP SHA-256
`dea13079338eb8f5709b12325c689f82e8e91786c8c88cf463ed5ba808b8a4b0`.
The new package rejected the still-missing project during inspection with the
specific explanation. After the harness created only the matching disposable
destination project, Resume reused the same staging owner ID and Finalize
completed with one verified workspace skill and verified backup. Independent
reads compared the 128 MiB installed payload with the source, confirmed no
pending transaction and preserved full-workspace data. Returning to the prior
full setup retained its exact installation receipt. Report:
`CodexMigrate-Synthetic-kt7seh4w/result.json`.

This is a successful real two-Mac packaged skills control-API run. It does not
cover rendered UI, VoiceOver, a physical cable pull, OS reboot, or first launch
of this newer bundle on the target Mac. The prior full migration and controlled
recovery ran the preceding candidate; the newer bundle changes shared selective
preflight only.

## Real SSH access removal

The `dea13079` package was copied to the destination disposable account,
checksum-verified, and checked with `codesign --verify --deep --strict`. Separate
packaged source and receiver helpers ran with fresh owner-only registries. Their
real connection-card HTTP endpoints generated, approved and accepted a new
temporary key. The accepted target identity matched the independently pinned
original connection. Private keys and loopback tokens stayed on their owning
Macs; no password was requested.

A fresh SSH process using only this new key authenticated as the destination
test account. After the receiver's Remove access endpoint completed, a second
fresh process failed with SSH exit 255 and `Permission denied`. Multiplexing and
agent fallback were disabled. The original independent pinned connection still
authenticated, demonstrating that the removal did not strand the existing test
setup. Both temporary helpers stopped; a separate read verified the receiver
process was gone, its revocation record remained, no migration transaction was
pending, and the original installed receipt remained at `path_compatibility`.

Reports: `CodexMigrate-Synthetic-51qnp907/result.json` and
`CodexMigrate-Synthetic-dzd6sfsy/result.json`. This closes the real SSH
revocation/isolation check through the packaged API, not rendered browser
confirmation, key-expiry timing, or signed/quarantined first launch. Temporary
private connection state and the engineering package remain in the disposable
accounts for evidence review; no personal account's access was changed.

## Rendered installed-workspace and Help checks

Stable Chrome ran headlessly in the disposable source account against the
actual packaged helper, with a fresh browser profile and without switching the
maintainer's desktop session. The first rendered inspection showed that the
home-path next action was buried below scope/backup information and six disabled
transfer buttons. Source `cc86caf90b48d1126add618922c46af7fe52efc7` moves that
action directly beneath the status and hides obsolete transfer controls after
installation, while retaining controls for retryable transfers.

Clean source produced unsigned ZIP SHA-256
`b9fb1a040a396a70ae3a8f0d1bc13560c379b51b58ed7a1a516f1d192b2cc052`.
An orderly helper update retained the existing installed receipt and reopened
the full configuration read-only. Screenshots at 1280, 390 and 320 pixels show
the next action beneath the status, without horizontal overflow or underlined
button text. The supervising agent inspected the desktop and narrow rendering.

Keyboard activation of the next action opened and focused the home-path
disclosure. The read-only cross-Mac path check returned focus to its button.
Keyboard Help/report preparation focused the diagnostic preview; a real browser
download matched that preview byte-for-byte. The report excluded the tested
private home paths, hostname and loopback token. No email was sent. The first
path-check exercise did not complete within its browser step; a separately
instrumented repeat passed. A further fresh-helper restart and keyboard run
also passed, with the path check taking 7.001 seconds and the installed receipt
unchanged before and after. This is not a claim of reliable network timing.

Axe-core 4.8.3 found no violations of its selected WCAG 2.0/2.1 A/AA rules at
those three widths, with 21 passing rules and color-contrast marked incomplete
because of the backgrounds. Manual CSS color-pair calculations found 9.08:1
for muted text against the brightest background-gradient endpoint, 6.99:1 for
the next-action text, and 5.00:1 for the Help email-button text. These bounded
checks are not whole-app WCAG certification. Increased text spacing also caused
no horizontal overflow at those widths. Native VoiceOver, permission dialogs,
setup/pairing, and the complete rendered migration/recovery journey remain open.

Local reports: `CodexMigrate-Synthetic-_81vt4xh/result.json` (original layout),
`CodexMigrate-Synthetic-xekezj7u/result.json` (updated layout/initial keyboard
exercise), `CodexMigrate-Synthetic-dkinbgfo/result.json` (keyboard/Help pass),
and `CodexMigrate-Synthetic-j5nuleud/result.json` (axe/text spacing). Screenshots
stay alongside these local reports, not in the public website assets.
The fresh-helper repeat is `CodexMigrate-Synthetic-goao06tf/result.json`.

## Automated checks at this checkpoint

`PYTHONPATH=src:tests python3 -m unittest test_recovery test_restore
test_guided_recovery test_machines test_transport test_pairing`:
98 tests passed. Separate actual-bundled-engine desktop tests ran nine checks:
eight passed and one case-sensitive-filesystem fixture skipped.
After the destination-project fix, all 49 setup/component/browser-engine tests
passed. The new bundle's actual-engine desktop suite also ran nine checks:
eight passed and one filesystem fixture skipped.

The broader source regression run after access-removal acceptance completed
`python3 -m unittest discover -s tests -p 'test_*.py'`: 588 tests, 581 passed,
seven skipped, no failures (131.674 seconds). `npm test` completed 186 tests:
185 passed, one skipped, no failures. The Node database integration test is
skipped without its explicit test-database environment. These are local
regressions, not new live commerce or Apple checks. The Python build tests print
simulated signed/notarized success for mocked temporary fixtures; no real
Developer ID signature or notarization was produced by this run.

After the next-action UI change: 29 dashboard/Git-readiness Python tests passed;
eight focused JavaScript state/Help tests passed; the complete Node suite had
187 passes and one explicit integration skip. The exact new bundled engine's
desktop suite had eight passes and one filesystem skip.

## Evidence retention and remaining gates

Private, bounded reports remain under `/Users/Shared` on the source test Mac:
`CodexMigrate-Synthetic-cmjh3mg3/result.json` (resumed installation),
`CodexMigrate-Synthetic-yhg41dp9/result.json` (independent installation checks),
and `CodexMigrate-Synthetic-4sqzb7jk/result.json` (recovery/restart checks).
Account-local state retains the full private transaction evidence. These local
reports are not shipped assets and contain no credentials or content digests.

Remaining release gates include different-home compatibility and Git usability,
real Codex-created project/loose/archived conversation reopening and continuation,
packaged browser selective-repair and transfer interruption acceptance, native
permissions/accessibility, Apple activation and Developer ID signing/notarization,
and delivery of the actual approved artifact through the purchase flow. Checkout
remains closed. Consult the main release-readiness gate map for the complete scope.
