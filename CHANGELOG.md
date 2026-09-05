# Changelog

## Unreleased

- Add a guarded `--resume-notarization` release-builder path that continues the
  exact saved Apple submission after interruption without rebuilding,
  re-signing, or submitting twice.
- Clarified common SSH failures in the app: an untrusted or changed host key
  now says that authentication—and therefore the user's password—was never
  attempted; key-authentication, name-resolution, Remote Login, and network
  failures have separate next actions.

## 0.1.0 — 2026-09-03

- Added content-free local inventory.
- Added strict SSH preflight and route reporting.
- Added resumable rsync staging for Codex state and selected workspaces.
- Added pause, resume, safe stop, and final-delta controls.
- Added destination backup and target-auth preservation checks.
- Added conversation-count and SQLite verification receipts.
- Added a loopback-only progress dashboard with token-protected controls.
- Added selective personal- and workspace-skill export with per-item rollback
  backups and username-independent user-skill discovery.
- Corrected APFS detection to use macOS `diskutil` plist metadata.
- Published the static project website, privacy policy, purchase terms, and
  refund policy for the planned Founding Edition. Checkout remained closed.
