# One-launch authentic conversation test handoff

Prepared September 6, 2026. This is an engineering harness, not customer UI.
Its live cross-Mac preparation passed both account sign-in checks, but authentic
conversation creation failed before migration began. There is no authentic
migration acceptance receipt yet. Original personal workspaces are not selected.

## Founder steps

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
passes 26 deterministic tests, without a real account login or model call.
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
