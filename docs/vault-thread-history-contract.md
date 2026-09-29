# Vault thread history contract

This is the acceptance contract for the next Codex Migrate + Vault release.
The customer promise is to find, read, and export conversation content that
Vault has captured, even when Codex no longer displays it. Resuming a recovered
conversation inside Codex is best-effort. The promise never applies before a
first verified snapshot or to turns written since the latest verified capture.

## Identity and versions

Local retained history must remain discoverable past the first 1,000 daily
snapshots. User-facing snapshot requests stay bounded, while title search and
per-thread timelines traverse all retained references without materializing
every thread version in a second list. A synthetic 1,001-reference regression
proves enumeration still works; it is not a large-history latency benchmark.

- A validated Codex `session_meta.payload.id` is the primary thread identity.
  Cross-check it against `session_index.jsonl` and the rollout filename when
  those sources are available. A title and a path are discovery attributes,
  never identity. A content digest identifies one byte version, never a thread:
  a normal append or a rewrite changes the digest.
- Identity is scoped to a Vault. Two independent Vaults are not synchronized
  or silently merged. Within one Vault, sequential captures of the same
  validated thread ID are dated versions. Identical digests do not create
  duplicate versions. A move between active and archived folders preserves
  identity and records the changed location.
- A disagreement between embedded, index, and filename IDs, or two divergent
  files with the same ID in one capture, is `needs_review`. Keep the files and
  versions separate; do not infer sameness from a title or a similar body.
  When no ID can be validated, retain a source-scoped path-based discovery
  result, but do not automatically connect it to a renamed or moved file—or
  treat changed bytes at the same path as one thread. Identical captured bytes
  may deduplicate; a different digest remains a separate result for review.
- Search current and archived transcript text, current and historical titles,
  and titles across snapshots. Older full text is searched in a selected
  snapshot. A v1 snapshot remains readable but cannot claim title aliases it
  did not capture.

## Recovery and key custody

- Opening a saved version is read-only. Export creates a user-selected file
  outside Codex. `Copy missing thread into Codex` is a separate confirmed
  write: verify the snapshot, require Codex and CLI writers closed, refuse if
  process or open-file inspection is uncertain, recheck immediately before
  writing, and refuse an existing or divergent ID anywhere in the active or
  archived trees. It never replaces or merges a live thread. The existing
  whole-history installer remains an advanced, separate operation.
- The random master key is stored in this Mac's login Keychain, not in a plist
  or in the encrypted Vault. The helper requests `ThisDeviceOnly`, but the
  current legacy-Keychain item has not been shown to enforce that accessibility
  class on macOS; do not advertise it as a proved guarantee. The user keeps
  the `CV1-` recovery key outside Vault. Losing both the Keychain item and
  recovery key makes snapshots unreadable. Reinstalling the app normally
  leaves Keychain intact; use recovery-key import on a new account or Mac
  instead of relying on Keychain migration.
- A recovery-key round-trip is not rereading the same Keychain item. Acceptance
  requires importing the key in a different Mac account or on another Mac and
  decrypting an existing verified snapshot. Do not escrow keys silently.

## Backup and protection state

- Daily encrypted snapshots are the recommended default. The UI distinguishes
  `unprotected`, `first snapshot verified; scheduled protection pending`,
  `scheduled backup healthy`, and `needs attention`. The full protection claim
  requires a verified first snapshot and a later successful scheduled run.
  Manual-only users see their latest verified snapshot but not an automatic
  protection claim.
- A local-only snapshot is not insurance against losing the Mac. A recognized
  cloud-sync folder does not prove that its provider completed off-device
  upload; report sync state as unverified until independently verified.
- New captures preserve older immutable versions, including when a rollout
  shrinks or is rewritten. Flag any drop in counted user or assistant turns,
  or a large byte-size shrink, for review; this is a conservative warning,
  not proof that Codex lost content. Surface the last intact version. Risk is
  carried forward in the encrypted manifest on later captures; a cryptographically valid capture of
  a truncated rollout must not turn an at-risk thread green.

## Pre-compaction proof gate

