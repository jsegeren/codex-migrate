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

Start the dashboard again with the same target, target home, workspace roots,
and state directory. Choose Resume. Rsync compares the existing staging tree
and continues instead of beginning from an empty destination.

## Finalization fails

Finalization installs under an automatic rollback trap. If a post-backup step
fails, Codex Migrate attempts to restore the destination Codex directory and
every selected destination workspace to their pre-install versions. The local
state records `pending_backup` before any replacement begins.

Do not delete remaining staging or the timestamped backup. Keep Codex closed on
the new Mac, inspect the reported backup and restored destination, resolve the
named failure, and choose Resume to rebuild any staging paths consumed by the
failed install. Do not assume rollback succeeded if the Mac lost power or its
disk failed during rollback.

## Dashboard or Mac shuts down

Normal dashboard shutdown terminates its active SSH and rsync process groups.
On the next launch, a persisted `running` state is reconciled to `interrupted`
and Resume reuses staged data. If shutdown happened during installation, the
state becomes `failed`, retains `pending_backup`, and requires backup review
before Resume.

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

## Different usernames

If an older conversation still references `/Users/old-user`, create the
dashboard-provided compatibility link on the new Mac. The command requires an
administrator password and should be reviewed before execution.
