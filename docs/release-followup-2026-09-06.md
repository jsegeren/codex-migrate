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
`signing-candidate-2026-09-06.md`. Ordinary Checkout buyer completion, exact-app
download/launch, and real two-Mac migration/interruption/recovery remain open.