OpenAI documents `PreCompact` for automatic and manual compaction, with a
transcript path when available and a synchronous command-hook option. That is
not proof the affected desktop rollout rewrite invokes it in time. Test a
disposable thread on the installed desktop build and record hook invocation,
source-file identity and digest at entry, completed encrypted checkpoint, and
the subsequent rewrite ordering. Test manual and automatic compaction, a
missing path, disabled/untrusted hook, timeout, and storage failure. A hook
must never be advertised as protecting compaction until those tests pass.

If proved, implement a bounded single-thread checkpoint that verifies its
encrypted capture before allowing compaction. An unsuccessful checkpoint
returns an explicit stop where the hook supports it. Keep scheduled snapshots
and post-change anomaly detection because other destructive paths may bypass
the hook. Never claim zero-loss protection from periodic snapshots alone.

### September 22 probe

On the installed macOS `codex` 0.155.0-alpha.16, a disposable TUI task with a
reviewed/trusted synchronous `PreCompact` command emitted a receipt before a
manual `/compact` completed. The hook input contained `trigger: manual` and a
readable `transcript_path`; the probe recorded only the pre-compaction file
size and SHA-256, not conversation text. The file later grew as compaction
completed. This proves that the manual TUI path can pause for a hook on this
build. It does **not** prove that the destructive desktop rollout rewrite in
openai/codex#44363 uses that hook or leaves enough time to verify an encrypted
checkpoint. A disposable app-server `thread/compact/start` test with an
untrusted hook did not run it; that is a trust-configuration result, not proof
that app-server compaction bypasses hooks. An earlier one-turn automatic probe
used an unsupported threshold override, so its absent receipt was inconclusive.
The documented key is `model_auto_compact_token_limit`, not
`model_post_turn_compact_threshold_percent`. A corrected disposable TUI probe
set that key to 1,000 tokens with a 4,096-token test context. On the second
turn, the UI displayed `Compacting context` and the active trusted hook emitted
one receipt with `trigger: auto`, a readable `transcript_path`, and a 59,367-byte
pre-compaction transcript SHA-256. The tiny context could not hold the task's
normal instructions; the turn did not reach a useful completion and was
interrupted. This proves hook invocation before the automatic TUI path, not a
successful encrypted checkpoint or desktop coverage. In a third disposable TUI
task, the same hook returned `continue: false` for manual `/compact`; Codex
displayed `Hook stopped` with the test stop reason and did not complete that
compaction. This establishes manual CLI veto behavior on this build, not veto
behavior for automatic or desktop compaction. See the [official hook contract](https://learn.chatgpt.com/docs/hooks)
and [sample configuration](https://learn.chatgpt.com/docs/config-file/config-sample).
The current upstream source calls `run_pre_compact_hooks` from local Responses,
remote-v2, and token-budget compaction paths before their context mutation.
That improves confidence in current hook coverage but does not establish the
behavior of the older desktop build or the separate on-disk rewrite reported
in the issue.

An isolated, test-only `PreCompact` command prototype now encrypts a synthetic
transcript with AES-256-GCM, reopens and authenticates the ciphertext, compares
its recovered byte count and SHA-256, and publishes an owner-only checkpoint
and receipt before returning `continue: true`. Missing paths, symlinks, or
non-private storage return `continue: false` in direct fixture tests. It uses a
disposable test key outside Keychain and is **not** the Vault backup format or
an installed customer hook. Direct tests prove its checkpoint mechanics. In a
separate disposable TUI session on installed Codex 0.155.0-alpha.16, the
reviewed one-off hook produced an authenticated 78,899-byte checkpoint before
manual `/compact` reported completion. A separate verifier decrypted that
saved ciphertext and matched its byte count and SHA-256 to the receipt. Making
the disposable key unreadable and trying `/compact` again produced `Hook
stopped` with the probe's stop reason; no second checkpoint was published. The
temporary key, ciphertext, and receipt were then removed, and the test Codex
task was archived. This proves encrypted checkpoint publication and failure
veto for the tested manual CLI path. A second disposable TUI task configured
with an `auto`-only matcher and an artificially low compaction threshold reached
automatic compaction on its second turn. Its test key was unreadable, so the
hook returned `continue: false`; Codex displayed `Hook stopped` and
`Conversation interrupted`, and the checkpoint directory stayed empty. That
task was archived and its temporary storage removed. This proves an automatic
failure veto in the tested CLI build, not a successful encrypted automatic
checkpoint. The affected desktop rewrite ordering and Vault-format integration
remain separate gates.

A third disposable TUI task configured a manual `PreCompact` command that slept
for five seconds with a one-second hook timeout. `/compact` displayed `Hook
failed` and `hook timed out after 1s`, then reported `Context compacted` five
seconds later. The task was archived and its temporary storage removed. This
is a **fail-open timeout** in Codex CLI 0.155.0-alpha.16: an explicit
`continue: false` veto works on the tested manual and automatic paths, but a
hook timeout does not veto manual compaction. Even if the affected desktop
rewrite invokes the hook in time, this result prevents us from advertising a
hook as a reliable pre-rewrite protection boundary without an upstream
fail-closed timeout/error option or an independent write-ahead mechanism.

Four additional disposable app-server `thread/compact/start` runs on that same
installed binary completed compaction and archived their test threads without
invoking the configured command or publishing a checkpoint. `config/read`
showed one `PreCompact` group; `hooks/list` showed the command as enabled but
`trustStatus: modified`. The process was started with
`--dangerously-bypass-hook-trust`, yet no `hook/started` or `hook/completed`
notification was observed. Because the hook was not persistently trusted, this
does not isolate whether the app-server path bypassed `PreCompact`, the bypass
flag failed to apply to that path, or the trust state prevented execution.
It does establish that merely discovering and enabling the hook is not a safe
checkpoint guarantee. None of these tests used a live customer thread.

No PreCompact protection is installed or advertised in the customer build.
The release guarantee remains the last successfully verified scheduled
snapshot, with at-risk detection on a later shrink. The upstream durable
record must not be destructively rewritten as a substitute for compaction.

## Paginated-history coverage gate (September 28)

The installed Codex runtime now records paginated threads in
`state_5.sqlite` and projects thread items into `thread_history_1.sqlite`.
The [official app-server documentation](https://learn.chatgpt.com/docs/app-server)
describes paginated records as a distinct history mode. A read-only inspection
on an affected Mac found rollout files
still present, but also projection byte offsets beyond the current length of
more than one rollout. The corresponding database retains substantially more
user and agent message items than the current rollout contains. A private,
in-memory comparison found no exact text matches in those affected examples;
representation differences mean this is not by itself a complete semantic
diff. It is strong evidence of a JSONL-only coverage gap, not proof that every
projected item is an otherwise lost user-visible turn. No conversation text,
hashes, paths, or IDs were copied into this report.

Source-authority finding, September 28: in upstream Codex at
[`69f7140`](https://github.com/openai/codex/blob/69f7140559180269e2eb8f5be6e0c20eb37b0c85/codex-rs/app-server-protocol/src/protocol/thread_history_projection.rs),
the paginated rollout is explicitly described as canonical and
`ItemCompleted` lines are projected into the history item store. Its
[materializer](https://github.com/openai/codex/blob/69f7140559180269e2eb8f5be6e0c20eb37b0c85/codex-rs/thread-store/src/local/thread_history_materialization.rs)
reads the rollout from a persisted byte/ordinal cursor. Thus SQLite items
are a **derived view** in the current upstream design, not an independent
complete source of every durable turn. Yet the
[reported destructive rewrite](https://github.com/openai/codex/issues/44363)
occurred before migration, and
[projection failures](https://github.com/openai/codex/issues/38792) can leave
the database stale while rollout data survives. For recovery, neither source can be
assumed to subsume the other on an affected installation. Vault's capture
unit is both the JSONL bytes and the pinned SQLite item projection, with
source labels and no silent semantic merge. This interpretation is specific
to the cited upstream revision and observed installed schema; it does not
prove that every Codex version or damaged history is covered.

Vault v1/v2 currently encrypts the active and archived JSONL trees, not the
paginated thread-history database. A verified JSONL snapshot therefore cannot
by itself prove that all current Codex history is recoverable. Do not advertise
complete paginated-history protection or call the next release certified until
the following are proved on synthetic data and the current installed runtime:

Current-title coverage is a separate findability gate. On one installed Mac,
the legacy `session_index.jsonl` supplied aliases for 1,677 thread IDs; the
state database held 323 additional named threads with no legacy alias. The
draft now combines bounded `state_5.sqlite` `threads.title`/`threads.name`
metadata with the legacy title history, without reading message bodies from
that database. Codex can put an entire first prompt in `title`, so Vault keeps
only a 500-character searchable prefix. A metadata-only recheck found aliases
for all 2,000 state threads with a nonempty name or title on that Mac. This
proves title-index coverage there, not complete content recovery or support
for every Codex schema; unknown state schemas remain an explicit warning.

The draft interim guard treats the presence of `thread_history_1.sqlite` as
unverified source coverage, even if a rollout file appears complete. It marks
the new snapshot and scheduled health as needing attention without opening or
modifying Codex's database. This conservative warning is not a substitute for
capturing database-only durable content and proving off-device recovery.

The September 28 read-only search check on one Mac found five thread IDs
represented by 27 divergent rollout files. Previously, a full-text query that
reached any such database-backed thread stopped the entire search with an
ambiguous-lineage error. The draft now skips only that unresolved lineage,
returns other search results, and explicitly marks the page as partial. Direct
read/export of an ambiguous thread still refuses to guess which rollout is
authoritative. A no-hit search without the optional local index did not finish
within 20 seconds across roughly 58 GB of rollout files and 7 GB of SQLite
storage; useful full-text search performance at this scale remains an open
product acceptance concern. No private transcript content, paths, IDs, or
hashes were recorded in this receipt.

A separate draft search guard skips an unreadable JSONL header or record while
returning matches from healthy files and marking results incomplete. The
damaged file remains unchanged; read-only salvage inspection is a separate,
possibly incomplete path. A caller without a warnings channel still receives
an error. Synthetic malformed-header and malformed-record tests cover this
behavior; it is not evidence that every damaged real conversation is recoverable.

The optional local FTS cache now also indexes rendered text from supported
SQLite-backed items. Its database stamp includes the main file and write log;
if either changes during or after indexing, live search scans the database
directly rather than excluding an uncached thread. The cache remains opt-in,
owner-only, unencrypted, disposable, and subject to a free-space floor. Forked
threads consider indexed parent rollouts. Synthetic tests cover matching,
changes during indexing, and fallback; this is not yet a measured search-speed
receipt on a full customer-sized history.

The current [official app-server contract](https://learn.chatgpt.com/docs/app-server)
can list and summarize existing paginated threads, but its full-history read
and item-pagination operations fail closed for them. It is not a supported
complete export path today. Metadata-only inspection of the installed schema
found durable `thread_items.item_json` rows and a separate projection cursor;
no private item content was copied into this document. The capture adapter must
pin a consistent read view, version-check the schema, encrypt the needed item
records without creating a plaintext full-history staging copy, and fail closed
on an unknown schema. It must keep database-derived records distinguishable
from the JSONL rollout so divergent copies cannot be silently merged.

The draft reader now also follows Codex's bounded `history_base` rollout
lineage when searching, opening, or exporting database-derived items. Synthetic
parent/child and nested-fork tests cover an archived parent, a message present
only in the parent's database rows, a child/grandchild that inherit it, and
post-fork parent text that must not appear under the descendants. An encrypted
snapshot restored into a separate folder passes the same search/read case;
the export stamp includes ancestor files so a changed parent invalidates a
prepared download. This follows the upstream paginated reader's use of
rollout IDs and ordinal bounds, not Codex's incomplete global-search behavior.
The saved reader uses the authenticated snapshot catalog to distinguish an
ancestor with no database rows (no saved projection file, so skip that segment)
from a catalog-listed projection that has gone missing (fail closed). A
synthetic backup, restore, search, read, and browser Markdown-export test covers
the no-row-parent case; removal of the catalog-listed child projection is
rejected rather than silently omitted.
An opt-in proof using installed Codex CLI 0.158.0-alpha.2 created a real
paginated parent/fork in a disposable `CODEX_HOME` against a loopback-only
synthetic model, with all API credentials removed from its process environment.
Vault found the inherited message under the child through the installed
database schema. After Codex exited, the test replaced that marker only in
the disposable JSONL rollouts with equal-length bytes, preserving the actual
Codex-generated lineage offsets; the database retained the message and Vault
still found and opened it under the child. The same isolated source was then
encrypted into a temporary Vault, its test Keychain key deleted, its recovery
key re-imported, and its snapshot restored into a separate folder. Saved Vault
search and read found that database-only message under the child. The test
deletes its temporary key on exit. This proves the draft reader and recovery
path against the installed fork format and a controlled database-only case on
one macOS login. It does **not** prove Codex naturally performs that rewrite,
a real customer-history recovery, or recovery in a clean user account or
second Mac. Missing or ambiguous lineage still requires review, and the
paginated-history release hold remains open.

On September 28, the installed-Codex synthetic proof above passed again with
Codex CLI `0.158.0-alpha.2` after the title-index change; it now also verifies
Markdown export of the saved database-only inherited turn after recovery-key
import and restoration. This remains one-login, disposable-source evidence.
Separately, the
[Vault cross-runner CI proof](https://github.com/jsegeren/codex-migrate/actions/runs/36462786535)
at `f33f53c` created an encrypted synthetic snapshot on one macOS runner,
removed its test Keychain key, and imported the recovery key on a second
independent runner. That runner found, read, and exported a database-only turn
and found a title present only in the synthetic `state_5.sqlite` source. The
[hosted-branch cross-runner CI proof](https://github.com/jsegeren/codex-migrate/actions/runs/36462813960)
at `7c76562` also passed its separate Vault and hosted ciphertext-portability
jobs. These are two complementary proofs, not one installed-runtime,
clean-account end-to-end test: the CI source database is synthetic, and the
installed-Codex proof re-imported on the same login. Neither proves recovery
of a naturally damaged real history, installed buyer-app behavior on a clean
account, or a live hosted R2 disaster restore. Keep those release holds open.

A separate September 28 physical two-Mac attempt produced and verified a
disposable encrypted v3 snapshot on the older Mac, then transferred only its
synthetic ciphertext and test recovery key over SSH to the newer Mac. The
second Mac's non-interactive SSH session could not import the key through its
login Keychain, so the test stopped before read/export; it did not touch either
Mac's real Codex history. This is an environment/Keychain-context limit of that
attempt, not evidence that installed-app recovery succeeds or fails in a
signed-in GUI account. The disposable bundles were removed. The clean-account
installed-app recovery gate remains open.

A later read-only check confirmed that the newer Mac's console user was signed
in, but a disposable Keychain write from its SSH session returned macOS status
36 (interaction not allowed); `launchctl asuser` also did not grant that shell
the GUI Keychain context. No real Vault key was accessed. Repeating recovery
through SSH would not satisfy this gate: run the exact installed app in the
signed-in GUI account and verify its import, read, and export there.

- For a future installed version, revalidate upstream storage semantics and
  the observed schema. A byte/ordinal cursor or item-count comparison alone
  cannot prove semantic equivalence between rollout and projection, including
  after a rewrite; preserve both independently and surface unresolved gaps.
- Capture any database-only recoverable content with a consistent, encrypted
  snapshot or supported export, without reading or copying credentials or
  modifying Codex's live database. Preserve provenance; do not silently merge
  a database projection with a divergent rollout.
- Detect a partial capture and show `needs attention`, not a green scheduled
  protection state. A successful ciphertext checksum is not source coverage.
- On a clean account or second Mac, import the separately held recovery key,
  find, read, and export a known database-only turn from the captured version.
  Do not promise in-Codex resume or write the database back as part of this
  read/export guarantee.
- Measure the extra encrypted bytes and changed bytes across two scheduled
  runs before setting a hosted capacity tier or default retention policy.

The current public beta remains a transcript-tree backup with the disclosed
testing boundary. Its claim and Help copy need an independent product-truth
review against this finding before the next public release.

## OpenAI account-switch boundary (September 28)

Changing the OpenAI login on one Mac is not a Mac-to-Mac migration and is not
an established account-to-account thread transfer. OpenAI's
[authentication documentation](https://learn.chatgpt.com/docs/auth) says logout
clears current credentials; it does not say whether the desktop app will list
or resume account A's local threads after account B signs in. Its
[project documentation](https://learn.chatgpt.com/docs/projects) distinguishes
a saved chat transcript from the current working tree. Repositories,
worktrees, and unfinished code remain filesystem state; model access, cloud
work, plugins, and account permissions follow the active login. Vault must not
equate a readable local rollout with authorization or native resumability
under a different OpenAI account.

Read-only schema inspection of this Mac's installed `state_5.sqlite` found
`creator_user_id` and `creator_account_id` columns in `threads`, but all 2,031
thread rows had NULL in both. No identifiers or conversation content were
recorded. Those columns are therefore insufficient to attribute this history
to an account or to partition it safely. Older Codex schemas may not have
them at all. The migration and Vault paths must continue to exclude
`auth.json`, `installation_id`, and other credentials; no account identity is
to be inferred from a title, path, or thread ID.

The installed CLI reports `0.158.0-alpha.2`. Its matching upstream
[`thread_list_response_inner` and `list_threads_common` source](https://github.com/openai/codex/blob/10382da79a2a2d6e8ae221fa63077215389c1ad2/codex-rs/app-server/src/request_processors/thread_processor.rs)
lists local threads using project, source, model-provider, working-directory,
and similar filters but does not apply `creator_account_id` or
`creator_user_id` as a list filter. This is evidence about that CLI/app-server
revision, not a live two-account result. The desktop client may apply its own
filter, and listing alone cannot prove read or resume under another account.
Treat the possibility of old local threads being visible to a newly signed-in
account in the same macOS user as a privacy issue to test, not a benefit to
advertise.

There is real but contradictory field evidence. In an
[August 2026 CLI discussion](https://www.reddit.com/r/codex/comments/1voiin4/when_i_switch_account_in_codex_cli_using_codex/),
users report continuing local sessions after switching between paid accounts.
An [upstream Desktop issue](https://github.com/openai/codex/issues/20004)
reports sessions hidden after account/provider changes and warns that
`encrypted_content` can fail when sent through the wrong provider or account.
That issue's concrete reproduction is on Windows and includes custom
providers, so it is not proof of the same failure on Mac with two OpenAI
accounts. Together these reports justify testing both visibility and actual
continuation, including a synthetic thread with encrypted model state.
Separately, a [macOS Desktop report](https://github.com/openai/codex/issues/27601)
describes old local threads becoming hidden or slow after account switching
while the files remain, with a full app quit/reopen sometimes restoring them.
This is one user's report on an older build, not a result for this test. It
means the test must record both the immediate post-switch state and the state
after a clean Desktop restart; a restart must not be mistaken for account
portability or for recovery of missing source bytes.

Before claiming account portability, run a controlled test with two separately
authorized OpenAI accounts, a disposable macOS user/profile, and a harmless
synthetic Codex thread. Record the installed app and CLI versions and test:

1. Create, close, list, reopen, and continue the thread as account A. Include
   a normal completed model turn that produces encrypted model state when
   supported; record its presence, not its bytes. Record the local files and
   database rows without copying authentication material.
2. Sign out only in the disposable profile, sign in as account B, then check
   list visibility, read behavior, and continuation separately in the desktop
   app and CLI. Record the result before and after a normal full Desktop quit
   and reopen, without modifying thread metadata or changing workspace roots.
   Do not send account A's synthetic transcript as a new prompt under B merely
   to make a test pass; distinguish true native continuation from a new thread
   seeded with exported context.
3. Sign out B and return to A. Verify A's thread, repo, worktree, and local
   Vault snapshot are unchanged. Confirm account-specific cloud work and
   connected services have not been silently mixed.
4. Repeat with a clean OS user or second Mac only after the same-profile test
   is understood. Preserve separate accounts and credentials throughout.

Until that evidence exists, the defensible Vault guarantee is encrypted
preservation plus independent find, read, and export of captured local work.
An explicitly labelled new-thread handoff could later use an export with the
user's consent. Native continuation under another account is an open proof
gate, not a marketed capability. Cross-account access must never be enabled
by copying credentials or rewriting account identifiers.

## Acceptance and boundaries

Use synthetic content for destructive tests. On each physical Mac, produce a
separate receipt for first snapshot, scheduled snapshot, renamed-title lookup,
missing-thread lookup, v1 read, export, key recovery, and divergent-ID refusal.
Test a long thread and a simulated 851 MB to 7 MB rewrite. Do not alter live
customer transcripts for acceptance. No cross-Mac sync, hosted storage,
subscription, or DevOS transcript import is part of this release.

The [September 22 two-Mac acceptance receipt](vault-history-physical-acceptance-2026-09-22.md)
records the v2 engine proof and its remaining claim limits. It does not satisfy
the separate desktop `PreCompact` proof gate above.
