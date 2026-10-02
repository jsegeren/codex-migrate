# October 1 packaged recovery acceptance

## Current-main rerun — October 1, 2026 (Pacific)

The same independent receiver drill passed again after integration and the
bounded-transcript-read safety fix, using a newly built package from clean
`main` at `e2913365a7ffdb75b04f488c2b3ebacd2094b4d4`. The branch-candidate
receipt below is historical; this rerun is the current packaged recovery proof.

- Version/build/architecture: `0.1.0` / `20` / `arm64`.
- Package built at `2026-10-02T00:36:14.737852Z`; Developer ID signed,
  Vault-profile provisioned, **not notarized** and not published.
- ZIP SHA-256:
  `d9c94b090ed705985fd584d70c6cb2cfe570801a185fe06157bc6c5c7ff259f4`.
- The self-contained driver's SHA-256 remains
  `c1e2ec686992057ab105c979d5388c45950782a57e92eaca2f18abfbdf6641a9`;
  its source is unchanged from the earlier receipt.
- A fresh synthetic snapshot and recovery key were generated with this exact
  packaged engine. The producer test key was removed before receiver import.
- The retained `codex-backup-clean-acceptance` guest reported macOS `26.6.2`
  (`25G83`), separate `admin` user, two CPUs and 6 GiB RAM. It still had no
  active developer directory or working system Python. Only this guest ran.
- The test-only share was read-only; audio and clipboard sharing were disabled.
  Both guest Ethernet interfaces were disabled before the drill, not during
  boot. No source repository or producer Keychain was transferred.
- Producer and receiver both exited zero. The receiver enforced all seven
  checks listed below, including wrong-key rejection, authenticated key import,
  exact-file/byte restore, attachment search, archived-thread read/Markdown
  export, reader shutdown and receiver test-key removal.
- The guest was stopped afterward; Tart reported `Running:false` at
  `2026-10-02T00:44:42Z`.
