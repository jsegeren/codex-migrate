# Changelog

## Unreleased

## 0.1.0 paid beta build 13 — 2026-09-18

- Make daily automatic backup the explicit recommended default during the first
  Vault backup, while keeping a clear manual-only choice.
- Shorten the homepage around three customer jobs: encrypted backup, local
  conversation search/export, and guarded Mac-to-Mac migration.
- Add a real-product Vault demo and explain why the guarded workflow is safer
  than manually copying local Codex files.

## 0.1.0 paid beta build 12 — 2026-09-18

- Open a verified encrypted Vault snapshot in private temporary staging,
  search it, and add one missing conversation without overwriting or merging
  unrelated local Codex history.
- Lead the public homepage with the loss-prevention promise: do not lose local
  Codex work when changing or upgrading a Mac.
- Add the canonical maintainer handoff and reconcile current paid-beta state
  across support, launch and operations documentation.
- Preserve a reproducible 1200×630 white social-card source and output.

## 0.1.0 paid beta build 11 — 2026-09-12

- Add automatic preflight speed testing across trusted Wi-Fi and private wired
  addresses reported by the verified destination Mac, select the fastest route,
  show the measured connection in the dashboard, and re-evaluate it on resume
  and independent recovery checks.
- Fix scoped IPv6 handling by retaining brackets for rsync destination syntax
  while passing the unbracketed address expected by OpenSSH.
- Add a guarded `--resume-notarization` release-builder path that continues the
  exact saved Apple submission after interruption without rebuilding,
  re-signing, or submitting twice.
- Clarified common SSH failures in the app: an untrusted or changed host key
  now says that authentication—and therefore the user's password—was never
  attempted; key-authentication, name-resolution, Remote Login, and network
  failures have separate next actions.
- Publish a signed, Apple-notarized Apple-silicon beta for $49 with
  entitlement-bound private delivery, best-effort support and a 30-day refund
  policy.
- Preserve destination authentication and installation identity; add staged,
  verified, resumable migration and explicit interrupted-installation recovery.
- Simplify the browser-first migration interface and use Joshua Segeren's public
  name consistently.

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
