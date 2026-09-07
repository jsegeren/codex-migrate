# Release follow-up: backup failure and owner notifications

## September 7: exact backup diagnostic and source correction

The Founder ran the one-shot administrator-authorized probe. It exited zero
and saved its bounded shared report at timestamp `1788764465`. On the actual
failed destination backup it found one missing socket, with matching counts
of 1,989 regular files, 618 directories and three links, no extra entries and
no changed node types. Both build-2 and build-3 rsync comparisons remained
non-clean. No structural change was detected across the probe. There was no
backup verification receipt or pending transaction. Counts do not independently
prove file bytes match; the diagnostic deliberately exports no filenames,
contents or hashes. It did not restart, repair or install anything.

The source correction handles only actual sockets in recognized destination
Codex runtime locations. A shared predicate is used by the full Codex backup's
content/tree comparison and the original-data check immediately before creating
the transaction. The backup itself retains strict, exclusion-free fingerprints;
the durable transaction format and later recovery checks are unchanged.
Workspace/skill checks and incoming source-data rules are unchanged. Ordinary
files, links and directories with socket-looking names are not omitted.

The real probe did not export the missing socket's location, so it does not
prove that socket qualifies for this narrow exception. Current build 2 has not
been replaced or retried. This source correction still requires a refreshed
packaged candidate and the real two-Mac acceptance test; it is not release
approval or a claim of successful migration.

Initial local macOS acceptance: 55 tests passed on system Python 3.9, including
actual APFS socket/clone handling, full installation with preserved destination
identity, injected post-install failure with verified rollback, rejection of
ordinary data loss/corruption and workspace sockets, and existing transaction
write-failure tests. The full Python 3.12 suite then ran 698 tests: 686 passed,
12 skipped. The expanded Python 3.9 backup/transaction/recovery/disk suite ran
74 tests: 69 passed, five opt-in disk tests skipped. All 13 builder tests also
passed on Python 3.9. Test-suite notarization messages are mocked, not actual
Apple submissions. Build number 4 distinguishes the corrected candidate.

The release task owns the single sibling build worktree
`/Users/jsegeren/Git/codex-migrate-release-build` on
`codex/signed-candidate-build4-2026-09-07`. It is retained only while building,
notarizing or preserving this candidate's evidence; retire at handoff or by
September 14, 2026 if Apple processing prevents completion. It must not replace
the still-live build-2 test helper without a reviewed handoff.

### Build 4 signed, notarized and preserved

Exact clean source `8d14dbf1877d1fc71a509d6eab86b18ec4014b52` was pushed on
the task and signed-candidate branches. The real release builder used the
existing Developer ID identity and Keychain notarization profile. Apple job
`ede65a70-5dfc-4617-9dda-0dc8272a6d48` returned **Accepted**. Stapling, staple
validation, strict signature verification and Gatekeeper assessment passed.
The exact packaged engine ran nine desktop checks: eight passed, one skipped.

The app, archive and receipts were copied without overwriting any earlier build
to `/Users/Shared/CodexMigrate-Authentic-20260906/accepted-build4`. Independent
signature and Gatekeeper checks passed on that saved copy. Artifact:

- `Codex-Migrate-0.1.0-build4-arm64.zip`
- SHA-256 `bba8b35f55b61389b0b36e65e50f45962975d7944d19293420e11a3f19a19d08`

The clean build branch was verified on origin, no process retained the build
worktree as its working directory, and generated build evidence was moved to
`/Users/jsegeren/.Trash/codex-migrate-build4-evidence-20260907` (recoverable).
The manual worktree was removed through Git and pruned; its retirement
requirement above is satisfied. Shared `accepted-build4` remains usable. No
Apple job is pending, no current test helper was replaced, and no live
checkout/catalog setting was changed. Exact two-Mac acceptance remains open.

## Earlier investigation

The refreshed owner-exported installation diagnostic at timestamp
`1788761076.260705` reports `backup_comparison_differences`, not an incomplete
comparison or missing backup receipt. It reports failed/installing, a pending
backup reference, no installation receipt and unknown recovery status.
It contains no file paths, raw errors, workspace content or credentials.

This narrows the actual two-Mac failure but does not attribute it to the locally
reproduced FIFO issue or establish recovery. The original build-2 helper was
verified live as PID 84016. No retry, restore, state reset or helper replacement
was performed. Source-account private access still requires that account;
unlocking the personal account does not grant cross-account filesystem access.

