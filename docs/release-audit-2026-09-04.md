# Release audit — September 4, 2026

## Outcome

The informational website and open-source alpha are public. The paid desktop
app is **not release-ready**. Passing automated tests or Lighthouse is not a
guarantee of migration safety, accessibility conformance, or clean-Mac support.

This was a focused readiness audit, not an exhaustive security assessment.
No real user migration, remote installation, payment, or signing operation ran.

## Evidence

- Baseline: commit `5b73b698126d709bcdafe486ce9607e12534f6f3`.
- Baseline Python suite: 79 passing tests, including disposable local APFS
  backup/install/rollback fixtures and real dashboard subprocess checks.
- Website update candidate: 82 passing Python tests after adding screenshot,
  transfer-method, and Windows FAQ regression checks.
- Signup endpoint: 10 passing Node tests. Live inbox delivery was verified in
  the earlier launch check; this audit did not send another signup email.
- Native Swift shell: `xcrun swiftc -typecheck -parse-as-library` passed.
- Baseline GitHub CI succeeded for the deployed commit.
- Six public pages return HTTP 200, have one H1, and do not overflow at 320px.
  Visible HTML text measured at least 14px. Homepage and guide canonicals are
  correct. The three legal pages lack explicit canonicals.
- Tab navigation had visible focus outlines; FAQ expansion works with Enter;
  invalid email input is rejected by browser validation. These are focused
  checks, not full keyboard or screen-reader certification.

### Lighthouse 13.4.1, production baseline

Measured September 4, 2026 at approximately 07:42 UTC. Single lab runs, not
field Core Web Vitals. These measurements precede the new lazy-loaded UI
screenshots and FAQ additions.

| Category | Mobile | Desktop |
| --- | ---: | ---: |
| Performance | 88 | 100 |
| Accessibility | 100 | 100 |
| Best practices | 100 | 100 |
| SEO | 100 | 100 |

Mobile LCP was 3.9 seconds; desktop LCP was 0.7 seconds. CLS was zero.
The unmodified 630 KB product-reference PNG is oversized for its display size;
Lighthouse estimates roughly 600 KB of avoidable image transfer. Optimize
delivery without changing the artwork or confusing it with our own branding.

### Accessibility is not finished

- axe-core 4.13.0 found no automatic violations across all six pages using
  WCAG 2 A/AA, 2.1 A/AA, and 2.2 A/AA rule tags at narrow width.
- axe requested manual review of `aria-label` on the generic
  `.product-reference` div. Give it appropriate semantics or remove the label.
- Lighthouse's experimental, unweighted label-in-name audit flagged the home
  brand link: the visible decorative `CM` mark is hidden from the accessibility
  tree. Review with assistive technology rather than treating the score as
  proof that the flag is harmless or a confirmed conformance failure.
- A 200% text-only enlargement stress test caused horizontal overflow in the
  closing CTA at 1280px. Its fixed non-shrinking action group needs correction.
- VoiceOver, broader keyboard flows, text-spacing overrides, and native-app
  accessibility still need testing. Do not publish a WCAG-conformance claim.

## Search and helpful content

Two informative guides are live and linked from the homepage:

- `/moving-to-a-new-mac`: selection scope, identity preservation, SSH setup,
  interruption, different usernames, and verification before retiring a Mac.
- `/backup-and-recovery`: free space, verified backups, recovery paths, and
  limits of same-disk protection.

`robots.txt` and `sitemap.xml` return HTTP 200 and advertise the canonical site.
The sitemap includes the homepage, both guides, and three legal pages. The
Search Console property list in the inspected account did not contain this
site or its parent domain. Registration, ownership verification, sitemap
submission, and URL inspection remain pending. No indexing is claimed.

## Pre-signing app work

Independent read-only review: `public_release_review`.

1. **Operation-specific safe cancellation.** Inspection/export sets `running`,
   disables controls and prevents Quit, but the close control requires a
   dashboard URL those commands never create. Quit instructions point to a
   nonexistent dashboard. Avoid unsafe termination during replacement.
2. **Restore migration configuration after relaunch.** The native form resets
   but the state directory depends on its values. Add an owner-only saved
   configuration/recent-migration flow, without storing credentials.
3. **Contextual accessible labels.** Repeated workspace `Remove` buttons need
   their folder in the accessible name; verify with VoiceOver and keyboard.
4. **Offline recovery access.** Guides are bundled, but visible help links open
   GitHub. Expose the bundled documents from the app.
5. **Clean-Mac matrix.** Verify the entire packaged runtime on the minimum
   advertised macOS version; Swift's target alone does not prove Python/runtime
   compatibility. Exercise full/skills-only migration, interruption/reboot,
   different usernames, low space, permissions, and rollback on disposable Macs.
