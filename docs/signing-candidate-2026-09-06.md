# First Developer ID candidate

## Build 3 checkpoint — September 6 late evening

The current release task owns the reused sibling worktree
`/Users/jsegeren/Git/codex-migrate-release-build`, on pushed branch
`codex/signed-candidate-build3-2026-09-06`, exact clean source
`e542160fe8399971ee4827625c2bf3096a9497c2`. Build 3 includes the reproduced FIFO
backup-verification fix; it does not claim to resolve the still-unclassified
two-Mac backup failure. The source change passed 679 Python tests (667 passed,
12 skipped); the build-number-only change passed all 13 builder tests.

The real builder compiled and Developer ID signed the app at
`build/desktop-u4d_z5m4/Codex Migrate.app`. Embedded-code checks, outer strict
signature verification and the engine-version check passed. Independent outer
signature verification passed again. The actual packaged engine then ran nine
desktop checks: eight passed, one filesystem-specific skip.

Notarization submission failed before a submission receipt was saved. Read-only
history queries returned exit 69 with a missing-Keychain-profile-item error.
The user login keychain remains the default and only user search-list keychain.
The Mac is locked; the cause of profile unavailability is not established.
No new Apple job or final release ZIP is confirmed, and no submission retry was
attempted. Reconcile history/profile access before submitting again. Build 2,
its accepted archive and the active failed-test helper are unchanged.

Retain this clean worktree and its signed app for reconciliation and completion;
do not rebuild or discard the evidence solely because the command exited.
Retirement deadline: September 13, 2026, or sooner once the artifact is safely
preserved and notarization no longer depends on this worktree. No process is
still running for this build. Public checkout remains closed.

## Earlier build history

The Apple account credential was validated and stored in the local notarytool
Keychain profile. No credential value is retained here. Signing uses Team ID
`P9J3JK79KQ`; the enrollment ID is not the signing team.

The combined source at `1ffa63a0b002814685cd472dcd43e0e00174c8db` ran 668
tests: 656 passed and 12 skipped. Mocked release output in that suite is not
an Apple submission.

An actual clean arm64 build of version 0.1.0 build 1 was Developer ID signed
and submitted as `1fedcddd-c0b0-4632-a6c6-4827cfecaddc`. Apple returned `Invalid`:
the embedded `Python.framework/Versions/3.12/Python` signature was invalid.
Direct local verification reproduced “code has no resources but signature
indicates they must be present,” although outer app deep/strict verification
passed. No release ZIP was published.

PyInstaller onedir signs the individual binaries before assembling framework
resources. A copied framework needs its bundle resource seal afterward. A
disposable copy of this exact rejected Python framework passed direct binary
and framework verification after signing the framework bundle as a whole.
The original submitted app and failure receipt were left unchanged.

The builder now seals embedded frameworks inside out after collection, then
directly verifies every embedded Mach-O file before sealing the outer app.
Notarization resume also verifies embedded code. Signing does not use `--deep`;
verification does. Build 2 distinguishes the repaired candidate. Two added
regressions cover framework ordering/flags and direct binary verification,
including propagation of signature failures. All 13 builder tests pass.

This task owns the single sibling `codex-migrate-release-build` worktree on
`codex/signed-candidate-2026-09-06`. Retain it only while Apple processing and
artifact verification are active; retire at handoff, or no later than
September 13, 2026 if an external gate prevents completion. No checkout,
production download or main-branch publication is authorized by a signing pass
alone. Clean-Mac launch and real two-Mac migration/recovery remain required.

Signing references: [Apple nested-code guidance](https://developer.apple.com/documentation/xcode/using-the-latest-code-signature-format)
and [macOS Code Signing In Depth](https://developer.apple.com/library/archive/technotes/tn2206/).

## Repaired build 2 submitted

Exact clean source: `1ee2e41` on the pushed signed-candidate branch. The builder
produced arm64 version 0.1.0 build 2 in
`codex-migrate-release-build/build/desktop-bnuxiqz9`, directly verified the
embedded binaries, then submitted job `da35b4d5-c297-476c-9036-13be0ea4c910`.
Apple's authenticated job-info response reports `In Progress`. The existing
builder is waiting on that same job and has not published a final archive.
Retain this worktree/output while the process remains live. If it exits before
completion, inspect its receipt and use the guarded resume path as appropriate;
do not blindly resubmit. The rejected build 1 output remains separate at
`build/desktop-_ddvfhfh`.

All 13 builder regressions pass on Python 3.9 and 3.12. The actual signed
build-2 engine passed eight checks with one case-sensitive-filesystem skip
using `CODEX_MIGRATE_TEST_ENGINE` and `test_desktop`, with Python/DYLD environment
overrides stripped and system-only PATH for packaged invocations. Temporary
fixture state was removed by test cleanup; no real workspace was transferred.
The disposable framework signing proof was moved to Trash and is recoverable.

The complete suite was then rerun from the exact clean build-2 source:
670 tests ran in 143.6 seconds, with 658 passing and 12 skipped. The suite's
mocked signing/notarization messages are not the real Apple job outcome.

## Apple accepted; exact archive prepared for two-Mac testing

Apple accepted submission `da35b4d5-c297-476c-9036-13be0ea4c910`. The original
builder exited successfully and completed stapling, validation, Gatekeeper
assessment and archive creation at `2026-09-07T02:22:52Z`, approximately 42 minutes
after submission. Independent signature, staple and Gatekeeper checks passed;
Gatekeeper reports `source=Notarized Developer ID`.

- Clean source: `1ee2e410b13799941cecbaca5e8525cf35de02dc`.
- Artifact: `Codex-Migrate-0.1.0-build2-arm64.zip`.
- SHA-256: `e6beb05820aaef74edbbb5c3247c898d4bef7f0c1dac1a813394e71a7289a40b`.

The archive checksum was verified, then the archive was extracted into a fresh
Shared directory. That extracted app passed signature, staple and Gatekeeper
checks before becoming the test harness's `isolated-candidate`. The enclosing
directory is mode 755; the actual harness's cross-user access/signature preflight
and direct verification of every embedded Mach-O also pass. No test runner or
isolated-candidate process was running at replacement. The earlier candidate is
preserved separately as `isolated-candidate-build1-preserved`; no test-account
state, authentication, staging or backups were changed.

The exact archive and build/notary/checksum receipts are retained alongside the
extracted app under `/Users/Shared/CodexMigrate-Authentic-20260906/isolated-candidate`.
This is local artifact verification, not an actual downloaded clean-Mac launch
or completed two-Mac migration/recovery acceptance. Those gates and real paid
delivery acceptance remain open. Nothing here opens paid checkout.

The build process has exited successfully. After rechecking the retained Shared
archive checksum and confirming the exact source SHA on origin, the clean manual
build worktree was retired with `git worktree remove` and `git worktree prune`.
Original build outputs (including the rejected build 1 evidence) were moved
recoverably to `/Users/jsegeren/.Trash/codex-migrate-build-evidence-20260906`;
disposable bytecode caches are in the adjacent `codex-migrate-build-pycache-20260906`.
The accepted artifact remains outside Trash in the Shared test directory above.
The temporary Apple check was removed from the existing daily star automation
after this terminal verified result; daily star monitoring remains unchanged.
