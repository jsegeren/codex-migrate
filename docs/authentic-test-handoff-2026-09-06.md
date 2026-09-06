# One-launch authentic conversation test handoff

Prepared September 6, 2026. This is an engineering harness, not customer UI.
Its live cross-Mac run has **not** occurred yet. The existing synthetic acceptance
receipts and original personal workspaces are not changed by preparing the files.

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
passes 15 deterministic tests, without a real account login or model call.
Launcher shell syntax is checked. The installed local Codex CLI is 0.153.4;
the protocol field names were checked against its generated schema.

The implementation follows the official [Codex app-server protocol](https://developers.openai.com/codex/app-server/).
Protocol-created conversations are real Codex conversations, but passing this
test will not by itself certify their presentation in the desktop sidebar.
After the automated test, separately open the three restored test conversations
in the new Mac's desktop app and verify their visible history and continuation.
That final rendered check remains explicit, as do the other open release gates.