The current Stripe session was inspected using Chrome's native accessibility
surface after its tab-debugger attachment failed. In the existing Segeren Studio
account, the owner's identity email is `joshua@segeren.com`. Personal settings →
Communication preferences → Transactions and Balances shows **Successful
payment receipt — Email** already enabled. No setting was changed and no
duplicate custom owner-email sender was added. This proves the configured
preference, not delivery of a new purchase notification. That remains part of
the real purchase acceptance check.

Build 3 private artifact transport and worktree retirement are recorded in
`signing-candidate-2026-09-06.md`. Exact-app buyer download/launch and real
two-Mac migration/interruption/recovery remain open.

## Ordinary Stripe sandbox buyer acceptance

Source `ef382218e93f7058a37db5729585ac90ed7e4808` passed all 255 Node tests.
Guarded Preview `dpl_D4vUhyP8UFVuST6cfNsk1bk2KnTu` reached READY with ordinary
Stripe selected for build and runtime. Only the existing
`codex-migrate-commerce-sandbox.vercel.app` alias was repointed; Production
aliases, closed checkout and disabled live webhook were not changed.

The explicit build-only invitation used request UUID
`6cb5167a-54a1-41cf-979c-3cc72bcbe8b9` exactly once. The actual checkout handler
created sandbox session
`cs_test_a15FDnoaCwWTDscTSCsUQVzShRHU4i3z2HBsVU92Q3XJOWlsULzqbY2pwH`.
The helper reported mail accepted, no payment attempted by the helper, and
`hostedCheckoutRequestTested: false`. This exercises the real handler with
hosted credentials but does not prove its HTTP ingress. Credentials and
purchase/download bearer links are excluded from this receipt.

Chrome native UI acceptance then proved:

- The TEST ONLY invitation arrived in `joshua@segeren.com` Inbox.
- Stripe displayed the sandbox $50 one-time product. Synthetic test card and
  billing details completed payment; no real money was charged. Saving the
  card to Link/Google Wallet was declined.
- The returned buyer page displayed "Your purchase is verified".
- Download for Mac opened the normal Save dialog and saved the 451-byte
  harmless sandbox ZIP. Its SHA-256 matched
  `1a9d8e5775804a42e03655c7653d4d5315fca718445a2aecff144f00faf53343`.
- The separate TEST ONLY delivery email arrived in Inbox at 11:17 PM local.
  Opening its recovery link also displayed "Your purchase is verified".
  The status/download handlers do not send mail; fulfillment email is a
  separate path.

This is successful ordinary-Stripe sandbox payment and fixture delivery, not
signed-app delivery or a real sale. A refund/revocation check for this exact
new session was initially pending and is now proven below. Hosted checkout
HTTP ingress and owner-notification delivery remain unverified. Prior Managed
Payments refund evidence is not relabelled as ordinary-Stripe evidence.
The invitation flag was supplied only to this
explicit Preview build; normal builds leave the helper skipped. Do not rebuild
with the invitation flag merely to obtain another email.

### Exact-session webhook and refund follow-up

In Stripe's sandbox UI, payment `pi_3UCvrdQwGK6ZgBcK0qQzMZN6` matched the
synthetic buyer, $50 product and completed checkout session above. Its
`checkout.session.completed` event `evt_1UCvrfQwGK6ZgBcKWTA134dY` showed a
**200 OK** webhook delivery to the existing sandbox alias at September 7,
06:17:12 UTC. The endpoint's deployment-protection credential is deliberately
not included here.

Only that new synthetic payment was refunded in full, with reason Other and
an internal sandbox-acceptance note. Stripe displayed **Refunded**. Opening
the same Inbox delivery link again changed the buyer page to "This purchase
needs review. Please email Josh for help." The rendered page had no
Download for Mac link and retained Check again and support controls. This
proves a refunded ordinary-Stripe purchase cannot obtain a fresh download
through its email credential. It does not revoke an already downloaded file
or promise immediate revocation of an already issued short-lived storage URL.
No real money moved, no payment details were saved, and other test payments
were not changed.

### Migration access revalidation

The original build-2 helper PID 84016 was still live under UID 502. A
noninteractive source-account identity check required a password. A separate
read-only target login check used the exact host fingerprint already supplied
by the Founder, verified before SSH. Host verification passed, but existing
credentials in the personal account were rejected. No host-key bypass, new
credential, persistent trust change, permission change, migration retry or
recovery action was performed. The actual backup comparison remains unresolved;
the generic shared error label is insufficient to diagnose its file-level cause.

Temporary deployment source and the temporary public-host-key check directory
were moved to the personal account's Trash after use, preserving recoverability.
The failed test's source, destination, backups, helper and state remain intact.
