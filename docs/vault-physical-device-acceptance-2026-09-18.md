# Codex Vault physical-device acceptance — 2026-09-18

## Outcome

The guarded whole-history Vault install passed an end-to-end test across two
physical Apple silicon Macs. A thread created by the real Codex binary on the
source Mac was backed up, transferred, installed on the destination Mac, and
then successfully resumed by the real Codex binary there.

No live customer history was used or changed. The test used isolated,
owner-only temporary Codex homes and removed all temporary credentials, Vault
keys, snapshots, rollback data, source files, and remote folders afterward.

## Verified sequence

1. The source Mac created one disposable conversation with the installed Codex
   binary in an isolated `CODEX_HOME`.
2. Codex Vault created and fully verified one client-side encrypted snapshot.
3. The destination Mac's pinned Ed25519 host fingerprint was rechecked before
   transfer.
4. The encrypted Vault was copied to the second physical Mac over the existing
   authenticated SSH route.
5. The destination created a separate disposable conversation with its own
   installed Codex binary, providing real pre-install history to displace and
   protect.
6. Recovery-key import and installation ran in the signed-in GUI launch context,
   matching the packaged app's macOS Keychain environment.
7. The install engine verified the snapshot, created its owner-only journal and
   rollback backup, replaced only `sessions` and `archived_sessions`, and
   verified the installed tree.
8. Pre- and post-install hashes confirmed that `auth.json` and
   `installation_id` did not change. Their contents and hashes were not logged
   or committed.
9. The installed transcript bytes exactly matched the verified source snapshot.
10. The displaced destination conversation exactly matched the private rollback
    backup.
11. The destination's real Codex binary resumed the recovered source thread by
    its thread ID and completed a new turn in that recovered context.
12. Both temporary Keychain keys and every temporary credential, Vault, test
    home, and remote folder were deleted and the cleanup was verified.

The accepted snapshot reference was
`6e1a130d-11a9-4ff5-b584-e6faab42f7a5`; the disposable recovered thread was
`01a0b38d-216d-7052-ad1b-f803fa64ae84`. These identify synthetic acceptance
artifacts only and contain no customer content.

## Safety exception used by the harness

The destination user's real Codex app was intentionally left running and
untouched. The shipped installer correctly treats any Codex process in the
selected account as open and refuses installation. Because the acceptance home
was isolated from that live app, the harness bypassed only the account-wide
process predicate for the temporary home. The production guard remained enabled
in source and in the packaged workflow; all snapshot, journaling, rollback,
install, and verification code was exercised unchanged.

## Claim boundary

This evidence supports the claim that the tested current Codex build can resume
a whole-history Vault snapshot installed on a second physical Mac. It does not
prove compatibility with every Codex version, guarantee that every desktop UI
surface indexes every valid transcript, or complete selected-thread recovery,
retention controls, or cloud-folder health monitoring.