6. **Purchase readiness.** Test payment, delivery of the exact artifact,
   private support, and refunds before opening checkout.

These can advance before Developer membership activation. The build script
already supports Developer ID signing, hardened runtime/timestamps,
notarytool submission, stapling, Gatekeeper assessment, checksums, and source
receipts. That path still needs a successful real signed release run.

At audit time this Mac had zero valid code-signing identities. Once Apple
access is resolved, produce and test the exact signed/notarized artifact;
activation alone does not satisfy the other release gates.

## Web-first direction

Founder direction: local data, browser-based experience, Mac-only initially.

- Keep the existing local migration engine authoritative.
- Move guided setup, scope selection, status, resume and recovery into the
  local browser experience; retain a small signed launcher/helper.
- Preserve loopback binding, token checks, explicit mutation confirmation,
  native folder permissions and SSH host verification. No public unauthenticated
  endpoint controlling a Mac and no workspace upload to our servers.
- Current delivery remains native setup plus a browser dashboard. The unified
  browser setup flow is planned, not implemented by this website update.
- A Windows version requires platform-specific implementation and validation;
  neither Windows nor cross-platform migration is currently supported.

## Screenshot provenance

New homepage/backup-guide screenshots use the current dashboard HTML directly
from `src/codex_migrate/dashboard.py`, rendered in a real browser with disposable
sample states. The fixture has no migration engine or SSH and rejects POSTs.
They are labeled as sample data, not evidence of a live 184 GB transfer or
clean-Mac certification. No customer paths, credentials or conversations appear.

## Follow-up implementation — September 4

Implemented after the baseline audit; this does not change the overall
**not release-ready** outcome:

- Inspection and skills-export controls now request cooperative cancellation.
  Skills backup/replacement defers cancellation through verification, receipt
  output, and lock release. Shutdown messages do not assert an unverified
  pre-replacement state. Force Quit and power loss are not covered by this
  cooperative guarantee.
- Transport abort cleanup terminates and reaps the local process group with
  bounded pipe draining, including when its leader has already exited.
- The native shell restores the last launched non-secret setup from an
  owner-only atomic local file. Changes reset to disabled; SSH key selection
  and dashboard tokens are not persisted. Multiple saved migrations and the
  browser-first setup flow remain outstanding.
- Workspace Remove controls have contextual accessibility labels. Bundled
  setup, recovery, and security guides have offline entry points.
- Closing CTA and narrow header wrapping were corrected. Homepage text-only
  200% stress checks at 1280, 390, and 320 CSS pixels have no page overflow.
  The offscreen, clipped honeypot is intentionally excluded from visible-layout
  interpretation. Normal mobile rendering was also inspected.
- Legal-page canonicals were added; unnecessary homepage ARIA labels removed.
- Verification: 95 Python tests, 10 signup tests, and native Swift typechecking
  passed. Tests include actual subprocess signal cleanup, exited-leader pipe
  cleanup, late-stop receipt reporting, and compiled Swift persistence checks
  for permissions, corruption, symlinks, and replacement.
- Independent review by `public_release_review` found the exited-leader cleanup
  and late-stop reporting bugs; both received fixes and regression tests.
  Native rendered/VoiceOver checks remain unverified because native UI access
  failed. A local unsigned engineering build succeeded, but it predates the
  final transport corrections and is not a release artifact.
- The independent reviewer also verified normal and enlarged-text website
  rendering at all three widths. A stop/exit race finding was fixed using the
  known process-group ID and an already-exited guard, with a regression test.

Still open: full browser-first setup/recovery, icon delivery performance,
comprehensive accessibility checks, real clean-Mac/cross-Mac recovery tests,
signing/notarization, Search Console verification/submission, and tested paid
purchase/delivery/refund flow. The baseline Lighthouse results above have not
been represented as measurements of these changes.

## Browser-first follow-up

- `launch` and the native **Open browser setup** button now open real local
  setup. Destination/folder selection, explicit per-session change permission,
  private saved setup, and navigation to the existing migration dashboard are
  implemented. No destination connection or transfer runs during configuration.
- Browser refresh retains the tab-scoped control token. Setup APIs require the
  loopback Host, a matching Origin when supplied, and the control token.
- Inspection is asynchronous and has cancellation checkpoints during local
  scans; Stop remains responsive. Setup/action requests are serialized against
  normal shutdown. Stale setup tabs cannot open a picker after attachment.
- Independent review found and prompted fixes for synchronous inspection
  blocking Stop, restored-root ordering invalidating staging credit, and stale
  picker requests blocking actions. Regression tests cover each case.
