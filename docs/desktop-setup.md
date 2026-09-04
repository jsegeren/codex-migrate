# Mac edition setup and recovery

The Mac edition is under development. No paid downloads or pre-orders are
available yet. Local unsigned builds are engineering artifacts, not releases.

## Before starting

- Keep an independent backup of irreplaceable data.
- Install and sign in to Codex on the destination first.
- On the destination, enable System Settings → General → Sharing → Remote
  Login for the intended user. Remote Management is not required.
- Use the exact destination username and home directory; they need not match
  the old Mac. Run `whoami` and `echo "$HOME"` on the new Mac to check.
- Configure SSH key authentication from the source, then connect manually
  once and verify the destination's host fingerprint through a trusted channel.
  The application cannot use an interactive password prompt. It never disables
  host verification or copies private SSH keys to the new Mac.
- The destination home must use APFS. Make enough room for staging and rollback.
- Backups are mandatory and verified before replacement. Insufficient space
  blocks installation, including skills-only exports. Free destination space
  and retry; there is no override or external-backup picker in this release.
  The dashboard shows space requirements, backup paths, and recovery guidance.

## Native setup

Open Codex Migrate on the **old Mac**. Enter `new-user@new-mac.local` and the new
Mac's `/Users/new-user` home directory. Optionally select an existing SSH key.
Choose the workspace folders to transfer. “Suggest common folders” checks
Git, Projects, and Developer under your home; it is not an exhaustive scan.

Folders are copied with their Git metadata and unfinished work. Credentials
stored inside a selected workspace are also copied. Review the scope carefully.

Click **Inspect both Macs**. Resolve any permission, space, identity, or connection
error before enabling changes. macOS may request access to selected folders;
grant only the access needed for your migration. Full Disk Access is not enabled
automatically by this app.

Enable changes only after reviewing the plan. Open the migration dashboard,
then choose Start transfer. It uses a free local port and opens in your browser.
The URL includes a private control token—do not share it. Keep the native app
open while the dashboard is in use. This edition uses a native setup window and
the existing browser-based progress dashboard, not an all-native progress view.

## Interrupted transfers

Use Stop safely in the dashboard before closing it. Paused transfers must be
stopped safely or resumed; the native app refuses to quit while its engine is
open. Rerun with the same destination and selected roots to reuse staging.
Do not change scope mid-migration. After a crash or reboot, staged data is retained.
Never remove the old Mac's data just because the progress bar reached 100%.

Finalization requires both Codex apps closed. It makes a destination backup,
installs, and verifies. Do not shut down either Mac during this phase. If it fails,
review the backup path and verification output before resuming. See
[recovery](recovery.md) for the existing engine's recovery contract.

## Skills only

Select personal and/or workspace skills, then choose Plan skill export. After
reviewing the plan, enable changes and choose Apply skill export. That action
requires an additional confirmation and backs up matching destination skills.
Restart Codex if updated skills do not immediately appear.

## Support

Support is best-effort. We aim to provide an initial response within a few
business days, depending on availability, complexity, and the information
provided. Requests are handled case by case. No response time, fix, successful
recovery, or resolution deadline is guaranteed. This does not limit the refund
policy or rights that cannot legally be waived.

Use GitHub issues for non-sensitive technical reports. Include macOS version,
app version, transfer phase, and a redacted error. Never post conversations,
repository contents, authentication material, control tokens, or payment data.
The private purchase-support contact must be configured before checkout opens.

## Build and release (maintainers)

Build with Python 3.9+ and Xcode Command Line Tools on each supported architecture:

```sh
python3 -m venv .venv
.venv/bin/pip install -r desktop/requirements-build.txt
.venv/bin/python desktop/build.py
```

The bundle includes the Python runtime and migration engine. Customers should
not need Python, Git, or Xcode just to launch it. Git is still needed for normal
development work after migration. Build output lives in a unique `build/desktop-*`
directory; local builds are explicitly marked unsigned and must not be sold.
Each app includes its source revision and build mode in `build-info.json`, plus
offline setup, recovery, and security documents. The ZIP has a SHA-256 checksum
and a matching build receipt beside it. Release builds require a clean committed
source tree so a distributed artifact can be traced to reviewed source.

Release requires an existing Developer ID Application identity and an existing
notarytool Keychain profile. Never put signing credentials in Git or command output.

```sh
.venv/bin/python desktop/build.py --release \
  --identity 'Developer ID Application: Your Name (TEAMID)' \
  --notary-profile your-existing-keychain-profile
```

The script stops if signing, notarization, stapling, or Gatekeeper assessment
fails. There is no unsigned fallback. A successful build is **not** by itself
release approval. Before charging customers, record evidence for:

1. Quarantined download opens under default Gatekeeper on a separate clean Mac.
2. No developer-installed Python or Xcode is needed to launch.
3. First-run permissions and SSH setup work with a different username.
4. Full transfer and skills-only export pass fixture-based cross-Mac tests.
5. Pause/resume, network loss, restart, finalization failure, and rollback pass.
6. Native window and dashboard controls pass visual and accessibility review.
7. Paid checkout delivers the exact signed artifact, including after browser closure.
8. Private support contact and refund handling are tested.

Initial hardware build: Apple Silicon. Intel support requires its own build and
validation before it is advertised. Automatic route benchmarking, broader
component selection, and automatic update installation remain unfinished; do
not advertise these as delivered by the current desktop shell.
