# First Developer ID candidate

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

Pending: Apple's explicit Accepted result, staple/validation/Gatekeeper checks,
final archive checksum, exact downloaded clean-Mac launch, and two-Mac
migration/recovery acceptance. Nothing here opens paid checkout.
