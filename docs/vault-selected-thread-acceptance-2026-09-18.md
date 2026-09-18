# Codex Vault selected-thread physical acceptance — 2026-09-18

## Outcome

Selected-conversation recovery passed an additive, encrypted two-Mac test on
physical Apple silicon hardware. The source revision under test was
`8e6aa242f193f9878e57f1202fa4d782db0bacde`.

The test used only synthetic content in isolated owner-only temporary homes.
The receiving account's real Codex and ChatGPT processes remained running and
its real `~/.codex` tree was never selected, read or changed.

## Verified sequence

1. The source Mac created one synthetic active transcript in an isolated Codex
   home.
2. Codex Vault created and fully verified a client-side encrypted snapshot.
3. The encrypted Vault and current recovery engine were copied to the second
   physical Mac over the existing pinned SSH connection.
4. Recovery-key import and all cryptographic operations ran in the receiving
   user's GUI launch context, matching the packaged app's Keychain boundary.
5. The receiving isolated Codex home began with a different conversation and
   unrelated configuration sentinel.
6. Planning reported exactly one additive conversation recovery and made no
   change.
7. Applying recovery re-verified and decrypted the snapshot, installed only
   the selected missing transcript, verified all pre-existing transcripts
   unchanged, and wrote the owner-only restore receipt.
8. The installed transcript's bytes matched the source snapshot exactly. The
   pre-existing conversation and unrelated configuration sentinel remained
   byte-for-byte unchanged.
9. A second plan for the same thread returned `already_present` and made no
   change.
10. The temporary recovery keys, Vault, test homes, engine copy, receipts and
    runner were removed from active locations after success.

## Safety exception used by the harness

The shipped installer correctly blocks whenever any Codex writer is running in
the selected account. Because the Founder needed to keep working on the second
Mac, the test used a separate temporary home and bypassed only that
account-wide process predicate inside the private acceptance runner. The
production guard remains enabled. Encryption, snapshot verification, private
staging, additive collision handling, atomic installation, unchanged-history
verification, receipt creation and key deletion all ran through the production
implementation.

## Claim boundary

This is source-level physical-device evidence for the selected-thread recovery
engine. It does not claim that the exact signed build 12 package has passed
Gatekeeper or buyer delivery, nor that every Codex version will surface every
valid transcript. Whole-history recovery and real-Codex thread continuation
have separate physical evidence in
[`vault-physical-device-acceptance-2026-09-18.md`](vault-physical-device-acceptance-2026-09-18.md).
