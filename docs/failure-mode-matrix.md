# Failure-mode and configuration acceptance matrix

This is an engineering acceptance checklist, not a claim that every row is
supported. Passing a copy test does not establish that a restored workspace is
usable. The paid release must either support a setup with evidence or detect
it early and give a safe, actionable explanation.

| Scenario | Current evidence / limitation | Required next acceptance |
| --- | --- | --- |
| Missing or corrupt local migration state | Reads now fail instead of returning fresh/idle state; existing token/lock evidence blocks silent reinitialization when the state file is missing. Focused tests cover malformed JSON, wrong object types, links, and disappearance. | Do not present this as complete power-loss recovery. Test destination reconciliation separately. |
| Wrong destination or source selected as destination | Every migration shell command and rsync receiver rejects the source Mac using an ephemeral salted platform-identity comparison, independent of username/hostname/IP. Unknown identity fails closed. Local real-shell/rsync fixtures and a genuine different-user two-Mac migration cover rejection and an allowed destination. | This prevents self-migration, not selection of another unintended trusted Mac. SSH trust and explicit destination review remain required. Supported macOS-version coverage is not exhaustive; duplicated VM identities are rejected. |
| Two migrations writing one destination | A shared destination-side kernel lock now covers staging mkdir/markers, rsync receivers, and full/skills backup-install-verify-rollback. Real local process tests exercise exclusion, retained descendant ownership after parent death, unsafe lock paths, shared installer boundaries, and real rsync protocol blocking. | Real cross-Mac disconnect acceptance remains open. No age/PID-based lock clearing; the persistent lock file must never be deleted. Older unguarded versions and manual writes are not coordinated. Power-loss reconciliation is separate. |
| Power lost during replacement or rollback | Destination recovery is synced before removal; pending or malformed records block staging/installation writes. Format-2 records freeze per-item backup checksums. Local fixtures cover SIGKILL, corrupted/missing backups, permission/link changes, Unicode paths, failed rollback, and flush/terminal-cleanup failures. On the real receiving test Mac, a protected replacement writer was deliberately killed after the durable journal; packaged recovery restored original data, preserved newer/out-of-scope data and the verified backup, cleared the journal and did not falsely report migration success. | Physical power removal and additional replacement boundaries remain open. Format-1 evidence requires support review, not automatic trust. Safe containment or a process exit alone is not completed recovery. |
| Destination already has new conversations or code | Full installation replaces selected roots after backup; it does not merge independent work. | Make replacement versus merge unmistakable in setup and final confirmation; test preservation in backup and recovery. |
| Different usernames with an existing old-home path | Read-only preflight and post-install checks validate ordinary home paths against local accounts. Disposable syscall fixtures verify direct aliases, conflict rejection, Unicode and late-entry races; an optional manual command creates only an absent exact path. A real different-user two-Mac migration passed the direct old-home alias, Git baseline and genuine conversation continuation checks. | Run representative project-specific development commands with the old Mac disconnected. Custom homes fail closed; one accepted fixture is not a universal workspace-usability guarantee. |
| Missing/unsupported Git or post-install Git differences | Full preflight checks the guarded Git runtime on both Macs only when repositories are discovered, before staging and without repository read grants. An unavailable source baseline stops finalization before replacement. Installed checks preserve the receipt and never restart copying; changed state, source issues, unavailable checks and cancellation remain distinct. Local fixtures cover linked worktrees, stash, uncommitted/untracked work and alternate storage with the old home offline. The real two-Mac migration required the saved Git baseline to verify before genuine conversation continuation. | Additional Git layouts and representative project toolchains remain open. Runtime startup is not repository integrity. Older installations without baselines require review; do not bypass ownership/sandbox guards. |
| Custom Codex storage/profiles | Full migration screens visible account `CODEX_HOME` and bounded user config/profile files for `sqlite_home`. Source project layers in selected descendants, managed worktrees and in-home ancestors are screened before inventory, copy/resume and freezing; explicit selected-root links are rejected while canonical parent aliases are resolved. Destination user config and retained ancestors above selected folders are screened at inspection and before replacement; linked/non-directory ancestor chains require review. Staged user config is rechecked against destination identity-file protections. Replaced project layers receive source screening and frozen tree checks. Fixed `/etc/codex/config.toml` and `managed_config.toml` are screened on both Macs without copying/changing system settings. | Custom-root migration is not supported. MDM preferences, cloud-managed requirements, arbitrary role references, other processes' environments and undisclosed roots still need effective-scope acceptance. System requirements/policy are not parsed or migrated. Project screening is conservative regardless of trust/profile activity, bounded to 1,024 layers per source/destination pass and does not traverse ordinary directory links. Lexical screening is not TOML validation or exhaustive discovery. |
| Managed Codex preferences | Full migration checks presence of the two documented keys for the executing source account and destination SSH account. Values are not converted, decoded, printed or changed. Present keys, errors and timeouts stop for review; the check repeats before source copying/freezing and destination replacement. In-process Foundation fixtures cover false/empty values and late changes without persistent preference writes. | No MDM enrollment, payload-policy comparison or cloud-policy certification. Other-home inventory does not inspect that owner's preferences. Sandbox/restricted-context visibility and actual managed-account/SSH behavior require acceptance. There is no bypass switch; administrators and support must review the setup. |
| Custom agent configuration references | A reproduced source fixture allowed inventory without reporting a referenced role file outside selection. Explicit `config_file` keys now stop full migration for scope review across the inspected user/profile, project and system layers; late checks preserve staging and original destination data. Reference values are not resolved, opened, copied or printed. | Conservative lexical detection also flags in-scope references and inactive/example-shaped keys outside strings/comments. This is unsupported-configuration detection, not a role-file migration/resolution feature or proof of effective storage relocation. Keep settings intact; no bypass. |
| External disks, shares, or repositories outside the home | Workspace selection is confined beneath source home; external Git dependencies block. | Clear supported-scope explanation. Do not advertise exhaustive whole-machine migration. |
| Cloud placeholders, unavailable files, and background writers | Source metadata checks reject macOS `SF_DATALESS` files/directories before selected content reads or directory enumeration, including configuration, Git pointers and materialized skill-link targets. Staging/resume and source freezing rescreen; excluded runtime data and preserved directory-link targets are not traversed by this guard. Synthetic metadata tests cover these boundaries and unchanged rejected destination data. Unreadable/changing/special files also block content verification. | Real cloud-provider/offline acceptance remains required. This is not a download/pin operation, atomic snapshot, remote-backup guard or universal detection of unflagged placeholders. Provider metadata operations can themselves stall, and files can be evicted after screening. Download and keep selected data locally first; close background writers. |
| Case sensitivity, filename normalization, unusual names | Config guards reject protected/control aliases and ambiguous workspace roots. Nested sibling names receive conservative Unicode decomposition/case-fold screening before copying and in the source tree freeze before replacement. Skills share the screening; unsupported UTF-8 names require review. No automatic renaming, and recovery preserves its existing byte-based digest contract. | Cross-filesystem/second-Mac acceptance remains required. This is conservative screening, not exact emulation of every APFS Unicode table; both case-sensitive endpoints may still require review. Excluded runtime subtrees and directory-link targets are not searched. Concurrent writers remain unsupported. |
| Codex version/storage changes | Transcript/state byte checks and SQLite checks exist; no broad version-compatibility guarantee. | Exercise representative versions and restored conversations; block unsupported layouts clearly. |
| Intel/Apple Silicon and native project dependencies | Artifacts identify architecture; development evidence is Apple Silicon. | Clean-machine packaging tests for each advertised architecture; explain when dependencies need rebuilding. |
| Permissions, managed accounts, denied access | Process-owner checks and failed read/copy checks fail closed. Packaged-engine POSIX permission-denial tests pass, and the receiving account completed the native folder picker open/cancel/select flow. | Exercise an actual macOS TCC denial and managed-account policy through the rendered app. Do not infer native permission behavior from `chmod` failures or silently request broader privilege. |
| Disconnect, sleep, changed route, helper restart | Real cross-Mac Pause/Stop/Resume retained 409,413,176 staged bytes. Killing only the active SSH child made the helper report failure, retained 677,848,813 staged bytes and resumed the same migration after helper restart without finalizing the destination. Simulated cancellation/restart/sleep cases also pass. | Physically remove and restore Wi-Fi and a working cable route with disposable accounts. Do not relabel process-kill evidence as physical-interface acceptance. |
| Disk fills during backup/install/rollback | Conservative budgeting, rechecks, verified backups, and failure fixtures exist. Five opt-in real APFS disk-image checks cover initial low space, space consumed after backup, pre-replacement ENOSPC, terminal completion under disk exhaustion, and forced installation failure with rollback under that pressure. The observed rollback was independently verified. See the bounded receipt below. | Actual production copy/journal/rollback ENOSPC and broader second-Mac/hardware recovery remain open. APFS retained room for metadata in the tested protected-phase cases; keep source and independent backup. |
| Connector credentials and external dependencies | Destination Codex identity is retained; source SSH keys are excluded. Other configuration can reference uncopied dependencies. | Explicit reauthentication/reinstallation guidance. Do not equate copied configuration with working integrations. |
| User gets stuck and needs support | Visible Help, email draft, reviewed local diagnostic report, and bounded event history are implemented. [September 6 browser acceptance](support-browser-acceptance-2026-09-06.md) verifies keyboard preparation/download, exact reviewed bytes, 320px/1280px layout, helper-error recovery and token rejection; 38 focused tests pass. | Repeat on the exact packaged release; native VoiceOver, actual email-client attachment and other setup/pairing surfaces remain separate. Never require private content just to request help. |

