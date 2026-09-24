# Sparkle signing-key rotation — September 23, 2026

The Founder approved rotating the inaccessible Sparkle Ed25519 signing key.
The live build 16, original purchase links, and public appcast remain unchanged
until an exact replacement passes the checks below. Do not delete the old key or
artifact. The new private seed is owner-only and outside Git; only its public
key is embedded in the candidate app. On September 23, a second owner-only
copy was placed on the Founder's other FileVault-enabled Mac over verified
SSH. A byte-for-byte comparison passed without displaying the seed; the
destination file and directory are owner-only. Keep both copies until a later
key-custody decision is explicitly verified.

Sparkle permits an EdDSA key change when the Developer ID signing identity
stays the same. Because this app enables `SUVerifyUpdateBeforeExtraction`,
Sparkle requires the rotation update to be a **Developer ID code-signed DMG**,
not a ZIP. See [Sparkle's key-rotation documentation](https://sparkle-project.org/documentation/#rotating-signing-keys).
This is the reason for the one-time DMG path; later releases may return to ZIP
after the new key is installed.
The packaging check pins the leaf Developer ID certificate from live build 16;
the Apple signing certificate must not change during this EdDSA rotation.

The new public key is `yFTFQ4PptkxpiW2K402K8NaMKsvfyG6tUffSqtRxrKg=`.
The private seed must never enter Git, logs, tool output, the web host, or a
customer artifact. Sparkle's `sign_update --ed-key-file` reads it locally;
the signer must verify its output against the final DMG bytes.

## Release sequence

1. Commit reviewed source with the new public key, idle-install race guard,
   and DMG-aware commerce. Run Python, Node, and Swift checks.
2. Build and notarize the exact clean-source app with `desktop/build.py
   --release`. Its ZIP is only an intermediate source receipt and must not be
   promoted as this rotation update.
3. Run `desktop/package_rotation_dmg.py` against that exact build directory,
   using the same Developer ID Application identity and a working Apple
   notarization credential. The command signs the disk image, records its
   separate Apple submission, staples it, verifies Gatekeeper, and produces an
   exact DMG receipt. If Apple's submission is interrupted, resume its saved
   output directory; do not submit another copy blindly. The submitted image
   remains byte-for-byte unchanged while a separate copy is stapled. A failed
   staple can be retried; a completed image with interrupted receipt writing
   is verified against its recorded final hash before its receipts are restored.
4. Sign the final DMG with Sparkle's new private seed. Verify the signature,
   public key, DMG SHA-256, byte length, embedded build number and source SHA.
   Add the reviewed DMG entry to the release catalog only after these match.
5. Upload to private Blob storage and independently read back the exact bytes.
   Before Production promotion, use a paid build-16 test installation to prove
   Sparkle accepts the Developer ID DMG key rotation, installs build 17, and
   relaunches with Vault and migration state untouched. Exercise invalid
   signature, corrupt DMG, missing/refunded entitlement, offline, low-space,
   busy migration, and running scheduled-backup paths. Confirm opted-in idle
   installation and periodic checking after relaunch.
6. Promote only after these receipts pass. If Sparkle cannot rotate in this
   configuration, keep build 16 live and offer a one-time manual replacement
   through the original purchase link. Be explicit with buyers; never claim a
   seamless automatic update that has not been observed.

The separate notarization Keychain remains locked. A Founder-approved App
Store Connect Team API key was generated for notarization; its owner-only
private file remains outside Git and `notarytool history` accepted it. From
clean source `004d3e28f8d40c656784b17af523bf8237a42d19`, the app and
rotation DMG received Apple Accepted notarization receipts
`ea31c59b-da11-415e-8357-dbfbba7cc198` and
`03552619-b676-492b-bd80-80f9a3b79972`. The final DMG is 10,356,114
bytes with SHA-256
`861b7f1341d79da87a64e0399a7450904e89241d507ff877dfa1a3ce428efe70`.
Its Sparkle signature verifies independently against the public key embedded
in the app. A read-only mount passed strict code-signature and Gatekeeper
checks, and private **sandbox** Blob storage returned matching bytes. The
isolated local build-16 app subsequently discovered build 17 through a
loopback appcast, downloaded this exact DMG, and Sparkle replaced it in place.
The installed build 17 passes strict code-signature and Gatekeeper checks and
starts its helper. The old test app was locally re-signed after changing only
its feed and automatic-check settings; this is not a paid-entitlement test.
Relaunch also produced a second process with an already-running warning,
which prompted a same-installed-copy quiet-exit fix. That source change
supersedes this image as the final release candidate, although the image
remains valid proof of Sparkle's key-rotation mechanism. Rebuild and repeat
the physical installation, then complete paid-entitlement and failure-path
checks. No live catalog entry or appcast has changed; build 16 remains the
paid beta.
