# Multi-Mac continuity: proposed next product wave

Status: **parked research, not the current Codex Migrate roadmap or a shipped
feature.** The current product priority is to finish excellent backup, search,
recovery, and one-time Mac migration, then find customers. DevOS owns the
long-term machine-independent thread and manager layer; building it again
inside Vault would create a competing control plane. The gates below describe
what a narrowly scoped Codex bridge would need if demand later justifies it.
Do not describe Codex Migrate as a sync product.

## Customer outcome

Two Macs can contribute to the **same project at the same time** without losing
Codex conversation context or overwriting each other's work. Each machine can
find and read the other's recent threads; independently running agents use
separate Git worktrees and explicit task ownership. A thread may move between
machines safely, but two Codex processes must never write the same thread at
once. This is more than a scheduled copy of `~/.codex` and less than a promise
that Codex itself supports concurrent writers to one session.

Three distinct jobs must remain visible in the product:

1. **Protect and find:** Vault's verified, versioned, encrypted snapshots and
   read-only search. A verified backup is the recovery authority.
2. **See and continue:** low-latency replication of thread versions between
   Macs, a combined read-only view, and a guarded, explicit transfer of thread
   ownership before resuming it on the other machine.
3. **Work concurrently:** separate threads and worktrees for separate tasks in
   one project, with task/path ownership and a shared activity view. Git, not
   transcript copying, carries code changes. No automatic merge of dirty files.

The existing migration workflow remains the way to move a complete supported
working environment to a replacement Mac. It does not become a background
two-way file mirror.

## Evidence and competing approach

