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
  separate path. The provider's webhook delivery-attempt log was not inspected.

This is successful ordinary-Stripe sandbox payment and fixture delivery, not
signed-app delivery or a real sale. A refund/revocation check for this exact
new session, hosted checkout HTTP ingress, and owner-notification delivery
remain unverified. Prior Managed Payments refund evidence is not relabelled
as ordinary-Stripe evidence. The invitation flag was supplied only to this
explicit Preview build; normal builds leave the helper skipped. Do not rebuild
with the invitation flag merely to obtain another email.