- Current local suite: 113 Python tests passed; Swift shell typechecking passed.
  Real HTTP fixtures cover token/origin rejection, path validation, planning
  guards, state reuse, secret-field exclusion, stop responsiveness, and shutdown
  serialization. A browser fixture with SSH disabled passed setup → dashboard
  → refresh; Start remained disabled. Setup rendering had no page overflow at
  1280/390/320px and axe-core found zero violations in the selected WCAG A/AA tags.
- Independent rendered review at 1280/320px confirmed readable controls and
  recovery limitations. Its key-copy wording finding was corrected: selecting
  an SSH key does not add it to scope, but workspace-contained keys are included.
- CI exposed a Darwin process-exit signalling race after the prior follow-up.
  The correction in `4a476e8` passed both Python 3.9 and 3.12 CI. This is not a
  claim that the new browser candidate has already passed hosted CI.

Remaining browser work: integrated skills-only exports, richer saved migration
selection/import, and complete recovery/accessibility checks. Existing native
and CLI migrations must resume using their original state/entry point; the new
browser flow does not import them or adopt their staging. Native folder-picker
permissions, VoiceOver, and clean-Mac/cross-Mac behavior remain unverified.
The overall project remains **not release-ready**.

The previously identified full-flow personal-skill coverage gap is addressed
in the follow-up below. This does not close the other release gates.

### Full-migration personal skills

- Full inspection now discovers current and legacy personal custom skills,
  includes materialized sizes in incoming-space estimates, and lists their
  individual destination paths. Current-location skills win same-name ties.
  Ordinary root metadata and `.system` are excluded from the personal pass;
  invalid skill directories and broken aliases stop inspection rather than
  silently disappear. The full `.codex` copy remains otherwise unchanged.
- Skills share the full staging/backup/install/rollback transaction. Existing
  destination skill aliases are backed up as links without following them;
  unrelated destination skills remain intact. Personal skills receive frozen
  SHA-256 regular-file and exact directory-tree verification before backup and
  after installation. No file contents or checksum values are logged.
- Skills cannot silently expand the confirmed replacement scope after staging
  or restart. Changed scope or older staging without a scope record requires
  Resume, review, and a fresh Finalize confirmation.
- Real disposable local rsync/APFS fixtures cover different home names,
  materialized file links, current-versus-legacy precedence, destination backup,
  corrupted staging, installed corruption with rollback, and destination aliases.
  Additional tests cover scope collisions, metadata, unsupported names, broken
  aliases, protected credential references (including relocated SSH roots), and
  unexpected special files. No real workspace or remote Mac was transferred.
- Independent reviewer `public_release_review` found and prompted fixes for
  silent omission, relocated protected paths, special-file validation, and
  confirmation-scope expansion. A corruption fixture exposed zsh ERR_EXIT
  inside a verifier function bypassing the caller's EXIT trap; explicit
  function returns and top-level exits now trigger rollback, with regression
  proof. Review outcome: accepted with fixes, no remaining blocking finding
  within this bounded change. Independent focused suite: 61 tests passed.
- Actual dashboard fixture at 1280/390/320px showed skill counts, destinations,
  and selected-versus-verified status with no page overflow. Axe-core 4.13 found
  zero selected WCAG A/AA tag violations at 320px; independent desktop/320px
  visual review passed. This is not VoiceOver or full WCAG certification.
- Full local regression suite: 129 Python tests passed; all 10 signup tests
  passed. Hosted CI and packaged validation of this candidate remain separate
  checks; no prior build is being represented as containing this code.

Still open: browser selective-export controls, broader inventory/recovery
coverage, clean-Mac and real cross-Mac acceptance, complete accessibility
testing, Search Console submission, signing/notarization, and paid distribution.
The prior packaged-helper check below predates these changes; it is not evidence
that the new skills code has been validated in a packaged release.

### Packaged browser-helper check

An unsigned Apple Silicon engineering build from clean source
`e6ba09f3309b212e861fd5e8fa5085ee52460e43` passed six desktop checks against
its actual bundled engine. Both `launch` and `serve` started private local
servers and shut down normally under disposable test homes. Engine subprocesses
used only the system PATH with Python/DYLD overrides removed. No destination SSH
or migration ran. This verifies packaging inclusion and startup on the build
Mac, not clean-Mac, minimum-macOS, native-picker, signing, or Gatekeeper support.

Artifact: `Codex-Migrate-arm64-LOCAL-UNSIGNED.zip` (engineering only).
SHA-256: `341e5e74585ecc1e03aca955bd5cc0a52cfeb89a8c56ac99a7afb549e1950d8f`.

### Reference guidance

- [Lighthouse scoring excludes manual checks](https://developer.chrome.com/docs/lighthouse/accessibility/scoring).
- [Submitting a sitemap does not guarantee crawling or indexing](https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap).
- [Apple Developer ID notarization and distribution](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution).
