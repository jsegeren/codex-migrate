# September 7 final-release validation checkpoint

Candidate: version 0.1.0 build 4, arm64, source
`8d14dbf1877d1fc71a509d6eab86b18ec4014b52`, archive SHA-256
`bba8b35f55b61389b0b36e65e50f45962975d7944d19293420e11a3f19a19d08`.
Harness/documentation branch checkpoint before this run: `28d5248`.
No candidate code, public deployment, payment settings or personal workspace
was changed by this validation. This is not release approval.

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
3. Exact accepted app through the buyer entitlement/email/download path, owner
   purchase notification, then reviewed release catalog, live webhook and
   checkout activation. The existing test-money fixture flow and direct exact
   archive transport already pass, but their combination has not been exercised.

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
