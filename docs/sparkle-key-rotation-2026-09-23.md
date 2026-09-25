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
   notarization credential. The packager refuses a stale source receipt or
   dirty checkout; resume from the original clean source commit if the branch
   has moved since submission. The command signs the disk image, records its
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

The same-copy relaunch fix was committed as
`35c775d4854525a8f49f1c2b78582926821a8c6c` and rebuilt. The replacement
app received Apple Accepted notarization receipt
`3d92ba3e-4f16-438a-b332-8a9676983a95`; its signed and stapled DMG received
Accepted receipt `9d526d9a-b67e-422c-b598-00f75ca27095`. Final DMG size is
10,354,263 bytes, SHA-256
`e61280cf3045db6deb559fa9c70e434513883ef9d731080fcd732fad9d9ae330`,
Sparkle signature
`OhLypSR6qkktLrru6xC+7TJMSUztKuFA4ah9t45vK9A4Qjrqxv2nEyViyuwXLOPqvgoA/r5bSEvXzbA9vPi+DQ==`.
The mounted app passed strict code-signature and Gatekeeper checks, and the
image's exact bytes were verified from private sandbox storage. The exact
candidate is catalogued for sandbox-only testing with `testingOnly: true` and
`accepted: false`; the live release selector cannot use it. A second
isolated build-16-to-17 local Sparkle upgrade installed this image in place;
the resulting app contained the exact clean-source receipt and started one
healthy helper. This still does not certify the paid Production path, idle
automatic installation, or the required failure-path matrix.

An isolated automatic-install smoke then found an AppKit termination deadlock:
the idle probe requested a quit, but `terminateLater` waited for a main-queue
reply that could not run. The source now cancels that first quit, waits for the
helper to exit, and requests a fresh quit. A Developer ID re-signed test copy
with that fix, a synthetic purchase token and a loopback appcast downloaded the
exact notarized DMG and installed build 17 without a manual quit; the installed
app passed strict code signing and Gatekeeper. It did not relaunch afterward.
The test copy and token were removed. This is a local mechanism test, **not**
a live build-16 or Production paid-update test. The notarized DMG above
predates the fix and must be rebuilt before release.

Clean source `1d90604cec80b2bf34e8d7d8137c5414cb2dc18e` then produced a
Developer ID signed, stapled app (Apple Accepted receipt
`19928083-f977-486c-aefb-cbd998e24270`) and a separately signed, stapled
10,356,805-byte rotation DMG (Accepted receipt
`ca8e6c31-5080-4c50-aa81-c207219c6a80`, SHA-256
`c0a2c4df6c6bb035cc3f4e9fe331b9bf4b5b28fb8bdda1a3035c3321607fa824`).
Its Sparkle signature
`gKPgDt/x88kga/D1H6Xdx2oOSXS5mFLlUx5utgxNtjDNtbG6Dy1/G3mD5kFvdpDJDlBQbUeMFbUuvKdP6pGrCQ==`
verified independently against the embedded public key. Private sandbox Blob
readback matched the full image. A local signed test copy installed this exact
DMG automatically but did not relaunch, as Sparkle's default install-on-quit
does not. Source has since changed to invoke Sparkle's immediate-install
callback only after a final idle check and helper exit. An isolated signed
test copy with that client change installed the same DMG and **relaunched**;
strict signing and Gatekeeper passed. The new client source is not yet in a
notarized DMG, and neither test exercised a real paid Production entitlement.

The relaunch change was committed as
`ee40e565d3c5890e818dd2c6cbc2f1e30de97d40` and rebuilt from clean
source. Apple Accepted the app (`c36e16c2-637f-498d-9e68-ee3ff44a090b`)
and separately signed DMG (`22e674ea-e5e0-4b67-bb61-520c2f020221`). The
final image is 10,355,906 bytes, SHA-256
`bc0da26470268ff37f9d37cd512d0a957dc502b7074256554e5ef051c040d383`,
with Sparkle signature
`NIaFQk/T554fh1WCXjUudBl9xVBWEJ15r9PFd1r4jeQ7a6xJ9ZTSRO05+GNmuSXpd1Td4TgQTSZIKYvGtRGuCg==`.
Independent Ed25519 verification and private sandbox Blob readback passed.
The isolated local build-16 test copy automatically fetched and installed this
exact DMG through Sparkle, then relaunched one app and helper. Its installed
source receipt, code signature and Gatekeeper check passed. This copy used
a local appcast and synthetic Keychain token, so real paid authorization,
pristine live-build-16 installation, busy operations, clean-account first
launch, and second-Mac application checks remain required before Production
promotion. The exact DMG's size and SHA-256 also matched on the Founder's
second Mac (macOS 26.5); a read-only mount passed strict signing and Gatekeeper
checks there without launching the app or touching Codex data.

