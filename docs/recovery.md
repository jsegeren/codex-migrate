# Recovery

## Required backup and space checks

Before staging, the full migration checks space for remaining incoming data,
the measured size of existing destination items to back up, and a 2–20 GiB
safety reserve. Selective skill exports use incoming file sizes plus existing
destination items and a 2 GiB reserve. The budget is deliberately conservative:
APFS clones normally use less space, but clone savings are not counted as free
capacity. Immediately before backups, space is measured again; after backups,
the safety reserve must still be available. Other apps can consume space after
a check, so copy errors also block replacement.

Every backup must pass a checksum comparison of regular file contents, tree
structure, and symbolic-link targets before any destination replacement begins.
No file contents, checksum values, or differing filenames are logged. A failed
copy or verification leaves the originals in place and keeps staging available.
There is no skip-backup switch. If space is insufficient, free space on the
destination and retry. External backup locations are not supported yet.

The owner-only backup directory contains `verification.json` only once every
backup has passed. It records original-to-backup paths and recovery guidance.
The dashboard shows the last space check and pending or completed backup path.
The selective export result includes the verified backup path as well.

Close all apps that write to selected files before finalizing. This is not an
atomic filesystem snapshot, and ACLs, extended attributes, and hard-link
topology are not independently verified. Same-disk clones protect against
replacement mistakes, **not disk failure**. Keep the old Mac and, for
irreplaceable work, an independent backup until you validate the new workspace.

## Interrupted staging

If inspection reports missing Git dependencies, no destination connection or
transfer has begun in that attempt. Expand the Git scope panel to see required
folders. Restart the helper, add those folders to the workspace selection, and
inspect again. Changing browser scope creates a different migration record;
existing staging is not automatically adopted or deleted. Review the changed
replacement scope carefully. A missing historical worktree warning means that
folder is already absent on the source, not that it was transferred.

Start the dashboard again with the same target, target home, workspace roots,
and state directory. Choose Resume. Rsync compares the existing staging tree
and continues instead of beginning from an empty destination.

## Finalization fails

Only one migration writer can use a destination home at a time. Full migrations
and skills repairs share the same destination-side lock for staging writes and
the complete backup/install/verify/rollback phase. If another operation holds
it, the attempted write stops with a message. Resume or stop the other transfer,
or let its finalization finish, before retrying. Read-only inspection is still
available; this is exclusion, not an automatic waiting queue.

The empty, owner-only `.codex-migrate-destination.lock` file stays in the
destination home after an operation. Its existence does not mean a transfer is
running: the operating system holds and releases the actual lock. Do not delete
the file, use a timestamp to declare it stale, or assume an SSH disconnect means
the remote operation stopped. A running child can retain the lock through a
disconnect. Unsafe lock paths or file permissions block writes; contact support
instead of removing them. The lock does not coordinate older tool versions
without this protection, other apps, or manual shell commands.

After a reboot the kernel lock is released, but that does not prove replacement
finished. Before the first removal, the tool now saves an owner-only
`.codex-migrate-transaction.json` in the destination home. It records the backup,
selected paths, whether each original existed, and frozen per-item backup
checksums. The new format-2 record checks backup bytes, names, regular-file and
directory permission bits, empty directories, and link text against the original
before replacement. Backup files/directories and
the record are synced, including a macOS device-flush barrier, before replacement
can begin. Sync failures block progress rather than falling back to a weaker
write. No source files or credential contents are stored in this record. The
checksums stay in owner-only destination recovery records, not the UI, logs,
or support report. The full destination backup check includes that Mac's retained
identity files; it never reads the old Mac's excluded identity files.

Before normal rollback removes any current destination data, all backup items
must still match those frozen checksums. Restored data must also match the frozen
checksums before rollback is called verified. A damaged, missing, unreadable, or
unexpected backup stops rollback and keeps the pending record; it is not copied
over the current files. Checks read the backed-up data again and can take time.
Copies preserve permission bits, but ACLs, extended attributes, ownership,
timestamps, and hard-link topology are not independently certified by the digest.
These records detect accidental changes, not malicious same-account rewriting
of both a backup and its record. Keep all writing apps closed.

Older format-1 pending records have no frozen backup checksums. They still block
new writes and require support review; upgrading does not silently trust or
upgrade their backups.

A pending record blocks new staging and installation writes, even from another
source Mac or a different migration mode. Missing, malformed, or linked recovery
data is never treated as proof of success. Do not remove the record to force
Resume. Keep destination Codex closed and contact support for inspection. A
guided post-crash restore/reconciliation action is still required before the paid
release; the current alpha contains the failure but does not automate that step.

