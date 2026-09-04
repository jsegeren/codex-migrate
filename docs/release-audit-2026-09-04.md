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

## Reference guidance

- [Lighthouse scoring excludes manual checks](https://developer.chrome.com/docs/lighthouse/accessibility/scoring).
- [Submitting a sitemap does not guarantee crawling or indexing](https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap).
- [Apple Developer ID notarization and distribution](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution).
