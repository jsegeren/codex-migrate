# Architecture

Codex Migrate is a dependency-free Python 3.9 application around the macOS
`ssh`, `rsync`, `sqlite3`, and APFS-aware file-copy tools.

## Components

- `config.py` validates targets and confines workspace roots to the source home.
- `inventory.py` records content-free counts, sizes, and repository totals.
- `transport.py` owns strict SSH arguments, route reporting, and resumable
  rsync processes.
- `migration.py` implements the staging/finalization state machine.
- `state.py` writes atomic owner-only progress and control state.
- `dashboard.py` exposes a token-protected loopback interface.
- `setup.py` adds browser-first configuration and a fixed-script native folder
  picker. It attaches the existing dashboard and engine without a second
  migration implementation. Its owner-only registry saves destination and
  selected roots, not change permission or key selection. Host/origin and token
  checks protect setup APIs; requests and normal shutdown are serialized.
- `components.py` performs small, independently selectable repair exports with
  per-item destination backups.
- `cli.py` provides inventory, inspect, and dashboard entry points.

`launch` starts guided local setup on a free port. The `/migration` view uses
the same engine and state transitions as `serve`. Browser-created records use
a stable key over normalized destination and sorted selected roots; the
browser does not import older CLI/native state. Restarting cannot silently
claim another migration's destination staging.

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
  → running/installing
  → complete/verified
```

Any running transfer can enter `cancelled` while retaining staging. Rerunning
the transfer reuses staged files through rsync's normal delta behavior.

## Publication boundary

This repository contains generalized source code and synthetic tests only. It
must never contain a real migration's logs, state databases, known-host files,
SSH keys, conversation indexes, screenshots with private titles, or hard-coded
home directories.