No known safety gap is waived because the product costs $49. Unimplemented
guards above remain engineering work, separate from Apple approval, commerce,
and clean cross-Mac acceptance gates in [release readiness](release-readiness.md).

## Real APFS disk-space acceptance — September 5

`tests/test_real_disk_space.py` creates a private, disposable 3-GiB APFS sparse
image, checks that it is a separate mounted device smaller than 4 GiB, and
requires at least 8 GiB of host free space. The test never fills a real home
volume. It is opt-in; ordinary unit discovery skips it.

Three checks passed using the production installer script and real `df`, `du`,
APFS clone-copy and verification commands:

1. A successful 1,280-MiB allocation reduces actual free space below the 2-GiB
   reserve. Installation stops before creating a backup or replacing data.
2. The same allocation occurs after the Codex backup has been copied and
   verified. The second production space check rejects replacement; the backup,
   original files and staged data remain.
3. A bounded 4-GiB write into that smaller image raises actual ENOSPC after the
   Codex backup check. The installer shell stops before replacement or a verified
   installation/backup receipt. This is an injected write in the installer shell,
   not a production copy, journal, rollback or hardware-failure test.

Each case verifies unchanged original destination files, retained staging, no
pending replacement transaction and unchanged synthetic source content. After
deleting only the exact artificial filler file, retry installs successfully with
a verified backup of the original workspace. The failed attempt's backup stays
intact where one was created. All three images were normally detached and their
disposable contents removed; cleanup never force-detaches or recursively removes
a still-mounted image. The existing 36 backup/transaction tests also passed.

