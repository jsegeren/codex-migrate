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
- Download and keep selected cloud files locally before starting. Inspection
  rejects macOS files/folders marked as cloud-only instead of downloading them.
  It cannot detect every provider's placeholders or prevent later eviction;
  real cloud-provider acceptance remains pending.
- A custom database-storage setting in user or selected project configuration
  requires review before full migration. Keep the setting and its data intact;
  don't remove it just to get past inspection. Skills-only repair is separate.
  Settings in retained destination parent folders are checked too.
  Known system config/default files are screened, not copied. For a managed
  work Mac, ask your administrator to confirm policy and tools on the new Mac;
  this tool does not migrate or certify device-management policy.
  Visible Codex managed-preference keys stop full migration for administrator
  and support review. A failed or timed-out check also stops. There is no
  override; do not remove policy to bypass it.
- Custom agent `config_file` references also need scope review before full
  migration, including references inside selected folders. The tool flags the
  reference without following or copying its target. Keep both intact and
  contact support; removing the reference to bypass inspection is not supported.
- If repositories are discovered, Apple Command Line Tools/Xcode and the
  guarded Git runtime must pass preflight on both Macs before staging. This
  early check does not inspect repository contents or prove Git integrity.
  A missing/unsupported toolchain blocks transfer with a review message; do not
  change ownership or weaken checks to bypass it. Skills-only repairs and
  full migrations without discovered repositories do not require this check.
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

Finalization requires Codex app and CLI/background-engine sessions closed in
the source and destination migration accounts. Unrelated macOS accounts can
remain logged in and working. The helper must run without `sudo` as the owner
of the selected home; identity or process-inspection errors block installation.
For background acceptance tests while everyday Codex sessions remain open,
use disposable accounts on **both** Macs. A temporary folder under the everyday
account is not process isolation. Opening restored chats still requires access
to the test account's graphical session; no logout of the everyday user is needed.

The tool makes a destination backup, installs, and verifies. Do not shut down
either Mac during this protected phase. If replacement is interrupted or its
outcome is uncertain, keep destination Codex closed and use **Check recovery**
before attempting another migration. See [recovery](recovery.md).

After installation, home-path and Git checks are separate from copying. Resolve
the **Home-path compatibility** panel first. Then use **Git verification → Check
Git** to compare discovered repositories with the saved source baseline.
**Stop Git check** is safe during its home-path precheck or Git probe. Check-only
retry does not recopy, restore or fetch anything, even if changes are disabled.
Do not start another transfer to resolve a failed post-install check.

If the source baseline cannot be captured before replacement, finalization
stops and keeps staging. Fix that issue, choose **Resume** to refresh staging,
then **Finalize**. For an older
installation with no original baseline, a retry cannot reconstruct it from
today's files: keep backups and contact support. A report of changed Git state
may reflect work you have already resumed. A passing point-in-time Git check
does not prove every chat, integration, hook or development command works;
validate representative work before retiring the old Mac.

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
not need Python, Git, or Xcode just to launch it. The guarded Git verification
step for discovered repositories requires a supported root-owned Apple-toolchain
Git executable on both Macs. Build output lives in a unique `build/desktop-*`
directory; local builds are explicitly marked unsigned and must not be sold.
Each app includes its source revision and build mode in `build-info.json`, plus
offline setup, recovery, and security documents. The ZIP has a SHA-256 checksum
and a matching build receipt beside it. Its filename includes the app version,
build number and architecture, for example
`Codex-Migrate-0.1.0-build1-arm64.zip`; engineering ZIPs additionally include
`LOCAL-UNSIGNED`. Update the app's version/build in `desktop/Info.plist` for each
release and keep the engine/package version in sync. The builder rejects an
engine/app version mismatch. Release builds require a clean committed source
tree and recheck its revision before submitting to Apple, so a distributed
artifact can be traced to reviewed source. Do not edit source during a build.
The final ZIP name appears in the output folder only after archiving, hashing
and writing its completion metadata succeed. A failed packaging step must not
be distributed as a partial download.

Release requires an existing Developer ID Application identity and an existing
notarytool Keychain profile. Never put signing credentials in Git or command output.

```sh
.venv/bin/python desktop/build.py --release \
  --identity 'Developer ID Application: Your Name (TEAMID)' \
  --notary-profile your-existing-keychain-profile
```

The script stops if signing, notarization, stapling, or Gatekeeper assessment
fails. There is no unsigned fallback. It saves Apple's submission ID in
`notary-submission.json` beside the app before waiting for processing. Only an
explicit `Accepted` result for that same ID permits stapling and release ZIP
creation. The completed outer build receipt includes that notarization result;
the already-signed receipt inside the app records pre-notarization build facts.

If processing is interrupted, do not immediately rebuild or submit another copy.
Use the saved ID with the existing Keychain profile to inspect the original job:

```sh
xcrun notarytool info SAVED-SUBMISSION-ID --keychain-profile your-existing-keychain-profile
xcrun notarytool wait SAVED-SUBMISSION-ID --keychain-profile your-existing-keychain-profile
```

A pending or accepted job is not a finished release archive. The builder does
not yet resume packaging automatically: retain the existing app and submission
receipt for maintainer review and completion of stapling, validation, Gatekeeper
assessment and checksums. If submission failed before an ID was saved, inspect
`notarytool history` using the same profile before retrying. Never publish the
pre-stapling app or mistake an engineering ZIP for an approved download.

A successful build is **not** by itself
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
