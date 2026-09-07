# One-launch authentic conversation test handoff

Prepared September 6, 2026. This is an engineering harness, not customer UI.
Its latest live run passed both account sign-in checks and created three genuine
conversations, but stopped during staging setup. There is no authentic
migration acceptance receipt yet. Original personal workspaces are not selected.

September 6 late-evening candidate update: `isolated-candidate` now contains the
exact extracted, Developer ID signed and Apple-notarized version 0.1.0 build 2
archive from clean source `1ee2e410b13799941cecbaca5e8525cf35de02dc`. Signature,
staple, Gatekeeper, embedded-code and Shared access preflights pass. The prior
candidate is preserved at `isolated-candidate-build1-preserved`. No test runner
was active during replacement; the latest actual test result remains stopped
before migration. Both existing launcher paths remain valid. Notarization is
not a prerequisite for engine testing, but the accepted artifact is now ready
for that same account-local launch. See the [signing receipt](signing-candidate-2026-09-06.md).

## Founder steps

Latest live run after the signed-candidate update: runner 83988 confirmed both
accounts ready and three genuine conversations, staged data and reached the
installation phase. It then reported `failed` during `finalizing`, with
`migration_phase: installing`. The runner exited; packaged helper 84016 remains
running with its protected state. This is not an installation or rollback
success receipt. Do not rerun, reset or change either test account before
examining the actual error and recovery evidence.

`/Users/Shared/Show Codex Test Error.command`, launched inside the source test
account on the old Mac, now reads saved state and exports
`/Users/Shared/CodexMigrate-Authentic-Status-20260906/installation-diagnostic.json`.
No screenshot or copy/paste is needed. Future runner exceptions export this
automatically. The already-exited runner cannot execute new code retroactively,
so this current failure needs one owner-account export. No password is required.
The export checks ownership and path permissions, uses atomic mode-644 output,
and includes only fixed status, error-signature hints, backup-presence and
verification flags. Unknown errors are explicitly unclassified; hints are not
proof of root cause or rollback. Raw errors, paths, commands, tokens and workspace
contents are excluded. It makes no network call or migration/recovery action
and works without a live helper. All 56 harness tests pass on Python 3.9 and
3.12, including automatic failure export, redaction and unsafe-path rejection.
The optional `--open-dashboard` read-only viewer remains available for later
owner review, but it is no longer the required handoff. The signed app itself
has not changed. The original launch steps below are not an instruction to
retry this failed installation.

1. On the **old Mac**, switch to **Codex Migrate Source**. With Codex closed,
   open `/Users/Shared/CodexMigrate-Authentic-20260906/Start Authentic Migration Test.command`.
   No administrator password is required when running in that account.
2. If already signed into Codex, that sign-in is retained. Otherwise, when Codex
   opens, sign in normally with ChatGPT, then quit with Command-Q. The launcher
   window may close; the runner is detached.
3. On the **new Mac**, switch to **Codex Migrate Target**, open Codex, sign in
   normally with ChatGPT, then quit with Command-Q. Return to personal accounts
   and leave both Macs awake and connected.

Sign-ins completed before launching are supported. Quit Codex in both test
accounts before starting the launcher. It no longer moves aside `.codex` or
reopens an already authenticated source app. Existing synthetic fixture files
remain alongside the newly created genuine conversations; the test is not a
claim that every existing source conversation is authentic.

The runner waits up to three hours for sign-ins and closed Codex processes.
It then creates the fixture conversations, starts the current packaged migration
engine, inspects, stages, finalizes with verified destination backups, checks Git,
and attempts reopening/continuation through Codex's app-server on the new Mac.

## Guardrails and evidence

- Exact disposable account/home guards; root and personal accounts rejected.
- Existing source pairing is reused with its pinned destination host key and
  strict SSH. Private keys and control tokens remain in the source account.
- Preparation retains the marked disposable account's existing `.codex` in
  place. Credential files are never opened, moved or copied by preparation.
  A Codex-created 755 root is accepted; links and writable-by-others roots are
  rejected. Any previous preparation backup remains untouched.