An additional rotation proof used the archived **live build-16 ZIP** itself,
whose digest matched the live release catalog. Its embedded old Ed25519 public
key and build number 16 were retained; only a disposable test copy's feed URL
was changed to loopback, requiring re-signing with the unchanged Developer ID
identity. That old app accepted the final build-17 DMG, reached Sparkle's
**Ready to Install**, installed, and relaunched a single build-17 app and
helper. The installed bundle contains source `ee40e56` and the new public key,
and passed strict code-signature and Gatekeeper checks. The isolated copy,
synthetic Keychain item, temporary update settings and HTTP server were cleaned
up. This closes the old-key-to-new-key mechanism gap, but a real paid
Production-entitlement update and the remaining busy/failure-path tests still
gate live promotion.

The current guarded candidate supersedes those earlier images. Clean source
`479780861710a857dedde8d8de0716999320721a` produced an Apple Accepted
app (`2ed37213-04bc-46bf-860e-12ca8d6e457e`) and one-time rotation DMG
(`111275c0-d44e-4ff1-b903-b046db98321f`). The 10,368,949-byte DMG has
SHA-256 `8aace2577a612bc9dcc064cad3f63dad57a0ecb02b042ac2b06d1748ad0b8486`
and verified Sparkle signature
`fn7ZhI/7P5WiYn5580/Q/PBsXt0XGCw1EClZ1ddvjbJUpkWrVc0wEfu/xvyT7cuWxR9Jkd7QTNf4B1o3ZgiwCQ==`.
Private sandbox storage returned identical bytes. Its catalog entry remains
testing-only and unaccepted; the paid live release is still build 16. The
normal native installation and failure-path acceptance listed above have not
been completed for this exact image.

An updater first-open hardening change superseded that candidate. Clean source
`90f1cb29e377675f730aeee1207d6cb5fe7f090b` produced an Apple Accepted,
stapled build-17 app (`5f19c6ed-d861-4e0c-9d1e-d3f0e71bcfee`) and a
separately signed, Apple Accepted, stapled DMG
(`77cc1e96-8b28-446b-836d-cafbf8941b03`). The final image SHA-256 is
`f9d4f5b580a7637f3a5dcc73e58598760824f7d8475934a71bb05379b0a76f51`;
its Sparkle signature is
`W1Db4e3BORBja+NcrvwH5jxRXDy7g2CJiHzPK/UeH2HkOA4HFGqyRRgko3soaYlg+ewRRFqPtB2hZ0LQ62DpCQ==`
and verifies against the exact DMG bytes with the public key embedded in that
app. The mounted-image unsafe-location warning and exit passed physically;
an initial manually quarantined first-open test stalled at macOS's approval
dialog; a second, correctly dated disposable quarantine copy launched from
App Translocation, showed the expected warning, started no helper, and exited
after dismissal. A true browser-download first open and clean-account run
remain open. The exact image was uploaded to private sandbox
storage, read back byte-for-byte, and catalogued as testing-only and
unaccepted. The exact bytes also passed signature, staple, Gatekeeper, and
read-only mounted-app checks on the Founder's other arm64 Mac; no app was
launched there. It has not been promoted. Build 16 remains public.

A subsequent native quit-handoff review found that helper exit could race
ahead of the successful update-shutdown response. The app must not treat exit
alone as proof that the Vault update guard was committed. Source now requires
that response before Sparkle may replace the bundle and refuses a staged
update if the helper is missing and no guard was confirmed. The preceding
image predates this fix, so its Apple receipts and Sparkle signature remain
valid only for that superseded image; build a new exact-source candidate and
repeat physical update acceptance before promotion.

