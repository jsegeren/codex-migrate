# Desktop release readiness

The downloadable paid app is **not released**. Publishing source and the
informational website does not open checkout or certify a customer download.

## Candidate checks completed on the development Mac

- Full Python test suite: 75 tests, including simulated low-space, failed-copy,
  corrupted-backup, rollback, component export, and dashboard boundaries.
- Native Swift shell type-checks on Apple Silicon macOS.
- A self-contained local app bundles the Python engine and offline recovery
  documentation; build receipts identify the source revision and build mode.
- The engine subprocess smoke test can run against the packaged executable with
  only system tools on PATH. It checks startup on a free loopback port, token
  protection, mandatory-backup UI, read-only mutation rejection, and shutdown.
- Website checked at 1280px and 390px widths: upright headline, purple accents,
  separate attributed Codex product reference, $50 one-time planned price,
  no preorders or live checkout, and best-effort support disclosure.
- Launch interest uses an explicit-consent form and a fixed-recipient SendGrid
  endpoint, protected by a production Vercel Firewall rate limit. Ten Node tests
  cover validation, consent, fixed delivery destination, configuration failure,
  and ambiguous provider errors. Early unsigned-build requests remain email-only.
  No automated newsletter or paid download is enabled.

These are local checks, not proof of clean-Mac installation or a complete
cross-Mac migration. Failure tests use disposable fixtures, not user data.

## Remaining paid-release gates

- Confirm Apple Developer membership activation and the intended account.
- Create Developer ID signing credentials and notarization access securely.
- Produce, notarize, staple, and verify the exact committed release artifact.
- Verify quarantined download and first launch on a separate clean Mac without
  developer-installed Python or Xcode.
- Exercise full and skills-only transfers, permissions, different usernames,
  network interruption, restart, and recovery with cross-Mac fixtures.
- Finish native UI/accessibility review against the exact release build.
- Configure and test private purchase support, refund handling, payment, and
  delivery of the exact artifact before enabling checkout.

No unsigned engineering ZIP is advertised or sold as a release. Automatic
route selection, exhaustive discovery, and automatic updating are not claimed
as delivered. See [the desktop setup guide](desktop-setup.md).
