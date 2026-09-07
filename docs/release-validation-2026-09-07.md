# September 7 final-release validation checkpoint

Candidate: version 0.1.0 build 4, arm64, source
`8d14dbf1877d1fc71a509d6eab86b18ec4014b52`, archive SHA-256
`bba8b35f55b61389b0b36e65e50f45962975d7944d19293420e11a3f19a19d08`.
Harness/documentation branch checkpoint before this run: `28d5248`.
The initial validation did not change candidate code, public deployment, payment
settings or personal workspace. Later fixes and hosted checks are recorded in
the dated sections below. This is not release approval.

## Completed checks

- Full Python 3.12 suite: 701 tests, 689 passed, 12 explicitly skipped.
  Builder tests use mocked Apple responses; their console messages are not
  new notarization submissions.
- System Python 3.9 recovery/restore/guided-recovery/full-skills suite with
  `CODEX_MIGRATE_REAL_DISK_TEST=yes`: all 68 passed. The five opt-in disk tests
  used bounded disposable APFS images, including genuine low-space/write
  failures, verified retry, completion under pressure and automatic rollback
  under disk exhaustion. Images were detached and fixtures cleaned up.
  Process snapshots and transport are local synthetic fixtures, not physical
  network/cable interruption evidence.
- Exact packaged build 4 engine: nine tests, eight passed, one skipped.
- Node 24 website/commerce tests: 258 tests, 257 passed, one skipped.
- Real Chrome recovery UI: Check recovery verified the backup; Restore backup
  presented the destination and exact selected paths for confirmation. After
  confirmation, the independent fixture-proof endpoint returned HTTP 200 and
  confirmed original destination files restored, newer displaced files retained,
  source and backup unchanged, no pending transaction, and migration not complete.
  These were disposable APFS fixtures, not the authentic test-account contents.
- Rendered recovery UI reviewed at 1440px and 390px; reflow also checked at
  320px. No horizontal page overflow. Visible buttons use 15px type without
  underlines. Keyboard Tab focus has a visible 3px outline.
- Axe checks for WCAG 2 A/AA, 2.1 AA and 2.2 AA tags reported zero automatic
  violations at desktop and mobile widths. Gradient backgrounds produced
  incomplete contrast results. A temporary audit-only substitution of the
  brightest gradient endpoint found no contrast violation; heading and muted
  foreground contrast against that endpoint calculate to 15.20:1 and 9.08:1.
  Screenshots were inspected. This limited rendered check is not native
  VoiceOver testing or a full WCAG conformance claim.
- Live homepage Lighthouse 12.8.2 at `2026-09-07T18:21:25.288Z`: mobile lab
  scores **100 performance / 100 accessibility / 100 best practices / 100 SEO**.
  Advisory opportunities remain for unused JavaScript (71 KiB), image delivery
  (33 KiB), legacy JavaScript and the request chain. Scores are one lab run,
  not field performance, Google ranking or full accessibility certification.

Browser checks used the Playwright skill and a separate test browser. The
recovery server, test browser and disposable disks were stopped/cleaned up.
The dashboard, backup, transaction and restore source files match the build 4
source revision; these checks do not silently substitute changed production code.

## Still required before paid release

1. Clean destination Mac: exact quarantined download opened from Finder,
   helper/setup permissions and native VoiceOver/focus behavior observed.
2. Physical two-Mac failure cases: connectivity interruption/reconnect,
   interrupted protected-phase recovery on synthetic data, and selective-skill
   repair with unrelated target state preserved. Local failure injection and
   the passing authentic migration are supporting evidence, not substitutes.
3. Owner purchase-notification delivery, then reviewed release catalog, live
   webhook and checkout activation. Build 4's exact-session refund/revocation
   passed as recorded below. Build 4 has also passed
   the actual sandbox entitlement → email → saved ZIP → quarantined-launch path
   on the current Mac, as recorded below. A replacement build containing the
   diagnostic fix needs its own signed-artifact and delivery checks.

The completed authentic run needs no repeat. The old build-4 continuation
launcher deliberately requires the former failed state and must not be used
for these new checks. No persistent administrator authorization or cross-account
credential copying was introduced. Production checkout remains closed.

## Exact-app sandbox delivery preparation

