# Git operational verification: engineering checkpoint

Status: the internal read-only probe is implemented and fixture-tested. It is
**not yet connected to migration completion, the dashboard, or a public CLI
command**. Existing “files verified” evidence must not be represented as Git
readiness. This document records the remaining integration work, not a narrower
release definition.

## Why a separate probe is necessary

Byte preservation does not prove an installed linked worktree can find its
shared Git directory. Git status also is not inherently a harmless file reader:
it can refresh the index and execute configured filters. Git documents its
optional index refresh in [git-status](https://git-scm.com/docs/git-status).
Disposable tests reproduced an optional filter being blocked while status
still returned exit code zero and printed the configured command to stderr.
Neither exit code alone nor a raw error log is an acceptable verification result.

## Implemented primitive

`src/codex_migrate/git_probe.py` supplies one system-Perl runner for local use or
the existing strict SSH transport. It accepts explicit source/destination home,
read scopes and ordered repository locations from the reviewed dependency plan.
It returns an allowlisted, bounded report with opaque comparison fingerprints;
it does not return Git stdout/stderr, filenames, refs, commands or object IDs.
These fingerprints are internal comparison material, not diagnostic attachments
or a customer-facing receipt by themselves.

- The initial process has a minimal environment, no shell, and no stdin data.
  Serialization completes before spawning. Git also receives a fresh minimal
  environment, with no inherited configuration, tracing or loader overrides.
- System `xcrun` resolves Git; only a root-owned, non-writable executable in an
  installed Apple developer toolchain is accepted. The actual Git process runs
  inside a deny-default sandbox. Reads are confined to declared workspace/Git
  scopes and explicit trusted runtime resources. Reading the root directory
  entry itself is allowed; reading all its descendant data is not.
- Git cannot fork, access the network or write files except `/dev/null`.
  System/global config and attributes, optional locks, fsmonitor, pager, lazy
  fetching, automatic maintenance and helper-based acceleration are disabled.
- Protected SSH and Codex identity locations are screened using conservative
  case/Unicode and resolved-path comparisons. Known identity hard links are
  detected from metadata only, before Git runs. Protected storage cannot be
  admitted through a trusted-runtime read grant.
- Each subprocess has an output limit and a deadline, including after both
  pipes close. Cancellation terminates and reaps the local process group.
  No raw diagnostic output is published; stderr prevents a successful check.
- Repository identity, common directory and worktree location must resolve
  within the declared scopes. The probe fingerprints symbolic/detached HEAD,
  refs, staged index entries and porcelain status. Bare repositories omit
  working-tree checks. Submodule recursion is disabled; discovered submodule
  repositories require their own planned checks.
- `fsck --full --strict --no-dangling --no-progress --no-references` checks
  local object/connectivity state without permitting child helpers. Ref-backend,
  commit-graph and multi-pack-index helper verification is not included; refs
  are enumerated separately. The required options must actually work on both
  Macs; there is no unsafe fallback. See [git-fsck](https://git-scm.com/docs/git-fsck).

Promisor/partial-clone and custom `fsck.*` policies currently require review,
without fetching or changing settings. Shallow repositories are labelled as
shallow, not complete history. Git's promisor-aware fsck can accept promised
objects that are absent locally, so a passing fsck must never imply that all
remote history is available offline. See
[partial clones](https://git-scm.com/docs/partial-clone).

This is a point-in-time probe, not a sandbox certification for every macOS/Git
version or a guarantee that arbitrary future hooks, filters, Git LFS, signing,
pushes, remotes or development commands will work. Unborn repositories and
other stderr-producing layouts can still require review. Read-scope scanning
adds metadata I/O and the bounded batch size must be respected.

## Evidence already exercised

Disposable tests cover clean and staged/unstaged/untracked work, packed bare
repositories, detached HEAD, corruption, filtered files, external config and
worktree redirects, inherited environment injection, protected aliases and
identity hard links, unusual path spelling, strict report validation, timeout
after pipe EOF and process-group cancellation.

The linked-worktree copy fixture includes a local branch, stash and unfinished
work. It removes the original source home from its old path before probing the
copy. The missing compatibility alias produces `needs_review`; a fixture-only
alias then gives matching source/destination reports. Frozen tree checks prove
neither fixture changed. This is local disposable evidence, not a second-Mac,
real-account or packaged application acceptance test.

## Required integration and release acceptance

1. Freeze a source Git baseline while source writers are closed, tied to the
   exact ordered repository/dependency plan, home paths, migration ID and
   installation content evidence. Persist the baseline safely before install.
   Explain source-existing issues without labelling them migration damage.
2. Preserve the successful installation receipt before any Git check. Once
   home-path compatibility is verified, run the same probe against the mapped
   installed locations and compare with the frozen source baseline.
3. Add a separate `checking / verified / needs_review / cancelled / unavailable`
   state with read-only retry, bounded progress and clear next action. Neither
   a failed check nor a lost reply may trigger reinstall, rollback or Resume-copy.
   Reconcile restart state conservatively. Skills-only repair must remain separate.
4. Bind every accepted report to its expected scope; count/shape validation
   alone does not prove which repositories were checked. Keep comparison hashes
   and private paths out of shared diagnostics. A later user edit is “changed
   since baseline,” not automatically corruption or lost migration data.
5. Integrate a concise summary and expandable details using existing dashboard
   patterns. Review keyboard focus, announcements and narrow layouts independently.
   Update completion claims only when the corresponding evidence exists.
6. Exercise actual packaged source/destination probes on a clean second Mac,
   including unavailable Git, unsupported flags/sandbox, external metadata,
   partial clones, unborn/merged/conflicted/sparse and submodule layouts,
   destination changes, disconnects, cancellation and restart reconciliation.

The broader release gates in [release-readiness.md](release-readiness.md) remain
open. Shipping this internal primitive does not close them.
