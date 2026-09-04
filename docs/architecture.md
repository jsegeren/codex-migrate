# Architecture

Codex Migrate is a dependency-free Python 3.9 application around the macOS
`ssh`, `rsync`, `sqlite3`, system Perl, and APFS-aware file-copy tools.

## Components

- `config.py` validates targets and confines workspace roots to the source home.
- `inventory.py` records content-free counts, sizes, and repository totals.
- `git_inventory.py` discovers Git locations and their required storage from
  metadata and links, without executing Git or reading object contents. Missing
  selected storage blocks full preflight before SSH; it never expands scope.
- `exclusions.py` shares root-anchored Codex runtime exclusions between rsync
  and Git dependency coverage. Managed workspace descendants are not filtered
  by runtime folder names.
- `transport.py` owns strict SSH arguments, route reporting, and resumable
  rsync processes.
- `migration.py` implements the staging/finalization state machine.
- `conversations.py` freezes active/archived transcript hashes and relative paths
  into a private verification script, reused against staging and installed data
  under the existing rollback transaction. It never parses or logs chat text.
- `state.py` writes atomic owner-only progress and control state.
- `workspaces.py` computes streaming SHA-256 tree snapshots with one system-Perl
  process per root, without a destination Python dependency or per-file shell
  processes. Versioned, length-framed nodes include byte-sorted names, file
  contents, regular-file/directory modes, empty directories, and link text.
  The same private source snapshots check staged and installed workspace roots,
  including Codex-managed worktrees. Absent managed storage is checked as absent,
  not as an empty directory. Digests are not saved in dashboard state or logs.
  Its separately versioned retained-Codex mode compiles the canonical transfer
  exclusions into byte-exact filters and omits real managed-worktree directories
  only because the complete-workspace pass checks them separately. It ignores
  only the Codex root's mode, which installation explicitly restricts to 700.
  Source identity filenames are validated before transfer and hashing; their
  contents are not read. Prepared source context carries both frozen snapshots.
- `dashboard.py` exposes a token-protected loopback interface.
- `setup.py` adds browser-first configuration and a fixed-script native folder
  picker. It attaches the existing dashboard and engine without a second
  migration implementation. Its owner-only registry saves destination and
  selected roots, not change permission or key selection. Host/origin and token
  checks protect setup APIs; requests and normal shutdown are serialized.
- `components.py` performs small, independently selectable repair exports with
  per-item destination backups.
- `component_migration.py` adapts those skill transactions to the existing
  migration state machine for browser inspection, staging, pause/stop/resume,
  explicit finalization, and crash reconciliation. It does not copy `.codex`
  or whole workspace roots. Its deterministic staging namespace and saved
  scope are separate from full migrations.
- `cli.py` provides inventory, inspect, and dashboard entry points.

`launch` starts guided local setup on a free port. The `/migration` view uses
the same engine and state transitions as `serve`. Browser-created records use
a stable key over normalized destination and sorted selected roots; the
browser does not import older CLI/native state. Restarting cannot silently
claim another migration's destination staging.

Skills-only keys also include the mode and sorted component categories.
Full-mode keys are unchanged, preserving existing browser resumes. The
destination replacement set is frozen at successful staging; changes require
restaging and a fresh finalization confirmation. Both full and selective
personal-skill transactions verify materialized regular-file bytes and the
directory tree before and after replacement, with automatic rollback on a
post-backup failure.

Dashboard inspection runs on the engine's worker thread. Local inventory
walks and disk-usage subprocesses check cancellation; stopping inspection
cancels its active remote command. Status remains available while it runs.

## State transitions

```text
idle
  → ready
  → running/staging
  ↔ paused
  → ready_to_finalize
  → running/final_delta
  → running/verifying_sources
  → running/installing
  → complete/verified
```

Any running transfer can enter `cancelled` while retaining staging. Rerunning
the transfer reuses staged files through rsync's normal delta behavior.
Source workspace verification is also stoppable; cancellation reaps its active
hash process and leaves staging available. A new Finalize recomputes snapshots.
The subsequent protected transaction verifies staging before backups, installs,
and checks the installed copy against those same snapshots under the rollback
trap. A completion receipt requires the workspace verification marker and exact
root count. This is content preservation, not Git operational acceptance.
Retained Codex state requires its own success marker. Its installed byte/tree
comparison runs before SQLite quick checks, which may change database sidecars.
Transcript checks remain separate to reject linked transcript storage; this
currently means an additional read of transcript data in the retained-state pass.

## Publication boundary

This repository contains generalized source code and synthetic tests only. It
must never contain a real migration's logs, state databases, known-host files,
SSH keys, conversation indexes, screenshots with private titles, or hard-coded
home directories.
