# Hosted service acceptance — October 3, 2026 UTC

Owner: the primary Codex Backup implementation task. This is an engineering
checkpoint, **not a hosted release, successful customer backup, or VM recovery
certification**. Production checkout, appcast and customer data were not changed.

## Completed at this checkpoint

- Deployed the actual `hosted/r2_object_worker.mjs` to the sandbox Worker
  `codex-backup-service-sandbox.segerej.workers.dev`, bound to the existing
  `codex-vault-sandbox-20260927` bucket; installed a private signing key.
- Used a one-off account-scoped Workers Scripts Write token. Its expiry was
  October 3, 23:59:59 UTC. Removed it after deployment, confirmed verification
  returns HTTP 401, and discarded its local private credential file. No standing
  Cloudflare deployment credential was retained.
- Configured sandbox-only hosted API settings on the existing project's Preview
  environment. Checkout remains closed. Production settings were not changed.
  Branch-scoped settings were unavailable because the Vercel project reports no
  connected Git repository; Preview settings were used, not Production settings.
- Created Preview deployment `dpl_9KA2sqg9Riien5tmUdLYUSPcNepk` at
  `https://codex-migrate-4jvf4q3c5-joshuas-projects-d3a5c48d.vercel.app`.
- Confirmed direct access is protected by Vercel authentication; supported
  `vercel curl` reaches the real recovery handler. Its deliberately malformed
  request returns `invalid_request`. This does **not** prove device authorization.
- Added an operator-only real-service driver and failure-regression tests.
  Native device credentials remain in Keychain, recovery keys are private input
  files, and the driver accepts only the named project's HTTPS Preview origins.
  It cannot grant itself an entitlement or sign its own object capabilities.
- Publication receipts bind a random synthetic case nonce and the remote sealed
  catalog's exact thread ID, path, size and digest. Local source changes, an
  unowned nonempty Vault, and overlap with live state are refused.
- Durable private attempt markers reconcile lost publication/receiver receipts.
  Recovery retries preserve partial outputs and never install into live Codex.
- 21 harness safety/regression tests pass. The existing live-run suite passes
  26 tests and the recovery-client suite passes 21 tests. These are local tests;
  mocks do not count as successful real-service or VM acceptance.
- Independent reviewer `public_release_review` accepted the final bounded
  harness as-is after fixes to fixture binding, durable retry ownership and
  live-state overlap. Its independent 21-test run, compilation and diff check
  pass. That review does not certify a real cloud/VM run.
- Read-only sandbox preflight matched all 42 source migration receipts and
  found the required tables. It ran as an operator check, not as a hosted build
  check; it does not certify schema drift or customer backup/recovery.

## Next required proof

1. Connect the native driver to the protected Preview using a supported,
   narrowly scoped authenticated test transport. Do not disable deployment
   protection or embed its credentials in shipping code.
2. Enroll a synthetic buyer and its two separate native devices through the
   actual purchase/email path. Verify a real Stripe **test-mode** subscription;
   do not use fabricated purchase/subscription rows as acceptance evidence.
3. Publish, independently reopen the remote manifest, and prove a no-change
   run does not create a new snapshot or upload unchanged content.
4. Pair the independent Mac VM, import the separately saved recovery key, and
   download/decrypt/restore exact bytes through the actual hosted routes.
5. Run corrupt-object, interrupted-upload/download, lost-response and last-good
   pointer tests. Then run the real scheduled/background acceptance and billing
   lifecycle tests. None of these is green from this checkpoint alone.

## Driver entrypoints

Use `PYTHONPATH=src python3 ops/hosted_service_acceptance.py --help`.
Every mutating action requires `--apply`. `prepare` creates a new private synthetic
home under a fresh operator-selected root; it refuses existing paths and live
Codex/app-state overlap. `publish` requires an already enrolled synthetic device,
expected account/Vault identity, existing private encryption metadata, and the
native helper. `recover` runs in the VM using its own paired device, a private
publication receipt, and a separately transferred private synthetic recovery key.
Do not pass keys, tokens, signed URLs or personal transcript content in arguments.

Keep output and key files outside Git. The source authority is the task branch
`codex/hosted-service-acceptance`. Its sibling worktree is temporarily retained
for the active acceptance task and independent review, with retirement due by
October 4, 2026. Preserve/push the exact handoff SHA before retirement.
