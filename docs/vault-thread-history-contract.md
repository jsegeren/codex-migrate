# Vault thread history contract

This is the acceptance contract for the next Codex Migrate + Vault release.
The customer promise is to find, read, and export conversation content that
Vault has captured, even when Codex no longer displays it. Resuming a recovered
conversation inside Codex is best-effort. The promise never applies before a
first verified snapshot or to turns written since the latest verified capture.

## Identity and versions

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
  result, but do not automatically connect it to a renamed or moved file.
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
- The random master key is stored in this Mac's `ThisDeviceOnly` Keychain,
  not in a plist or in the encrypted Vault. The user keeps the `CV1-` recovery
  key outside Vault. Losing both the Keychain item and recovery key makes the
  snapshots unreadable. Reinstalling the app on the same account normally
  leaves Keychain intact; a new account or Mac requires recovery-key import.
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
  shrinks or is rewritten. Detect conspicuous loss of records or assistant
  turns and surface the last intact version. Risk is carried forward in the
  encrypted manifest on later captures; a cryptographically valid capture of
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

No PreCompact protection is installed or advertised in the customer build.
The release guarantee remains the last successfully verified scheduled
snapshot, with at-risk detection on a later shrink. The upstream durable
record must not be destructively rewritten as a substitute for compaction.

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
