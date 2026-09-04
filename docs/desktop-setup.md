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

## Browser-first setup

Open Codex Migrate on the **old Mac**, then choose **Open browser setup**.
The helper serves setup and the real migration dashboard on a private loopback
address. Enter the destination, choose local workspace folders, and review the
scope. Existing SSH configuration is used unless you enter a custom key path.
This is not a hosted upload: workspace data stays on the Macs.

Destination changes start disabled. Enabling them only makes the dashboard's
transfer controls available; you still inspect and start explicitly. Backup and
finalization guards are unchanged. The helper refuses a normal close while
inspection, a transfer, a paused process, or installation is active. Use **Stop
safely**, or wait for installation and verification to finish, before closing.

Browser-created migrations save the latest mode, destination, selected roots,
and skill categories under
`~/.local/state/codex-migrate-browser`. Reopen the helper with the same scope to
reuse that migration's state. Change permission, key selections, and account
credentials are not saved. The private control token is kept in browser
session storage so refreshing the same tab works; it is not sent to our site.

Do not switch an ongoing native/CLI migration into browser setup: their older
state directories are separate and are not imported by this flow. Resume using
the original controls. Similarly, restarting with a different scope does not
adopt existing destination staging. Preserve it and review recovery instructions.

Choose **Custom skills only** to repair personal skills, workspace skills, or
both without copying conversations, configuration, or entire repositories.
Workspace folders are searched only when workspace skills are selected. Review
the individual destination skills in the dashboard before staging. Finalize
requires both Codex apps closed and backs up and verifies those skills only;
unrelated destination skills and files remain unchanged.

Skills-only browser migrations use separate owned staging from full migrations
and support the same Pause, Stop safely, and Resume controls. Reopen with the
same mode, categories, destination, and folders to resume. The CLI `export`
command remains a one-pass alternative; its staging is not imported here.
Native picker permission behavior and the full browser recovery journey still
require clean-Mac validation before release.

## Alternative native setup

Open Codex Migrate on the **old Mac**. Enter `new-user@new-mac.local` and the new
Mac's `/Users/new-user` home directory. Optionally select an existing SSH key.
Choose the workspace folders to transfer. “Suggest common folders” checks
Git, Projects, and Developer under your home; it is not an exhaustive scan.

The last launched destination, folder selection, and skills choices are saved
in an owner-only local file under `~/Library/Application Support/Codex Migrate`.
They are restored when you reopen the app; **changes are always disabled**.
Review the restored scope before continuing. SSH key selections, credentials,
and dashboard tokens are not saved. Reselect a custom SSH key if needed.
“Restore last launched setup” also restores these values after editing the form.
Only the most recent setup is saved; this is not a multiple-migration library.

Folders are copied with their Git metadata and unfinished work. Credentials
stored inside a selected workspace are also copied. Review the scope carefully.

Click **Inspect both Macs**. Resolve any permission, space, identity, or connection
error before enabling changes. macOS may request access to selected folders;
grant only the access needed for your migration. Full Disk Access is not enabled
automatically by this app.

Enable changes only after reviewing the plan. Open the migration dashboard,
then choose Start transfer. It uses a free local port and opens in your browser.
The URL includes a private control token—do not share it. Keep the native app
open while the dashboard is in use. These alternative controls use the native
setup window and the same browser-based progress dashboard.

## Interrupted transfers

During inspection or a skills export, use **Stop operation** in the setup
window. Inspection and staging can stop; any staged files are retained. Once
skills backup/replacement starts, a stop request waits for that transaction and
verification (or rollback) to finish. Keep both Macs connected and wait for the
reported outcome. Force Quit and power loss cannot provide this guarantee.

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

Setup, recovery, and security guides are bundled with the app. Use the **Read
… offline** buttons even when the network is unavailable. Online links remain
available for current documentation and issue reporting.

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