The delivery catalog now includes `sandbox-build4-arm64`, bound to the exact
signed build above, with `accepted: false` and `testingOnly: true`. It uses a
separate content-addressed `sandbox/` object. Test payments may exercise the
same entitlement and private-download code with actual app bytes. Live
configuration rejects this entry even if acceptance is accidentally flipped;
the sandbox pathname and test-only designation cannot authorize a live release.
The harmless historical delivery fixture remains unchanged and available to
its existing test purchases.

The receipt-bound uploader's explicit `--sandbox` option retains signature
receipt, source, checksum, size, private-access and no-overwrite checks. It does
not edit Vercel settings or enable checkout. Browser transport accepts either
reviewed sandbox artifact, but explicitly does not claim buyer-flow acceptance.
Actual upload, hosted test checkout and fulfillment are separate verification
steps; catalog preparation alone does not prove them.

### Hosted candidate purchase and email acceptance

The sandbox object was uploaded privately and streamed back with all 8,305,798
bytes and the candidate SHA-256 verified. The existing Chrome transport harness
also verified attachment filename, byte count and hash. That harness explicitly
does not claim buyer-flow acceptance.

Protected Preview `dpl_AsWtuy7Ww5QQAM8krMxF4JEfbXMz`, from source
`c614225c31cca7838004980b9e681b2caab91ac7`, selected ordinary Stripe and
`sandbox-build4-arm64`. The existing commerce-sandbox alias was pointed to it;
Production settings were not changed. One invitation, reference
`469afae2-2cf7-4d14-84b3-7db12ee0e54d`, arrived in the owner's Inbox.

The existing checkout completed using Stripe's synthetic test card, synthetic
billing details and the approved owner email. No real money was charged or
payment method saved. The browser identified itself as an AI agent. Session:
`cs_test_a1R36ggecp8gHU0kth0UxqHackp7XNEe64Jv2SOj5fl2uZPnKGddAMOnky`.
The returned buyer page verified the purchase and offered the exact build.
The separate delivery email arrived at 11:42 AM Pacific with the correct release
ID and archive hash. Opening its recovery link independently verified purchase.

However, clicking Download for Mac in this user Chrome session navigated to
`ERR_BLOCKED_BY_CLIENT`. No matching archive was found in Downloads. The block
was not bypassed, no browser protection was disabled, and its cause is not yet
attributed. Successful operator transport does not substitute for this failed
buyer-download observation. Exact-session refund/revocation and owner purchase
notification delivery remain unverified. Public availability still reports false.

