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
