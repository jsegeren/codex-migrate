# Beta access website verification — September 6, 2026

## Scope

The homepage and two migration guides now describe the open-source Beta and
case-by-case $50 packaged Mac beta. A dedicated email request button is separate
from launch-email signup. Early builds are explicitly unsigned and unnotarized;
payment waits until a tested build is ready for the customer's setup. General
self-service checkout remains closed. No payment configuration, API, analytics,
signup implementation, or social image changed.

## Evidence

- At `f649e15`, the full Python suite completed 611 tests: 599 passed and 12
  skipped. The JavaScript suite completed 233 tests: 232 passed and one skipped.
- After the website edits, all 20 site tests and all 12 checkout UI tests passed.
- Playwright inspected the pricing card at 320px and 1280px. Screenshots were
  visually reviewed for readable wrapping, contrast, hierarchy, and button text.
  At 320px, the beta request link received keyboard focus with a visible outline,
  the page had no horizontal overflow, and the checkout panel remained hidden.
- Both guides had no horizontal overflow at 320px and 1280px.
- Local layout checks mocked `/api/availability` to unavailable because the
  static test server does not implement API routes. This is not production API
  evidence or an end-to-end purchase test.
- The commerce build preflight returned `skipped` with no explicit preflight
  environment. It is not recorded as a commerce acceptance pass.

## Production verification

- Published clean tracked source `eb52402a13c450e0fca18fbbefb8df4ef14fa512`
  to the existing Vercel project. Untracked social-image drafts were excluded.
- Deployment: `dpl_GmSEjMqGNTaojhpSgps4vaodXcJx`, status `READY`, aliased to
  `https://migrate.segeren.com`.
- An unmocked browser visit confirmed the Beta availability text, $50 request
  button, hidden checkout panel, and `/api/availability` returning
  `{"available":false}`.
- Both guide routes and `/og-dark-v1.png` returned HTTP 200. The homepage still
  points to that existing social image.
- No customer emails, checkout sessions, charges, or migration operations were
  triggered by this website verification.

## Remaining release evidence

The new authentic cross-Mac runner had not written a status report at the time
of these checks. Genuine signed-in conversation reopening and continuation are
not yet proven. The existing test suites and synthetic migration evidence do
not replace that acceptance run or a clean-Mac test. Apple signing remains
pending, and the existing Stripe support case still had no response.

These focused checks are not a comprehensive WCAG certification or a claim of
release readiness. The unsigned candidate and manual beta delivery gates are
documented separately in `packaged-beta-candidate-2026-09-06.md`.