The sandbox fulfillment email contained stale fixture-only wording ("No real
purchase or app is delivered"). The next source checkpoint distinguishes a
signed test candidate from the harmless fixture; tracking remains disabled and
sandbox email stays restricted to the approved owner address. Previously sent
mail is unchanged. The Stripe sandbox product description also still contains
fixture-era wording and needs updating before another operator test.

### Primary CTA refinement

At the Founder's request, primary website CTAs use dark purple-blue `#4432b8`
with white text and `#35258e` on hover. Secondary buttons remain outlined; the
white CTA on the purple closing section retains its existing contrast treatment.
Playwright rendered the purchase page at 1440px and 390px using a synthetic
API response (not payment evidence). Both views had no horizontal overflow,
no button underlines and a visible 3px keyboard-focus outline. Screenshots were
inspected. White-text contrast is 8.77:1 normally and 11.62:1 on hover.

Regression checks: 261 Node tests, 260 passed and one explicitly skipped;
all 22 site tests passed. These stylesheet/mail edits do not alter the signed
app candidate. Publication remains a separate recorded step.

The website/mail source checkpoint `bd0a124` was then deployed from a clean Git
archive to `dpl_FD2WzRmZSrJE5GgDaH3JYeyrodpT` and promoted only after the
unpromoted deployment served the expected CTA stylesheet and availability false.
The live `migrate.segeren.com` stylesheet now contains both new color tokens;
its availability endpoint still returns false. Checkout was explicitly disabled
on this deployment. Neither an invitation nor a provisioning/payment action ran
during its build; no new app archive was created and no release was accepted.

The sandbox test's fresh Stripe-email search found no owner payment notification
in the approved mailbox; only an unrelated support response matched. Receipt
delivery is not relabelled as an owner notification. The existing purchase and
emailed recovery pages remain available for continuation; do not pay again to
recover the download.

Disposable sandbox upload input, Preview/website Git exports and local CTA
screenshots were moved to uniquely named `codex-migrate-*20260907*` entries in
the owner's Trash after their processes finished. They are recoverable. The
Shared signed candidate, private stored artifacts and unrelated untracked design
files were preserved. No manual worktree was created.

## Purchase-page refresh regression

The Founder reported that refreshing removed the download button. Source
inspection confirmed that fragment stripping plus memory-only credentials lost
all purchase recovery on reload. This was a real UX bug, separate from the
browser's blocked-download observation.

The page now retains only a verified, bounded-format purchase token in
tab-scoped session storage, reusable for 30 minutes from its initial page visit.
It never stores signed artifact URLs, card details, cookies or local-storage
credentials. Refresh obtains a fresh server-verified download link; saved state
never bypasses current payment/refund/dispute checks. An explicit new fragment
clears prior recovery before validation. Expired/future/malformed records and
rejected purchases are discarded. Blocked storage leaves email-link access usable.
The privacy page describes the storage and browser-session restoration caveat.

All 29 purchase UI tests passed, including nine new cases. A real Chrome fixture
opened a private link, verified fragment removal, reloaded successfully with a
fresh server request, then simulated refund and verified that reload hid the
download and cleared recovery. All 270 Node tests ran: 269 passed, one skipped;
all 22 site tests passed. This fixture is refresh/revocation evidence, not a new
payment or an actual archive download. No signed app code changed.

Source `29e1f78` was deployed to protected Preview
`dpl_2DzEdALzZVMa3VHwbNjh6ahv2h9t` with the same sandbox account, catalog and
existing entitlement. The already-delivered private recovery link was kept in
browser memory and reopened on that corrected deployment; no new purchase,
invitation or email was created. The actual buyer page verified the purchase,
then a real reload again verified it and left Download for Mac visible. The
corrected tab was preserved for the Founder. The existing sandbox alias now
points to this Preview. Historical immutable Preview URLs are not rewritten.

Production `dpl_6QYmdHyV5zqZWMtgeV2CSwEmdhkJ` was promoted after checking
availability false. The live purchase script's SHA-256 matches the tested source
(`b5659dae0f59d414acd33059238bf07c20747807306475e4b732ea58cb12be51`).
Live availability remains false; both deployment builds skipped invitation and
provisioning operations. The temporary Git export was retired to the owner's
Trash as `codex-migrate-refresh-20260907`, recoverable; the local fixture server
and browser were stopped. Buyer file saving and clean-Mac acceptance remain
separate open gates.

## Actual buyer download and quarantined launch

At approximately 13:00 Pacific the existing exact-candidate sandbox purchase
saved through Chrome's native Save dialog to Downloads. No new purchase was
created and no browser protection was disabled. The saved build4 ZIP is
8,305,798 bytes, SHA-256
`bba8b35f55b61389b0b36e65e50f45962975d7944d19293420e11a3f19a19d08`.
It retained Chrome's quarantine attribute. This successful observation supersedes
the earlier unsaved-download gate; it does not attribute the earlier browser error.

Finder/Archive Utility extracted the app. Strict/deep signature verification
passed and Gatekeeper returned accepted, Notarized Developer ID. The first
launch waited behind macOS's normal Internet-download confirmation; a separate
automation activation attempt produced a misleading not-responding dialog.
After dismissing that dialog, the normal prompt explicitly said Apple had
checked the app for malicious software. Open was selected; quarantine was not
removed and Gatekeeper was not bypassed.

The helper then exited because an older local-test engine (PID 25067, browser
port 60809) already owned the default state lock. This was confirmed by the
engine's bounded error output and the open lock descriptor. Its browser showed
unconfigured setup, not a running migration. SIGINT requested graceful shutdown;
the helper's active-operation guard and cleanup path remained in force. The
new failed test launcher was stopped only after it had no helper child.

With the idle helper closed, Launch Services `open -n` started the exact
downloaded app, retaining AppTranslocation and quarantine. This avoided routing
the launch to other old development copies with the same bundle ID. The new
launcher PID 90307 started its packaged engine PID 90327, listening on loopback
port 50105, and automatically opened the guided setup in Chrome. The browser
showed the current connection-card flow, "I'm on the new Mac", and Step 1 of 3.
No connection, transfer or customer-data mutation was initiated. The downloaded
ZIP/app and local setup tab are retained for continuation.

This proves actual sandbox delivery and approved quarantined launch on the
current Mac. It does not prove a clean receiving-Mac Finder launch, desktop
conversation verification, native VoiceOver, or real interrupted recovery.

### Duplicate-instance diagnostic follow-up

The lock correctly prevented concurrent ownership, but the native launcher
reported only that the helper stopped. Source now gives lock contention its own
exception and exit status 75; the launcher explains that an existing copy is
running and how to stop it safely before reopening. Other lock I/O failures do
not masquerade as contention. It never kills the existing helper or bypasses
the lock. The real-process regression verifies that a duplicate exits 75 while
the original remains running and serves its unchanged unconfigured setup.

Swift typechecking and all five state tests passed. Desktop tests: nine run,
eight passed and one filesystem-dependent skip. These source changes are not
inside the signed build4 archive: a new signed/notarized candidate is required
before claiming the diagnostic fix is shipped. Live checkout remains closed.

The complete Python suite subsequently passed: 702 tests, 690 passed and 12
explicit skips, in 181 seconds. Apple/build messages emitted by the suite are
mocked fixture output, not a new signed artifact or notarization submission.

## Build 5 signed candidate

The duplicate-instance fix was packaged from clean, pushed source
`48f5194cd008dddf59b35b1e2c78aff74d46720c` as version 0.1.0 build 5, arm64.
The existing Developer ID identity and Keychain profile were used; no new
credentials or Apple enrollment were required. Actual Apple submission
`b8a32506-0c36-49c3-bdc1-e9ce31550e49` returned **Accepted**. Signature,
stapling, staple validation and Gatekeeper checks passed.

- Archive: `Codex-Migrate-0.1.0-build5-arm64.zip`, 8,305,628 bytes.
- SHA-256: `adc126c92952e0031138b199bc2003c18ee08a6a419f2cfe91ea404b84483be7`.
- Preserved app, archive and nonsecret receipts:
  `/Users/Shared/CodexMigrate-Authentic-20260906/candidate-build5`.
- Exact packaged-engine desktop tests: nine run, eight passed, one
  filesystem-dependent skip. The actual duplicate-launch exit-75/original-helper
  survival regression passed against this binary.
- Independent hash, signature, Gatekeeper and staple verification also passed
  on the Shared copy. Build 4 and its running idle setup were not replaced.

The release task owns sibling worktree
`/Users/jsegeren/Git/codex-migrate-release-build` on pushed branch
`codex/signed-candidate-build5-2026-09-07` for this build only. It is retired
after preserving evidence; no process retained its working directory.
This artifact is not yet in the payment catalog and does not inherit build 4's
buyer-download or physical-Mac acceptance. No live sales setting changed.

Current access rechecks: noninteractive execution as the disposable source
account requires authentication; the current personal account does not have a
trusted host entry for the target account's Mac. No host-verification bypass,
private-key copy or persistent administrator authorization was introduced.

## Exact sandbox purchase refund and owner preference

Stripe sandbox account `acct_1Rkc6nQwGK6ZgBcK` showed the successful $50
candidate payment `pi_3UD7UlQwGK6ZgBcK1PznPGLe`. Its completed Checkout event
identified the previously recorded session
`cs_test_a1R36ggecp8gHU0kth0UxqHackp7XNEe64Jv2SOj5fl2uZPnKGddAMOnky`
and `sandbox-build4-arm64`, confirming the refund target rather than choosing
an unrelated fixture. A full synthetic $50 refund was submitted with an internal
acceptance-test note. Stripe then displayed **Refunded**. No real payment,
customer refund, new checkout or replacement delivery email was created.

The original private link from the 11:42 AM delivery email was reopened in
Chrome. The actual hosted page displayed **This purchase needs review. Please
email Josh for help.** and offered no Download for Mac button. Thus the same
entitlement that delivered the verified ZIP no longer authorizes a fresh
download after refund. The previously downloaded file was not removed; this
test does not claim revocation of files already obtained or immediate expiry of
previously issued short-lived artifact URLs.

The live account `acct_1Rkc6eJfbWpcJIZb` communication-preferences page was
also rechecked through the real Chrome UI. **Successful payment receipt —
Email** was checked (value 1); SMS and Push were disabled/unchecked. This is
configuration evidence, not proof of a new owner email arriving. Stripe's
[account email-notification guidance](https://support.stripe.com/questions/set-up-account-email-notifications)
describes successful-payment notifications. No payment was made merely to
exercise live mail delivery, and the sandbox customer delivery email is not
being substituted for an owner alert. Live checkout remains closed.

## Build 5 exact buyer delivery and downloaded launch

Catalog/test source `367a665e1a656a54f8c936d56b393bf0e7feba40` adds
`sandbox-build5-arm64` without accepting it for live sales. The private uploader
read back all 8,305,628 bytes with the signed build 5 checksum recorded above.
Both build 4 and build 5 sandbox entries remain `testingOnly: true` and
`accepted: false`; regression tests reject turning either into a live release
by changing only its accepted flag. Node checks: 271 run, 270 passed, one skip.

Protected Preview `dpl_8hw3uT9CHpXTRSEGEfWkpfXH2mbD` became Ready at
20:22 UTC and received the existing stable commerce-sandbox alias. Its one
operator invitation used reference `dbe87a53-69ed-40ce-b103-4f7a5ad728a1`;
mail acceptance and actual Inbox arrival were verified. Checkout session
`cs_test_a1UlZOaZAUhOLjiReRU36WaDUsCtPnxZjyTH6Ck622gOMXQQE3Vxj6uraH`
completed using Stripe's synthetic card and invented billing details. No real
card or charge was used. The existing test product description was corrected
to describe delivery of the invited test artifact rather than promising no
software. Price and live product settings were unchanged.

The actual buyer page verified payment and offered build 5. Reloading retained
the download control and verified the entitlement again. The deployment's
webhook request returned HTTP 200. The 13:27 Pacific fulfillment email arrived
in Inbox, described the signed operator-test candidate correctly, and contained
the exact archive checksum. Its private recovery link independently reopened a
verified purchase page offering that same build. Tokens and signed URLs are not
part of this receipt.

Chrome's native Save dialog saved
`/Users/jsegeren/Downloads/Codex-Migrate-0.1.0-build5-arm64.zip`. Its size and
SHA-256 matched the signed archive, and Chrome quarantine remained present.
Archive Utility extracted `Codex Migrate 2.app` alongside the older build,
without overwriting it. Bundle build number was 5; strict/deep signature and
Gatekeeper checks passed (Notarized Developer ID).

The old build 4 helper was verified idle/unconfigured with no active child,
then closed through its guarded SIGINT path. Normal macOS Open confirmation
for the new download explicitly reported Apple's malicious-software check.
After Open, the translocated build 5 launcher (49005) started its packaged
engine (50219), listening only on `127.0.0.1:51550`, and automatically opened
the current connection-card setup in Chrome. No migration or pairing began.

A duplicate-launch probe did not replace the original engine or listener.
Native automation could not select its warning dialog reliably, so the warning's
rendered wording is not certified by this probe. The childless duplicate
launcher (50625) was stopped; the original idle helper remains available.
The packaged real-process exit-75/survival test remains the verified diagnostic
evidence. Downloaded files, Shared candidate and existing test data are retained.

This closes build 5's actual sandbox purchase, fulfillment, recovery-link,
refresh, file-save and current-Mac quarantined-launch checks. It does not close
receiving-Mac launch/VoiceOver, physical interruption/recovery, selective-repair
acceptance, or actual owner-alert arrival. Live checkout stays closed until the
remaining release acceptance is resolved.

### Downloaded build 5 setup and Help checks

The actual downloaded/translocated build 5, still on local port 51550, was
exercised through Chrome's native accessibility and keyboard controls. Switching
to receiving-Mac setup focused its heading. Submitting the harmless invalid text
`not-a-valid-connection-card` via Tab/Return produced **Paste the complete
connection card from your other Mac.** Approval remained available for correction;
no valid card was submitted or connection created. The error container has
`role="alert"` in the pinned source; speech announcement was not tested.

Returning to source setup focused **Your new Mac**. Help opened the diagnostic
section. Preparing a report focused its labelled review text area and displayed
the explicit not-sent/manual-attachment notice and Save control. No report was
saved, uploaded or emailed. Invalid input was cleared. This verifies these
actual packaged setup/error/support controls, not native VoiceOver or a denied
filesystem permission on the receiving Mac.

The Shared authentic result remains terminal at automated acceptance passed /
desktop visual check remaining. Noninteractive execution as the disposable
source account still requires administrator authentication. There is no live
acceptance worker being awaited and no authorization to bypass that account
boundary. Do not rerun the completed build 4 continuation or old diagnostic
launchers to address the remaining tests.