Successful installation or verified normal rollback saves a
`transaction-receipt.json` in the backup folder before clearing the pending
record. A final cleanup error can occur after the pending file was removed;
the terminal receipt and installed/restored data have already been synced at
that point. An error is still reported, and the backup must be retained for
review. A terminal receipt does not replace checking current restored usability.
Actual drive power-loss and clean second-Mac acceptance remain unverified;
device-flush support is not protection against failed hardware.

Retained Codex state now has the same frozen before/after protection. Changed,
missing or extra retained configuration, organization, rules, automations or
database files block replacement or trigger rollback. A database can pass SQLite
integrity checks yet differ from the source; that is not accepted as a complete
copy. The byte comparison runs before SQLite checks can change sidecars.
Authentication and runtime exclusions still apply. Source identity filenames
using noncanonical capitalization require review before transfer.

Full migration also freezes checks for every selected workspace and
`~/.codex/worktrees` after its final copy. Staged file, Git object/ref, name,
permission, or link-text mismatches block replacement. Installed mismatches
trigger rollback using the same frozen expectations, not a refreshed source
snapshot. Source verification can be stopped safely; Resume retains staging,
but the next Finalize restarts verification. Unreadable or changing files and
special files such as sockets/pipes must be resolved, not silently excluded.
The destination checks and installation are a protected phase and may take
substantial time; keep both Macs connected until it finishes.

Full migration freezes active/archived transcript content checks after its final
copy. Corrupted or missing staged transcripts block destination replacement.
Post-install transcript verification uses that same snapshot; failure triggers
the normal rollback attempt. Resume refreshes the copy before a new Finalize
confirmation. These checks can take time for large conversation histories and
do not replace opening representative chats and repositories on the new Mac.

In browser **Custom skills only** mode, the same controls apply, but the
replacement and rollback scope is only the listed skill destinations. Codex
state and whole repositories are not copied or replaced. The saved categories
and dedicated staging folder must match when resuming. This browser flow does
not import one-pass CLI exports or native export staging. Skill backup mappings
are in the component backup's `verification.json`; numbered `items` entries map
to the exact original skill paths.

Full-migration finalization installs under an automatic rollback trap. If a post-backup step
fails, Codex Migrate attempts to restore the destination Codex directory and
every selected destination workspace and personal skill to their pre-install
versions. The local
state records `pending_backup` before any replacement begins. The rollback is
reported as verified only after each original matches its frozen backup checksum (or is absent
when it did not previously exist), and the restored data and recovery receipt
are synced. A failed check retains the pending record and blocks new writes.

Do not delete remaining staging or the timestamped backup. Keep Codex closed on
the new Mac, inspect the reported backup and restored destination, resolve the
named failure, and choose Resume to rebuild any staging paths consumed by the
failed install. Do not assume rollback succeeded if the Mac lost power or its
disk failed during rollback.

## Dashboard or Mac shuts down

The staged personal-skill selection is saved locally. If that selection changes,
or staging was created by an older version without this record, Finalize stops.
Choose Resume to refresh staging, review the listed skill scope, and confirm
Finalize again. No newly discovered skill is silently added to a previously
confirmed replacement scope.

The browser-first helper refuses normal shutdown while a migration is running
or paused. Choose Stop safely during inspection, copying, or source workspace
verification, wait for it to
settle, then quit. Installation must finish before normal shutdown. The
standalone CLI dashboard instead terminates its active SSH and rsync process
groups during shutdown. Neither behavior prevents an unexpected crash or power
loss.

On the next launch, a persisted `running` state is reconciled to `interrupted`
and Resume reuses staged data. If shutdown happened during installation, the
state becomes `failed`, retains `pending_backup`, and says rollback is unconfirmed.
The destination may still be running. Preflight checks for unfinished destination
recovery evidence before assuming its Codex directory is intact. A pending record
requires recovery review, not a blind Resume.

## Restore the destination backup

The completion receipt records the backup directory. Quit Codex on the new Mac
before restoring. Move the current `~/.codex` aside rather than deleting it,
then copy the backup's `.codex` directory back into place. Preserve evidence
until the restored application opens correctly.

Exact restore commands are intentionally not generated automatically in the
alpha: the backup path and current state should be inspected before any
replacement.

Selected workspace roots that already existed on the destination are backed up
under the receipt's `home-relative` directory. Restore them with the same care:
quit development tools, move the current workspace aside, and move or copy the
reviewed backup back to its original path. A workspace that did not exist on
the destination has no prior version to back up.

Full-migration personal-skill backups are under `personal-skills/<name>` inside
the recorded backup folder. Existing skill aliases are backed up as links,
without copying or modifying their targets. Unrelated destination skills are
not replaced. Use `verification.json` to identify the exact recovery mapping.

## Different usernames

If an older conversation still references `/Users/old-user`, create the
dashboard-provided compatibility link on the new Mac. The command requires an
administrator password and should be reviewed before execution.