As of September 25, 2026, [`d-jiao/codex-sync`](https://github.com/d-jiao/codex-sync)
offers encrypted push/pull of
selected `~/.codex` files to customer-owned storage, with an optional daily
launchd pull-then-push. That is useful for **sequential** use of two Macs. Its
documented limits include conflict sidecars if one thread changes on both
machines, an app-closed desktop refresh before pulled threads appear, and no
sync of project organization, automations, worktrees, or the underlying repo.
It does not claim simultaneous writes to one thread or coordinated project
execution. This is a product comparison, not an allegation about its author.

## Source-of-truth and safety rules

- Keep Vault snapshots immutable and independently restorable. Replication
  cannot rewrite or prune the last good backup. Sync failure must not make
  local Vault history unreadable.
- Give every physical installation a stable device ID and each captured thread
  version a validated provider thread ID, source device, content digest, and
  capture sequence. Path and title are discovery metadata, not identity. A
  Codex rewrite is a new version, not an assumed append. Conflicting IDs or
  divergent versions remain separate and need review.
- Never replicate `auth.json`, `installation_id`, secrets, live SQLite files,
  runtime locks, or unchecked process state. Do not write into Codex while it
  is running. A remote thread is available immediately in Vault's read-only
  viewer; visibility or resumption in Codex itself requires separate proof.
- For a movable thread, one device is the writer. Handoff requires its Codex
  writers to close, a verified final capture, acknowledgement by the receiver,
  and a new ownership epoch before receiver-side import. If either side cannot
  prove this sequence, remain read-only and retain both versions. A timeout or
  disconnected Mac is not evidence that its writer stopped.
- Concurrent agents on one project get separate worktrees and branches. The
  managed launcher records task, repository, worktree, branch, device, owner,
  and claimed paths. Overlapping claims stop managed launches or request an
  explicit replan. This does not claim control over unmanaged Codex processes
  or arbitrary manual edits outside the launcher.
- Transport is authenticated and encrypted. The first physical-device proof
  can reuse the existing pinned-host-key SSH path on one LAN; the protocol must
  identify devices and versions independently of SSH so a later customer-owned
  relay or cloud transport does not change the data model. Do not assume a
  cloud-sync folder has finished uploading.
- Key custody follows Vault's recovery-key model. A second-device import and
  decrypt test is mandatory. No silent key escrow or new subscription is part
  of the first wave.

## Conditional bridge sequence and acceptance gates

### Gate 0 — finish the current Vault release

Complete the existing Vault/updater signing, installation, purchase, and
two-Mac acceptance work separately. Find and support customers for its actual
backup, search, recovery, and migration jobs. Do not hold this release for
speculative sync architecture. Capture baseline version, Mac configuration,
and data-format receipts for both devices.

### Gate 1 — safe two-Mac visibility (first buildable slice)

Add a local pairing flow over authenticated SSH, per-device change detection,
and encrypted replication of immutable thread **versions** into each Vault.
Start with an explicit Sync now command and then a bounded background interval
while both Macs are reachable; show last successful exchange and lag. Preserve
offline versions and reconcile when connected. The shared Vault view searches
both devices, labels source and freshness, and exports content without writing
to Codex. No repository files, SQLite, or live Codex import move in this gate.

Acceptance: on two physical Macs, add, rename, archive, rewrite/compact, and
delete disposable threads on either side; prove the other Vault can find the
last intact version, identical bytes do not duplicate rows, a disconnect does
not erase either side, and reconnect converges without clobber. Include a
recovery-key round trip using a different login or Mac. Measure propagation
latency and report it honestly; do not call the interval real-time.

### Gate 2 — simultaneous work on one project

Add a managed project registration and launcher. It creates/uses one Git
worktree and branch per task/device, records bounded task/path ownership, and
shows both machines' activity in one view. Code moves through normal Git
commits and reviewed integration, not rsync of dirty worktrees. Both agents
may run at once on disjoint tasks. A disconnected machine retains its own work
but may not silently acquire a conflicting managed claim.

Acceptance: two physical Macs run different agents on the same repository at
the same time, each sees the other's conversation updates in Vault, disjoint
changes integrate cleanly, overlapping claims are stopped, and a network
interruption neither loses work nor grants duplicate ownership. Test an agent
crash and stale claim recovery without assuming a PID or elapsed time proves
the other machine is idle.

### Gate 3 — guarded thread handoff into Codex

Only after Gate 1 is reliable, allow the user to stop a thread on Mac A and
resume that *same* thread on Mac B. Reuse Vault's verified selected-thread
restore and rollback, but add source quiescence and an explicit ownership
epoch. Prove the destination Codex build can index and resume the thread;
never edit its live database to manufacture visibility. If the source cannot
be contacted or the destination already has a divergent version, refuse
automatic continuation and keep both readable in Vault.

Acceptance: actual desktop/CLI round trips in both directions, changed home
paths, different Codex versions, app-open refusal, interrupted transfer,
divergent history, stale device, and rollback. This is a handoff capability,
not permission to run one Codex thread on both Macs concurrently.

### Gate 4 — wider network and productization

Decide whether demand justifies a customer-owned object-store relay or a
managed relay. Add onboarding, health/lag monitoring, retention and cost
controls, version compatibility, automatic update, and support diagnostics.
Security review and realistic failure testing precede any claim of continuous
or cross-network availability. Windows remains a separate compatibility and
testing project.

## Reuse in DevOS

Keep the reusable contract small: device identity, immutable versioned
artifacts, ownership epochs, task/workspace claims, acknowledgements, and
content-free health receipts. Codex-specific transcript parsing, desktop
refresh, Keychain details, and Git worktree launching remain adapters. DevOS
should own its canonical project and conversation state itself rather than
depending on Codex's private files or copying this app's UI. Reuse proven
protocol ideas and tests, not a speculative shared framework in Gate 1.

## Non-goals and honest claims

Do not promise that two active Codex processes can safely append to one
thread, that a copied transcript makes all repository state portable, that
background copies alone are backup, or that both Codex desktop sidebars update
live. Do not bundle cloud hosting, Windows, subscription billing, or automatic
dirty-worktree merges into the first wave. The customer-facing claim after
Gate 2 can be: **Work on the same project from two Macs at once, with separate
agent workspaces and shared, searchable conversation context.**

## Decision checkpoint

Do **not** begin Gate 1 automatically after the Vault release. First decide
whether customers need an independent Codex bridge that DevOS cannot provide;
otherwise keep this as research and implement the single thread/control plane
in DevOS. If a bridge is authorized, Gate 2 is the differentiating
simultaneous-work milestone and must pass before marketing this as a multi-Mac
solution. Gate 3 is optional convenience, not a substitute for Gate 2. Review
each gate's actual two-device evidence before expanding any claim.