The rebuilt race-fixed candidate uses clean source
`b510f2166f30fe2856b0ec04599237c07d4a570d`. Apple accepted the signed
and stapled app (`c0f3b663-ebc1-4b00-a38f-217edcdfbfb2`) and the
10,375,160-byte rotation DMG (`a904a709-5c83-4459-bb50-887f3e7b6486`).
The image SHA-256 is
`9890bffb25ca30c9d080dfe9ae6ed2f61902fec6f26c103965fba8f902ba7b79`;
Sparkle signature verification passed. Private sandbox storage returned
identical bytes. The catalog entry is testing-only and unaccepted; neither
appcast nor paid buyer delivery has been changed. Physical installation and
clean-account acceptance are still required before promotion.

An invalid-signature physical probe of that image exposed a stale native
ready-to-install flag after Sparkle had already aborted. Source now clears
uncommitted update readiness on Sparkle abort, failed download and user
cancelation; an isolated repeat of the bad-signature case left the old app and
synthetic transcript unchanged and created no Vault update guard on a normal
quit. Clean source `27ef9bf1d4c89ae9fb1853ed0e37a57458db39cf` was rebuilt
and notarized: Apple Accepted the app (`0ee9063e-e017-4283-b646-434c81337cd7`)
and separately signed DMG (`f3179da8-56d6-4cb5-b43c-a3e19d2aa7af`). The
10,376,201-byte image's SHA-256 is
`bf33da502e15a012c287efc5cec6c9b3057bf544c9ebbf8d9aebb1d91d2c1dc6`;
its Sparkle signature
`NPh2GD88tMlk9/aeyA/zkTTZkKX2DxccR16JJaSfh4UHm+mdpom9x26v5Nrn2ifAk6YbYHXRNbXJuCdZLO5UCQ==`
verified against the exact bytes. The mounted app and DMG passed staple,
strict signing and Gatekeeper checks. Private sandbox storage readback matched
the image; its catalog entry is testing-only and unaccepted. Build 16 remains
live. Re-run buyer-path and clean-account acceptance with this exact image
before any promotion.

The exact `27ef9bf` DMG subsequently passed an isolated automatic 16-to-17
Sparkle installation with the old public key and a loopback appcast. The
installed executable matched the notarized candidate byte-for-byte; its
source receipt, build number, strict signature, Gatekeeper result, and
unchanged synthetic transcript were checked. A target-build-17 Vault guard
was written before replacement. The test artifacts were removed afterward.
The other already-running app on this account prevented a separate healthy
helper after the test copy relaunched, so clean-account relaunch and the real
paid Production path remain release gates.

The exact same `27ef9bf` DMG was independently checked on the Founder's
second Mac (macOS 26.5, Apple silicon): remote length and SHA-256 matched,
and a read-only mount passed strict deep signing, stapled-ticket validation,
and Gatekeeper as Notarized Developer ID. The mounted app reported build 17,
the rotated public key, and the `27ef9bf` source receipt. The mount was
detached and the disposable image moved to Trash without launching the app.
This is artifact compatibility evidence, not a second-Mac install test.

The next exact-source candidate is clean commit
`bed7cba5c85f2f4316ca9f2c10a67af6b807c92c`. Apple Accepted the signed
and stapled app (`9837371b-3677-476a-9c5c-c9a5a8719b8c`) and separately
signed and stapled rotation DMG (`741699d3-7c88-4c12-bf55-32ec38bcf578`).
The final 10,397,434-byte DMG has SHA-256
`09159745ee1e5ba08a3dc9e9baf37d23419310a4a49daca16032de890e15dd6e`;
its Sparkle signature
`lxYQ9ErXTBxP4qS42HcrKaodZ0K7AE4OYWKeMD4uNFhOA3RF/IfiCoj73e8BL+PhjyiVD3XkGPZeW6Sw2R7oAg==`
verified against those exact bytes. Apple staple, strict signing, and
Gatekeeper checks passed. The exact image was uploaded to the private sandbox
store and independently read back in full with matching length and SHA-256.
The catalog entry remains `testingOnly: true` and `accepted: false`; build 16
remains the live paid release. Physical paid-update, idle/busy-operation,
failure-path, and clean-account acceptance are still required for this exact
candidate before promotion.
