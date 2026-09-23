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
   output directory; do not submit another copy blindly.
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

The separate notarization Keychain is currently locked. No candidate DMG has
been notarized, uploaded, or promoted. Build 16 remains the live paid beta.
