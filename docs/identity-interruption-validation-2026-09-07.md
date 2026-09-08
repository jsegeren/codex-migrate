# Installer interruption: destination identity preservation

## Reproduced defect and correction

A disposable local APFS test killed the actual generated installer shell with
SIGKILL immediately after it moved the staged `.codex` directory into place.
The previous ordering copied destination authentication and installation identity
after that move. The interruption left an existing `.codex` without those files.
Explicit recovery correctly preserves an intentional logout when current identity
is absent, but therefore could not distinguish this installer-created gap.
The new regression failed because destination authentication was missing after
restoration. No real account credentials or personal workspace were involved.

The installer now prepares both identity files from the verified destination
backup in its owned staging directory, compares both copies, and only then
starts the replacement transaction. The directory move exposes data and
destination identity together. Source authentication is never copied. Recovery's
intentional-logout behavior is unchanged.

## Verification

- Actual installer SIGKILL after the Codex move: pending state blocks new
  writes; production recovery checks and restores the original destination;
  destination identity survives; displaced incoming data is retained; source
  and verified backup remain unchanged.
- Actual installer SIGKILL after the workspace move: the same restoration
  checks pass, including retention of the partially installed workspace.
- Failed identity copy and corrupted identity preparation both stop before
  replacement, leave originals intact, and succeed through normal retry.
- A partial initial journal-write test now follows the app's real staging
  cleanup before retry. It verifies temporary identity files are removed while
  the earlier partial journal and backup remain preserved.
- All 31 transaction and transaction-write-failure tests pass on Python 3.12
  and system Python 3.9. All 13 builder tests pass after the build-number bump.
- The complete Python suite passes: 727 tests, 715 passed and 12 skipped.
  Mock notarization messages emitted by builder tests are not Apple submissions.

The fault tests execute local generated shell and production recovery against
synthetic fixtures; only transport and closed-Codex process snapshots are local
fixtures. They do not prove physical network/power-loss behavior or native
two-Mac acceptance. Screen Sharing still reports the receiving test Mac locked.
Native accessibility, TCC and remaining physical-device checks remain open.

Build number 7 identifies the next candidate containing this correction.
This source checkpoint does not change the public paid download (build 5),
approve the candidate, or claim the overarching release goal is complete.

## Signed build 7 candidate

Clean, pushed source: `67a92bb5d8383b542a3962be7868a87f927a871b`.
Apple accepted submission `990bb452-7072-41a4-9d5e-c743b62368de`.
The completed builder exited successfully at approximately 19:52 Pacific.

- Archive: `Codex-Migrate-0.1.0-build7-arm64.zip`, 8,307,584 bytes.
- SHA-256: `f244a02c956d2a460d1002caec17d214c78379ba8b09e9b0840b367ab5986fb1`.
- Artifact, app and receipts preserved in
  `/Users/Shared/CodexMigrate-Authentic-20260906/candidate-build7`.
- Independent preserved-copy checksum, strict/deep signature, staple validation
  and Gatekeeper checks passed (Notarized Developer ID).
- Exact packaged executable: nine desktop tests, eight passed and one
  case-sensitive-filesystem skip; both unprivileged filesystem-denial tests pass.
  These denial checks are not native TCC acceptance.

The task-owned sibling build worktree is retired after checking it is clean,
its source is pushed, its builder is terminal, and no process holds it as cwd.
The Shared candidate remains available. No catalog entry or public download was
changed; main-branch integration and candidate delivery promotion remain next.
