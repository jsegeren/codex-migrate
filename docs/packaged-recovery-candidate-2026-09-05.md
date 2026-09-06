# Packaged recovery candidate — September 5, 2026

Status: unsigned engineering candidate, not approved for sale or distribution.

## Exact artifact

- Clean source: `e6abe132561b6ce2fca96dc7d10f62ae0d5f820a`.
- App version/build: `0.1.0` / `1`, arm64.
- Filename: `Codex-Migrate-0.1.0-build1-arm64-LOCAL-UNSIGNED.zip`.
- SHA-256: `fbdf29bfac5bd5b12b667451586c5e21fe333684d0cf93ae96ba0b0dd1e0a0aa`.
- Local retained artifact and receipts: ignored `build/rc-e6abe13/`.
- Toolchain: Python 3.12.3, PyInstaller 6.22.2, macOS 26.5.1 arm64.

The current supervising task owned one clean sibling worktree on
`codex/rc-recovery-2026-09-05`, pushed its exact source to origin, and invoked
the existing `desktop/build.py` with the isolated build environment. No image
drafts or other uncommitted website changes entered that source tree. The build
record reports `source_dirty: false` and `build_mode: local-test`.

The completed artifact was moved into the retained local build directory. The
clean worktree was removed with Git and pruned; no manual worktree remains.
The immutable source remains reachable on origin. Generated scratch files were
removed; existing cross-Mac fixtures and backups were not touched.

## Actual package checks

The desktop regression test now inspects the actual engine's HTTP page for the
recovery next action, its position beside status, disclosure target and event
binding. This complements the existing JavaScript state matrix and rendered
source-level recovery journey; a source-template check alone cannot catch an
old packaged engine.

1. With `CODEX_MIGRATE_TEST_ENGINE` pointing to the newly built executable,
   `PYTHONPATH=src:tests python3 -m unittest test_desktop -v` ran nine tests:
   eight passed; the case-sensitive filename-collision fixture was skipped on
   this volume.
2. The exact ZIP checksum independently matched its build receipt.
3. The ZIP was extracted to a fresh temporary directory, outside the checkout,
   after the build worktree had been retired. Its ad-hoc signature passed
   `codesign --verify --deep --strict`. This is not a Developer ID signature,
   notarization or Gatekeeper/quarantine approval.
4. All nine desktop tests were repeated against the extracted executable:
   eight passed and the same filesystem fixture was skipped. Child engine
   processes use a system-only PATH and omit Python/DYLD environment overrides.
   Tests cover helper startup/shutdown, read-only setup, malformed SSH-bridge
   rejection, Git dependency inventory, support-report build attribution and
   unresolved recovery refusal. No remote destination was contacted.
5. Negative control: the previous `b9fb1a04` package failed the new dashboard
   assertion because its recovery next action is absent. That expected failure
   proves the check distinguishes the old package from this candidate. The
   older long-running test-account helper was not terminated or replaced.

These are local packaged-engine checks on the development Mac, not a fresh
Mac without developer tools, full native UI acceptance, an end-to-end physical
transfer or authentic Codex reopening. No real Codex process guard was bypassed
and no active workspace or login identity was selected.

## Next release evidence

The isolated source helper remains running, but the prior account-driving
authorization has expired; a noninteractive privilege check requires a password.
No privileges were broadened. Authentic Codex test conversations, remaining
physical failure cases, native VoiceOver, signing/notarization and the exact
signed buyer download/launch remain open. Use this artifact for the next
authorized device check; do not rerun migration on the maintainer's workspace.