- Existing pending recovery blocks preparation. The old source helper is stopped
  only with an installed, idle receipt; an unknown or active helper blocks it.
- A new standalone `Authentic-Migration-Test` Git project contains a committed
  baseline, a local branch, an uncommitted edit and an untracked file. Existing
  `Git` fixtures are not selected or modified by this run.
- Three small conversations are created using the installed Codex app-server:
  project, non-project/loose and archived. They contain invented test markers.
  No session JSONL or SQLite schema is fabricated. The ChatGPT subscription login
  is checked through `account/read`; API-key login is not accepted for this test.
- Partial conversation creation is held for review, never duplicated silently.
  The precisely identified legacy unsupported-model failure has a one-attempt,
  same-thread repair described below; other failures still stop.
  Continuation must produce a new assistant turn containing the original marker.
- No arbitrary command queue, remote listener, sudoers edit or password caching.
  The model fixture requests no tools, uses read-only permissions and rejects
  unexpected server-side approval requests. Provider/account details are not logged.
- Status alone is shared at
  `/Users/Shared/CodexMigrate-Authentic-Status-20260906/result.json`.
  It contains phases, booleans, counts and fixed diagnostics, never authentication
  material, raw subprocess output or personal conversation content.
- A protected migration is not killed when its observer times out. The helper
  and private state remain available. Rerunning during an active installation
  stops before opening Codex or changing test data; once inactive, the launcher
  can attach to the known helper without starting a parallel replacement.

The package is the clean `28d5b10` unsigned arm64 candidate recorded in
[the package receipt](packaged-beta-candidate-2026-09-06.md). Its copied app
passed `codesign --verify --deep --strict` again in the handoff directory.

`PYTHONPATH=tests .venv/bin/python -m unittest test_authentic_mac_handoff -q`
passes 36 deterministic tests, without a real account login or model call.
Launcher shell syntax is checked. The installed local Codex CLI is 0.153.4;
the protocol field names were checked against its generated schema.

