# In-app updates: release gate

The updater is a candidate until a signed, notarized build has installed a
newer release and relaunched successfully on a real Mac. Do not call this an
automatic updater on the website or in buyer email before that test passes.

## Design

- Sparkle checks the public `/api/appcast` feed. The feed advertises only the
  current approved Apple-silicon release with a valid EdDSA archive signature.
- A buyer links the private purchase email URL once in the Mac app. The app
  verifies it against the server and saves the token in this Mac's Keychain.
  The token is not sent to Sparkle's public feed.
- For the exact first-party `/api/update-archive` URL, the app adds the token
  to an Authorization header. The server rechecks the HMAC, paid Stripe charge,
  and refund/dispute state before issuing a fresh private Blob URL and
  streaming the approved release. It never embeds a private Blob URL or buyer
  token in the appcast.
- Sparkle verifies the archive signature and installs the replacement. The
  app's existing termination hook must shut down its local helper cleanly
  before replacement. An update never changes or migrates Codex/Vault data.
- A buyer can still download the newest compatible build from their original
  purchase link, or retrieve the original build. This is the fallback if
  in-app installation cannot complete.

## Required acceptance before release

1. Bump the app's build number; commit the exact source before release build.
   Build with the Developer ID identity, obtain Apple's Accepted notarization
   receipt, staple, and verify Gatekeeper. Keep the prior release available.
2. Sign the **final ZIP bytes** with Sparkle's EdDSA `sign_update` tool. Add the
   signature to the immutable release-catalog entry only after checking the
   archive SHA-256, byte length, embedded version, and accepted Apple receipt.
3. Upload the exact ZIP to private storage and independently read it back;
   verify its byte length and SHA-256. Promote only that catalog entry.
4. On a test Mac with an older updater-capable app, link a paid test purchase;
   check manually and via automatic check. Confirm download, signature
   verification, helper shutdown, in-place installation, relaunch, and new
   version. Confirm an active migration makes shutdown refuse the update
   safely rather than interrupting the operation.
5. Verify a missing/forged token, refund/dispute, wrong architecture, corrupt
   archive, wrong EdDSA signature, and unavailable network do **not** replace
   the installed app or expose a private artifact. Verify the email purchase
   link still downloads the previous release.
6. Only after this receipt exists, update public copy and buyer email to say
   that linked purchases receive in-app updates. Until then, say only that
   buyers can retrieve compatible newer builds from the original email link.

If a release is bad, stop promotion and restore the prior approved catalog
entry. Do not remove old private artifacts or revoke valid purchases. Sparkle
does not make rollback automatic; publish a corrected build with a strictly
higher build number.

## Build 16 physical update receipt — September 23, 2026

- The final Developer ID signed, Apple-notarized and stapled arm64 archive is
  `Codex-Migrate-0.1.0-build16-arm64.zip`, 9,591,579 bytes, SHA-256
  `60eff4dcb07088d01c966587e808f21d5fa74b8afb4eba45ed326543f07241f7`.
  The Sparkle Ed25519 signature in `commerce/releases.json` verifies against
  the public key embedded in the signed app. The private Blob upload was read
  back in full with the same byte count and SHA-256.
- An isolated, older build-15 app copy on the first Mac used a local appcast
  carrying that exact signature and archive. Sparkle discovered build 16,
  downloaded the ZIP, offered Install and Relaunch, and replaced the app in
  place. The resulting app reports build 16; strict code-signature verification
  and macOS Gatekeeper both pass as Notarized Developer ID. A relaunched copy
  started its local helper. A concurrent duplicate launch showed the expected
  already-running warning and did not modify migration data.
- The same final ZIP was copied to the second Mac solely for a non-invasive
  artifact check. Its SHA-256 matched, and strict code-signature verification
  and Gatekeeper both passed there. No app or migration was launched on that Mac.
- CI passed on Python 3.9 and 3.12 for the updater implementation. The
  purchase-token, appcast and private-archive failure cases have automated
  coverage. This local physical smoke does **not** by itself prove a paid
  purchase-link update through the Production proxy, automatic scheduled
  installation, or a clean-user-account first launch. Keep those as explicit
  post-deployment checks and retain the original-email download fallback.
