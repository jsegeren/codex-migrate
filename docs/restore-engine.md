# Internal restoration engine acceptance boundary

This is engineering documentation, not a customer restore command. The engine
in `src/codex_migrate/restore.py` is not exposed through the CLI, native app, or
dashboard. The public `recovery` command remains read-only. Do not recommend
calling this internal API against an active workspace.

## Transaction contract

Restoration requires explicit apply authority and a previously inspected
format-2 transaction: its ID, destination backup, and exact original paths must
still match. The destination's existing kernel lock is acquired exclusively;
normal staging/install entry points retain their pending-record block. The
backup must still match its frozen checksums. Legacy or malformed evidence
does not become trusted by retrying.

The engine creates `recovery-<transaction-id>` inside the verified backup:

- `plan.json` freezes the transaction and current entry presence/digests.
- `prepared/<index>` holds cloned restoration candidates, not current work.
- `ready.json` binds the plan and candidate digests before originals can move.
- `current/<index>` preserves displaced current entries. Indexes follow the
  original transaction scope; neither these entries nor the backup are deleted.
- `complete.json` is synced after final verification, before the original
  pending journal can be cleared.

The records are owner-only and destination-local. They contain paths and
digests, not file contents; hashes and credential contents are not returned to
the caller or diagnostic reports. The source Mac is not modified or inspected
by this restoration operation.

Current destination identity files replace the generated candidate's older
identity files. If the current Codex directory exists but an identity file is
absent, that absence is preserved: restoration must not undo a logout/reset.
If the whole current directory is absent, its verified backup supplies the
prior destination identity. Identity links, ambiguous capitalization and
unsupported evidence with no previous Codex root block restoration.

## Interruption and conflicts

Before preparing candidates, space is checked conservatively for the backup
copy size plus 2 GiB; the reserve is checked again before replacement. APFS
cloning is required; a clone failure never falls back to another copy method.
Unknown or unowned recovery directories are not adopted. Interrupted generated
copies or partial metadata writes are retained under `incomplete`, with at most
100 quarantine slots; exhaustion stops for support rather than deleting files.

On every attempt, the engine revalidates the plan, frozen backup, prepared
entries, preserved entries and active originals. Existing durable records are
re-synced before mutation; mere visibility after an interrupted publication is
not treated as proof they reached storage. File/directory fsync and a macOS
device-flush barrier remain required.

Moves use Darwin `renameatx_np` with `RENAME_EXCL` through system Perl's syscall
interface. The SDK constants are recorded in `transaction.py`; there is no
replacing-rename fallback. A destination that appears after existence checks
therefore causes failure rather than an overwrite. The same primitive publishes
new transaction records. Unsupported systems fail closed.

The Codex-process guard runs before preparation, after preparation, and directly
before each move. It is not an operating-system prohibition against later app
launches, renamed executables or manual writers. Keep all writing apps closed.
Unexpected new/changed work stops recovery; the engine does not merge it or
silently discard it. Resolving that conflict still requires explicit review.

## What the local tests do not establish

The fixtures use disposable files on this development Mac and real APFS
copies/renames, including deliberate process termination. They do not use real
credentials or perform a migration over SSH. They do not prove drive power-loss
behavior, clean second-Mac operation, Intel support, restored Codex usability,
or preservation of metadata beyond the existing tree-digest contract.

The next customer-facing slice must provide reviewed scope confirmation,
protected-phase status, support-safe error reporting, and restart reconciliation.
In particular, a dropped response after journal cleanup must not trigger another
restore or report “finished” solely because the pending journal is absent.
The preserved-current mapping and completion receipt need a read-only verified
reconciliation path before exposing the action. Restoring a previous destination
is not completion of the desired source-to-destination migration.