- Exact-main [CI run 36946227632](https://github.com/jsegeren/codex-migrate/actions/runs/36946227632)
  succeeded. Its path-gated portability jobs did not all rerun; this separately
  executed VM drill supplies the fresh packaged-recovery evidence.

This closes the freshness gap between the older branch package and integrated
`main`. It does **not** prove live R2 publication/recovery, unattended hosted
backup, notarized first-launch/updating, billing, buyer UI, or Codex resume.
No customer data, real schedule, public download or cloud resource was changed.

## Result and scope

The Developer ID signed hosted-branch candidate passed synthetic recovery on
an independent macOS VM after the vendor Command Line Tools and Homebrew Python
were moved aside; system Python failed and no active developer directory was
available. The source Mac removed the disposable key before transfer; the
receiver had to import the separately saved recovery key. This closes a
packaged-engine/native-Keychain recovery gap. It does **not** close notarized
download/first-launch, real R2 recovery, hosted scheduling, billing, customer UI,
or real Codex conversation-resume acceptance.

No personal transcripts, account credentials, real backup schedules or customer
data were used. No public app or hosted runtime was changed.

## Exact candidate

- Source: `b52ca326f21eaa232015561e0fbc858ec82b5cc5`, clean committed tree.
- Branch: `codex/hosted-vault-service`. It does not yet incorporate the newer
  app-branding commit `41ea1a8` on `main`; integration remains required. This
  package is not the final combined customer candidate.
- Version/build/architecture: `0.1.0` / `20` / `arm64`.
- Build: Developer ID signed and Vault-profile provisioned; **not notarized**.
- ZIP: `build/desktop-zkj_m890/Codex-Migrate-0.1.0-build20-arm64-LOCAL-UNSIGNED.zip`.
- ZIP SHA-256: `489e89ed58888fa9730d5462aa613236769bf8aefb4b350a3992d4cb09c3961e`.
- Strict deep signature verification passed. The conservative local-test ZIP
  filename does not imply that the app lacks a Developer ID signature.
- Self-contained portability driver SHA-256:
  `c1e2ec686992057ab105c979d5388c45950782a57e92eaca2f18abfbdf6641a9`.
  It runs the existing `tests/packaged_vault_portability.py` drill without
  requiring Python or repository imports on the receiver.

## Independent receiver environment

Tart guest `codex-backup-clean-acceptance`, cloned from
`ghcr.io/cirruslabs/macos-tahoe-base:latest` on October 1:

- Guest macOS `26.6.2`, build `25G83`, Apple Silicon, separate `admin` user.
- Two virtual CPUs and 6 GiB RAM; only one acceptance VM was booted.
- Audio and clipboard sharing disabled. The host share contained only the
  signed candidate, test driver and synthetic ciphertext/recovery bundle; it
  was mounted read-only at `/Volumes/My Shared Files/test`.
- Host-only startup initially refused because `softnet` was absent. No SUID
  helper, administrator networking change or passwordless sudo was installed
  on the host. The VM booted with standard virtual networking; both guest
  Ethernet interfaces were then disabled before the drill. This is not proof
  of host-enforced network isolation during boot.
- The vendor base image included Command Line Tools and Homebrew Python 3.14.
  Inside the disposable guest only, those installations were moved reversibly
  into named `/var/tmp/codex-backup-acceptance-disabled-*` folders. The guest
  reported no active developer directory, system Python invocation exited 1,
  and Homebrew Python executables were unavailable before the current-candidate
  drill. This is a modified vendor image, not a pristine Apple installer image.
- The guest received neither the source repository nor the producer Keychain.

## Observed checks

The producer and independent receiver commands both exited zero. The driver
enforces these checks; it never prints recovery keys or private command output:

1. Create active/archived synthetic history and a pasted-text attachment,
   generate/verify an encrypted snapshot, and remove the producer test key.
2. Refuse an already-present receiver key and prove the snapshot cannot be
   verified before importing the separately saved key.
3. Reject a wrong recovery key without occupying the receiver Keychain slot.
4. Import the correct key using authenticated-manifest verification, then
   verify the exact snapshot.
5. Restore into a separate disposable inspection home, compare the exact file
   set and bytes, and require the restore receipt.
6. Search for the restored attachment text, then read an archived conversation
   and export it as Markdown through the actual packaged loopback HTTP reader.
7. Confirm reader shutdown and remove the receiver test key.

The same guest initially passed against signed source `8359f19`; after building
the current source and generating a new bundle/key, it passed again against
`b52ca32`. The second result, not the older package, is this receipt's candidate.
The VM was stopped afterward; authoritative Tart state reported `Running:false`.
The retained guest is for the next acceptance step, not a live customer service.

## Related verification and remaining gates

- Exact source CI [run 36829557460](https://github.com/jsegeren/codex-migrate/actions/runs/36829557460): all nine jobs passed, including independent-host
  portability and hosted database checks. Those hosted jobs use disposable
  fixtures, not the live R2 sandbox.
- Full local Python suite: 1,371 tests, 33 skipped, zero failures.
- Current packaged Vault/interruption/updater-contention suite: 11 tests run,
  nine passed and two initially skipped. The separately opted-in real,
  disposable LaunchAgent test then passed, yielding ten distinct passed
  packaged checks. The optional previous-package upgrade test was not rerun
  in this current-candidate batch; do not count it as passed here.
- The LaunchAgent fixture preserves the account's real Codex home/schedule and
  refuses an existing backup-agent configuration. It proves disposable local
  scheduled capture, not real hosted background protection.

Next release gates: authenticated real-R2 publication/readback and replacement-
Mac recovery; successful hosted scheduled run/offline catch-up; approved,
verified pricing/billing/fulfillment; notarized exact final download/first-launch
and safe updater acceptance; customer-facing restore/protection UX acceptance.
No paid-customer count was refreshed by this technical drill.
