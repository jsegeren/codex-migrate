# Scoped cross-Mac acceptance — September 5, 2026

Status: **engineering progress, not release approval**.

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
any staging or backup. A fresh packaged retry is required for this source fix.

## Automated checks at this checkpoint

`PYTHONPATH=src:tests python3 -m unittest test_recovery test_restore
test_guided_recovery test_machines test_transport test_pairing`:
98 tests passed. Separate actual-bundled-engine desktop tests ran nine checks:
eight passed and one case-sensitive-filesystem fixture skipped.

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