Reproduce on macOS from the repository root:

```sh
CODEX_MIGRATE_REAL_DISK_TEST=yes PYTHONPATH=src:tests python3 -m unittest test_real_disk_space -v
```

The adapter is the existing local synthetic fixture, including its closed-Codex
process snapshot and dummy destination identity. No SSH, authentic Codex state,
personal workspace, GUI recovery or packaged two-Mac acceptance is claimed.

### Protected-phase extension and retry defect

Two additional disk-image cases exhaust the volume with a bounded write after
replacement and content verification, immediately before the production terminal
transaction call. The filler exceeds 2 GiB and real remaining free space is below
64 MiB. The production journal, clone-copy, rollback and verification operations
are unchanged:

- The large write fails, but APFS still permits the small completion writes.
  Installed synthetic conversation/workspace contents, preserved original backup,
  the `installed` terminal receipt and absence of a pending record independently
  confirm success. Requiring every large-write ENOSPC to fail installation would
  be an incorrect test expectation.
- An explicit installer exit at that same boundary forces rollback while the
  disk pressure remains. The observed result is a verified automatic rollback:
  original Codex/workspace files match, the terminal receipt says `restored`, and
  the pending record is removed. The test also requires explicit verified
  recovery after reclaiming space if a future filesystem run instead reports an
  unconfirmed rollback; that alternative was not exercised in this run.

The expanded run reproduced a separate real defect: two attempts within one
second chose the same timestamp-only backup folder. Retry hit the existing-path
guard and failed without a useful message. Full migration, CLI skills export and
browser skills repair now share a timestamp-plus-random-attempt name. Existing
path checks and destination locking remain in force; old backups are not reused,
removed or overwritten. Frozen-clock regressions cover full retry, consecutive
CLI repairs, and a failed browser repair followed by successful retry.

The combined run passed 119 tests across real disk-space, backup, transactions,
CLI/browser components, full skills, recovery inspection and restoration. All
disposable disk images were detached and removed after verification.

These cases do not prove ENOSPC during an actual production journal/clone write:
the tested APFS filesystem retained enough metadata capacity. Physical power
loss, a second receiving Mac and broader filesystem versions remain separate.
