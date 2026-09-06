# Packaged retry-fix candidate — September 5, 2026

Status: unsigned engineering candidate, not approved for sale or distribution.

## Exact artifact

- Clean source: `286f6b9a29d95b5c557b3fba31da69f143ddcb9a`.
- Version/build: `0.1.0` / `1`, arm64.
- Filename: `Codex-Migrate-0.1.0-build1-arm64-LOCAL-UNSIGNED.zip`.
- SHA-256: `b6326ea0ae3647171392153b7e692c200f4245ea399c53105eb8877f62f065bb`.
- Retained local artifact, app and receipts: ignored `build/rc-286f6b9/`.
- Toolchain: Python 3.12.3, PyInstaller 6.22.2, macOS 26.5.1 arm64.

This candidate includes the distinct-attempt backup naming fix for full
migration, CLI skills export and browser skills repair. Its source passed the
119-test disk-pressure/backup/transaction/components/recovery run documented in
[the failure-mode matrix](failure-mode-matrix.md#protected-phase-extension-and-retry-defect).
Those source-level tests are not claimed as packaged cross-Mac acceptance.

## Build and verification

The supervising task created one clean sibling worktree on
`codex/rc-retry-2026-09-05`, pushed that exact source branch to origin and ran
`desktop/build.py` using the existing isolated build environment. The builder
recorded `source_dirty: false` and `build_mode: local-test`. No untracked social
image drafts entered the build.

The completed output was moved to the retained directory above. The empty build
directory and clean task worktree were removed, followed by Git worktree prune.
No manual build worktree remains; the exact source is preserved on origin.

The ZIP's independent SHA-256 check passed. It was extracted outside the checkout
to a fresh temporary directory, and the extracted app passed
`codesign --verify --deep --strict`. Embedded build metadata matched the original
app. This is an ad-hoc signature check, not Developer ID, notarization or
Gatekeeper approval.

With `CODEX_MIGRATE_TEST_ENGINE` pointing to the extracted executable,
`PYTHONPATH=src:tests python3 -m unittest test_desktop -v` passed eight tests and
skipped one filename-collision test requiring case-sensitive storage. The suite
includes actual helper/dashboard startup and graceful shutdown, authorization
and read-only boundaries, malformed SSH-bridge rejection, Git/configuration
scope checks, native saved-setup checks and release-builder guard tests. Packaged
engine child processes use a system-only PATH without Python/DYLD overrides.
The temporary extraction was removed after all test processes exited.

## Not yet proved

No destination was contacted during these package tests. Authentic Codex
reopening, remaining two-Mac interruption and permission checks, native
VoiceOver, Apple activation/signing/notarization, and the exact signed buyer
download and first launch remain open. The existing disposable-account helper
was not stopped or replaced, and no personal workspace or login was touched.

Use this candidate, rather than the older `e6abe13` package, for the next
authorized engineering device check. Do not sell or advertise this ZIP as the
signed release.
