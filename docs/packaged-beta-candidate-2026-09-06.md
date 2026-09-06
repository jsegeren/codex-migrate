# Unsigned beta candidate — September 6, 2026

Status: engineering candidate; not yet approved for customer delivery.

## Connection check

The Founder ran the existing `check-test-connection.py` as the disposable
`codexmigratesource` account. The sanitized result in
`/Users/Shared/CodexMigrate-Preflight-zbj8hduz/result.json` confirmed source-account
identity, accepted pairing, SSH into the disposable destination, packaged-engine
startup, source inventory and migration preflight. `migration_started` was false.

This was a one-shot check using the older installed engineering package. It did
not grant this supervising task persistent execution access to that account.
The report's `destination_codex_initialized` field establishes required files
exist, not genuine Codex sign-in or successful reopening of authentic chats.

## Fresh artifact

- Clean source: `28d5b10299d5674769afb2ac67942976dc437350`.
- Source preserved on origin branch `codex/beta-candidate-2026-09-06`.
- Version/build: `0.1.0` / `1`, arm64, local-test mode.
- File: `Codex-Migrate-0.1.0-build1-arm64-LOCAL-UNSIGNED.zip`.
- SHA-256: `b70a7a6d95336073929914355904cc4be0442fcf1c6ae45f18c094df8156f719`.
- Retained app, archive and build receipts: ignored `build/rc-28d5b10/`.
- Toolchain: Python 3.12.3, PyInstaller 6.22.2, macOS 26.5.1 arm64.

Built through `desktop/build.py` in a clean sibling worktree. Independently
checked the archive SHA-256, extracted it into a fresh temporary directory, and
verified `codesign --verify --deep --strict` on the extracted app. This is an
ad-hoc signature, not Developer ID, notarization or Gatekeeper acceptance.

The extracted engine passed eight `test_desktop` tests, with one case-sensitive
filesystem test skipped. The suite exercises the real helper/dashboard process,
authorization/read-only boundaries, malformed SSH bridge rejection, Git and
configuration checks, and build guards. All 11 `test_build` tests passed; their
notarization results are mocked and do not indicate an Apple submission.

No destination was contacted by these new package tests. The running disposable
account helper was not replaced, and no personal workspace or authentication was
accessed. Authentic Codex-created project, loose and archived conversations still
need migration and successful reopening/continuation on the new Mac. Existing
synthetic transfer/recovery evidence does not substitute for that acceptance.

The unsigned paid-beta path can proceed without Apple only after its remaining
acceptance conditions in `commercial-edition.md` are met. General self-service
checkout remains closed. This candidate was not uploaded, sold or delivered.
