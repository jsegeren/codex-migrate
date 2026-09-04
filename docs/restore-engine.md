# Restoration engine acceptance boundary

This is engineering documentation, not a customer restore command. The engine
in `src/codex_migrate/restore.py` powers the browser's explicitly confirmed
Restore backup action. The public `recovery` CLI command remains read-only.
Follow the [recovery guide](recovery.md), not direct internal API calls.

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

## Guided action and reconnect reconciliation

The browser requires a checked backup, enabled changes, and confirmation bound
to the transaction ID and listed paths. Before sending the restore request,
the source persists and flushes that exact reference and inspection. Checkpoint
failure sends no restore request. Recovery progress does not display a transfer
percentage, and ordinary migration actions and normal shutdown are unavailable
during the protected restore operation.

A successful remote reply is followed by read-only reconciliation. A dropped
reply or source restart instead requires Check recovery; it never automatically
retries restoration. Reconciliation takes the existing shared destination lock,
opens only the selected transaction's evidence, rechecks frozen backups, validates
plan/ready/completion bindings, and compares both active restored entries and
separately preserved current entries. It reports actual presence separately from
expected presence. Unexpected preserved/prepared slots fail closed.

Missing, malformed, incomplete, changed, busy, or different-transaction evidence
does not mean success. Only complete matching evidence with no pending cleanup
resolves recovery. A matching incomplete transaction can offer a separately
confirmed Resume restoration. Ordinary migration entry points require a bound,
validated saved reconciliation proof; a missing attempt or a bare resolved flag
cannot bypass recovery. Changed files require review, not automatic replacement.

Restoring a previous destination is not completion of the desired migration.
The migration remains interrupted, its completion receipt is cleared, and the
next migration must stage and verify again. These local fixture checks do not
replace packaged cross-Mac acceptance or the remaining hardware/usability gates.