The implementation follows the official [Codex app-server protocol](https://developers.openai.com/codex/app-server/).
Protocol-created conversations are real Codex conversations, but passing this
test will not by itself certify their presentation in the desktop sidebar.
After the automated test, separately open the three restored test conversations
in the new Mac's desktop app and verify their visible history and continuation.
That final rendered check remains explicit, as do the other open release gates.

## First launch follow-up

The Founder launched the harness after signing in. Its public result reported
`needs_review`, `migration_started: false`, and a generic subprocess failure.
The runner exited and the old source migration helper had stopped; no authentic
migration receipt exists. The original diagnostic does not establish the failed
remote operation's cause, and it must not be attributed to incorrect user input.

The harness now preserves the failed phase, distinguishes SSH failures from
remote program exits, and allows only known fixed remote diagnostics into the
public report. It withholds arbitrary stderr and remote error bodies. A target
Codex/migration app still open is now a bounded background wait, not an immediate
exit. Source Codex closure is also awaited before preparation. Other failures
remain explicit review stops; no protected migration is automatically reset.

The 18 deterministic checks pass on system Python 3.9.6. These changes have not
yet been exercised by a new account-local run. Updating the Shared program does
not restart an exited process in another user's account. No password caching,
privilege bypass, personal-account transfer or credential copying was introduced.

## Second launch: both sign-ins passed, first model turn failed

Runner PID 8999 reported `source_ready: true`, `target_ready: true`,
`failed_phase: creating_genuine_test_conversations`, `migration_started: false`,
and `Codex turn failed`. The runner exited before starting the migration helper.
The previous generic turn diagnostic discarded the failure category; it does
not establish a quota, network, permission, or model cause.

The diagnostic repair now maps the installed 0.153.4 protocol's allowlisted
`codexErrorInfo` categories and bounded integer HTTP status codes into fixed
messages. Provider messages, additional details, account records, and transcript
contents are never published. Unknown shapes remain a generic withheld error.
On restart, an incomplete fixture receipt is validated and its exact thread is
read through `thread/read`. Failed/interrupted turns produce a safe diagnostic;
other partial states still require review. This path never retries a model turn,
creates a replacement thread, or marks an incomplete fixture as complete.

All 26 harness tests pass on system Python 3.9 and the Python 3.12 virtualenv,
including redaction, malformed errors, partial-thread identity checks, and
non-retry behavior. `git diff --check` passes. These are deterministic tests,
not a successful live rerun. The Shared script update cannot restart the exited
owner-account process. A strict, noninteractive localhost SSH check failed with
connection refused; no authentication material or privilege settings were changed.

Next account-local launch is diagnostic only for the existing failed fixture.
It should not ask for sign-in again when both accounts remain authenticated.
Review its actual error category before choosing any retry or account action.

## Diagnostic rerun: launcher falsely reported failure to start

Runner PID 62197 did start and wrote a new report: both sign-ins passed,
`migration_started: false`, and `Codex turn failed: other` while inspecting the
partial fixture. It then exited. The parent's one-second startup check treated
any already-exited child as a failure to start, even when it had finished its
diagnostic. That message was incorrect. The launcher now reports that the child
has stopped and explicitly asks for report review, not another setup/launch.
An early zero exit is not called successful migration either.

The generic `other` category does not establish the original failure's cause.
Repeating this same diagnostic would not add useful evidence. The next debugging
step needs owner-local access to the exact test turn's error information through
Codex, without publishing raw provider output or changing account credentials.
There is no running background acceptance worker and no authentic migration
receipt. All 28 deterministic harness tests pass on Python 3.9 and 3.12; this
includes fast zero/nonzero/signal exits and a still-running child.

## Root cause found and fixed: unsupported implicit model

The single September 6 fixture rollout was readable through its existing file
permissions. A bounded inspection of only its terminal error—not a recursive
session search—identified HTTP 400 `invalid_request_error`: the implicit `gpt-5`
model is not supported with a ChatGPT account. The harness omitted an explicit
model, and Codex used that unsupported default. This was not evidence of failed
sign-in, incorrect passwords, quota exhaustion, or a migration failure.
No credentials, private harness receipts, or account permissions were accessed
or changed. The published error contains only the model rejection.

The harness now discovers the account's advertised default with `model/list`,
validates its default reasoning effort, and persists the selection in the
owner-only `model.json`. It pins the model for thread start/resume and the model
and effort for every turn. Target continuation requires the same model to be
available, rather than selecting a different default. Missing, ambiguous,
hidden, unsupported, or absent pinned models stop without a fallback. Start and
resume responses must confirm the requested model. Catalog selection follows
the official [model/list documentation](https://learn.chatgpt.com/docs/app-server#models)
and the locally generated 0.153.4 protocol schema.

Only the first incomplete, pre-pin project fixture with exactly one failed turn,
the exact observed unsupported-`gpt-5` error, and its exact invented user prompt
is eligible for repair. The harness records `model_repair_attempted` and the
chosen model before resuming that same thread. The rejected request receives
one new turn using the selected supported model; subsequent launches cannot
repeat that repair if it fails. Other errors, extra turns/items, changed content,
or already-pinned partial records remain review stops. Codex storage is never
edited directly and the original failed turn remains in history.

All 36 deterministic tests pass on Python 3.9 and Python 3.12, including catalog
pagination/ambiguity, pinning, exact repair eligibility, no duplicate thread,
repair failure persistence, and server rejection of the requested model pin.
The shared executable script is updated and byte-compared against the reviewed
source. This does not restart the exited source-account process: the corrected
live acceptance run remains pending an account-local launch. Unlike the previous
diagnostic-only update, this changes the identified cause and can proceed into
migration if model generation and all existing safety checks pass.

## Supported-model run: staging setup requires diagnosis

Runner 75071 created all three genuine conversations with the advertised
`gpt-6-astra` default. It started migration; the engine then reported `failed`
with phase `preflight_complete`, before the staging/copy phase was entered.
Packaged engine 75640 was left running with its private state. Do not reset it,
delete destination staging, or claim that authentic installation passed.

The stage-preparation code checks the destination staging owner marker before
copying. Earlier tests used the same default staging folder; an ownership
collision is a hypothesis, not a confirmed diagnosis. The current supervising
personal account cannot read the source test account's private migration state;
noninteractive sudo requires authentication and localhost SSH is unavailable.
No permissions, credentials, or account isolation were bypassed.

`Inspect Stopped Codex Test.command` runs `--diagnose` only in the source test
account. It reads the existing migration reference, reuses the pinned connection,
and checks fixed destination staging metadata. It exports only allowlisted
staging-owner comparisons, pending-recovery presence, and fixed error codes to
`/Users/Shared/CodexMigrate-Authentic-Status-20260906/staging-diagnostic.json`.
It does not open Codex, call a model, start/stop a helper, transfer, finalize,
delete, unlock, or alter either account's migration data. Control tokens and
owner-marker values are never exported. The original result remains unchanged.
This diagnostic still requires execution as the source test account; preparing
the script is not proof it ran. The deterministic harness suite passes 41 tests.

Apple membership was observed active through September 6, 2027 for
`joshua@segeren.com`, showing team `P9J3JK79KQ`. The Founder supplied
`WCCLSPWZ9Y`; signing-team selection is awaiting clarification. The local
Keychain reports no valid code-signing identities. No certificate was created,
notarization submitted, checkout opened, or paid release published.

## Follow-up: account verified and staging conflict confirmed

The Founder executed the read-only diagnostic. Its public receipt reports
`failed_before_copy: true`, `staging: different_owner`, and
`pending_recovery: false`. This confirms the conflict; it does not authorize
deleting or adopting another migration's staging.

The next harness uses `migration-isolated`, `runtime-isolated.json`, and
destination folder `Codex-Migrate-Authentic-Staging-20260906`. The CLI now
accepts `--staging-name`, preserving its default and existing path validation.
Keep this name and the state directory unchanged when resuming. A distinct
packaged app under the Shared `isolated-candidate` directory prevents replacing
the currently running binary. Existing conversations and model pin are reused.

Before starting it, the source-account launcher can gracefully stop only the
exact recorded legacy helper when its protected status still says failed
before copying, with no receipt, staged completion or pending backup. It checks
source/destination configuration, repeats the remote ownership/recovery probe,
and rechecks status and PID before SIGTERM. Active, unknown, changed or installed
operations stop the launcher without signalling. A timeout never escalates to
SIGKILL. Original private state, destination staging and backups remain intact.

Apple Support's activation email for case 102953437296 explicitly calls
`WCCLSPWZ9Y` the enrollment ID. The signed-in `joshua@segeren.com` portal shows
the active Individual membership with Team ID `P9J3JK79KQ`, renewing September
6, 2027. The earlier apparent mismatch was an identifier-type mistake, not
evidence Apple activated the old consumer account. A private local key and
verified public CSR were prepared outside the repository. Certificate creation,
Keychain installation and real notarization are not yet complete.

The clean local-test package is now prepared from pushed revision
`9ae70b5750bafe8f9869644de46d6a57a49cca09`, arm64, version 0.1.0 build 1,
Python 3.12.3 and PyInstaller 6.22.2. Its copied Shared app passes
`codesign --verify --deep --strict`, exposes the new staging option, and has
`source_dirty: false`. This is ad-hoc signed, not Developer ID signed or
notarized. Archive SHA-256:
`d173ccb5b80fc5a5b6f6dec02ed2d0e3634a76a86017b1dac9d70faa3e42ddcd`.
The Shared harness and existing `Start Codex Test.command` byte-match source.
An account-local launch is still required; no fresh transfer is claimed.

Verification: 67 focused tests pass on both Python 3.9 and Python 3.12.
The full Python 3.12 suite ran 650 tests: 638 passed, 12 skipped.
Mocked release-test output does not constitute a real notarization submission.
The single clean build worktree was owned by this acceptance task and retired
after confirming its revision on origin and the copied artifact checksum.
Its duplicate 29 MB build output was moved to Trash; the usable Shared package
and receipt remain available.

## Configuration-binding follow-up

The Shared isolated candidate is now superseded by clean revision
`d27a13d0c89c91534ffa1d9c280b11fa5ee2e406`. The default launcher and harness
paths are unchanged. Source-account process inspection showed the legacy failed
helper only, with no running authentic harness or isolated candidate, before
replacement. The unused `9ae70b5` package was moved to Trash; no running app or
migration data was replaced. The original failed helper still uses its original
path, not this candidate.

The new CLI prevents saved state from being rebound to a different source,
destination, scope, mode or staging folder. The authentic run uses pristine
`migration-isolated` state, so no legacy evidence is adopted. Repeated runs with
the same configuration retain their binding. Existing non-pristine unbound CLI
state requires review and is never reset automatically.

The new archive SHA-256 is
`82dbc7ec30e3c9a14661f7d1faa74034c0f79fbe161901105bbd23e61c63a91c`.
The copied app passed deep/strict code-signature verification and the ZIP passed
its checksum. A real CLI lifecycle test also passed against this packaged
engine: start, graceful stop, same-configuration reopen, and rejection of a
changed destination without changing state. It uses disposable local state and
does not contact a remote Mac. No token is printed by the test.

The full suite ran 660 tests (648 passed, 12 skipped); the subsequently added
real CLI lifecycle test passed separately. All 66 focused binding, state, staging
and harness checks pass on Python 3.9 and 3.12. The build branch was pushed,
the single clean build worktree retired, and its duplicate output moved to
Trash. Apple certificate confirmation and the real source-account launch remain
external checkpoints; checkout remains closed.

## Shared candidate permissions and signing identity follow-up

The Founder launched the revised runner. The latest public result has
`failed_phase: preparing`, `migration_started: false`, and a `codesign` exit 1;
the runner has exited. The copied `isolated-candidate` parent directory was
mode 700, preventing the separate source account from traversing it. This was
an artifact-publication error, not a transfer failure or a wrong user password.
Only that public artifact directory was changed to mode 755. All candidate
directories are now traversable/readable and all files readable by the test
account's permission class. Deep/strict app signature verification passes.
No app contents, source-account secrets, staging, backups or migration state
were changed. The correction still needs an actual source-account launch.
Future Shared publication must set the enclosing public artifact directory to
755 explicitly instead of retaining a private temporary build directory's mode.

The downloaded Developer ID Application certificate matches the existing local
private key and Team ID `P9J3JK79KQ`. The key was imported non-extractable with
access granted specifically to `/usr/bin/codesign`; the certificate and Apple's
official Developer ID G2 intermediate were imported into the login Keychain.
No trust override was added. Apple-chain verification succeeds and macOS lists
one valid code-signing identity. A disposable executable was actually signed
with hardened runtime and an Apple timestamp, then strictly verified. No
private key, password or credential content entered the repository or output.
Notarization authentication, submission and the exact signed app remain open.

Community feedback about interrupted/partly moved migrations is relevant.
The local fault-injection evidence covers partial transaction receipts and
explicit recovery preserving later destination work. It does not substitute
for the remaining packaged two-Mac interrupted-copy and interrupted-install
acceptance runs. Skills-only selection and recovery of an incomplete transfer
are different acceptance cases.

The harness now checks Shared wrapper and bundle directory/file read/traverse
permissions, plus engine executability, before code-signature verification or
remote preparation. It reports a fixed permissions diagnostic and never changes
permissions itself. The regression covers the exact private-wrapper failure,
nested private directories/files, a non-executable engine and a missing engine;
all fail before calling `codesign`. All 49 harness tests pass and the real Shared
candidate passes this new publication preflight. This is not a source-account
migration result.

The first notarization launcher did not execute: the Founder's terminal transcript
shows a stray `g` prepended to the absolute launcher path. The shell rejected
that path before any password validation. A fresh Terminal instance was launched
and a live owner-account `notarytool` process was confirmed. Credential validation
and Keychain persistence must still be checked after password entry.
