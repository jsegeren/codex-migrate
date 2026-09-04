# Git operational verification: engineering checkpoint

Status: the read-only probe is now connected to full-migration finalization and
the dashboard's separate Git check/retry. Installation evidence and Git evidence
remain distinct. This is local fixture evidence, not a signed or clean second-Mac
release certification. There is no separate public Git-check CLI command.

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

## Integrated lifecycle

The source plan is rediscovered before its Git probe; newly missing dependencies
or unsafe metadata block installation. The owner-only baseline includes the
ordered locations, read scopes, both homes, migration ID, per-attempt nonce,
source report and a fingerprint of the prepared content evidence. The baseline
is durably saved before the installation RPC; the installation receipt binds its
fingerprint. Status/API/preflight JSON and diagnostic reports omit that private
comparison material. No destination Git probe is sent when the saved
baseline/receipt binding is invalid; a retry may first check home paths over SSH.

After saving and syncing installation evidence, the engine checks home paths
and then Git. The path-to-Git handoff publishes its checking state under the same
lock so shutdown cannot miss both operations. Each retry rechecks current home
paths. Destination probes take the existing migration lock read-only/shared and
reject pending transactions; they do not create a missing lock file or permit a
concurrent migration writer. They cannot stop unrelated writing apps, so the
comparison remains point-in-time rather than atomic.

The dashboard offers Check Git and Stop Git check without enabling mutations.
Checking, verified, needs-review, unavailable and cancelled states are separate
from installation. Restart converts an interrupted check to needs-attention,
not resumable copying. Source issues and changed destination fingerprints are
separate counts; neither is automatically described as lost data. Older
installations without baseline evidence cannot acquire an original baseline
after the fact. Skills-only completion remains independent.

Read grants currently cover selected workspace roots and managed Codex worktrees,
not arbitrary other retained Codex directories. Such Git dependencies can be
copied by the content contract but still require operational review. There is
no silent read-scope expansion into authentication storage. Git checks have
bounded input/output and timeouts; the UI reports the phase, not invented
per-repository percentages for a batch that has not returned.

## Remaining release acceptance

1. Exercise actual packaged source/destination probes on a clean second Mac,
   including unavailable Git, unsupported flags/sandbox, external metadata,
   partial clones, unborn/merged/conflicted/sparse and submodule layouts,
   destination changes, disconnects, cancellation and restart reconciliation.
2. Resolve the hosted macOS CI primitive failures from run 33878246468 rather
   than assuming this development Mac's toolchain is representative. Runtime
   metadata is collected without configuration contents or credentials.
3. Complete native/VoiceOver acceptance and validate representative Codex chats.

The broader release gates in [release-readiness.md](release-readiness.md) remain
open. Shipping this internal primitive does not close them.
