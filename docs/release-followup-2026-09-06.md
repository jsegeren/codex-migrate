# Release follow-up: backup failure and owner notifications

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
