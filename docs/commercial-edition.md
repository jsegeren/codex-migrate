# Commercial edition principles

The open-source migration engine is the trust foundation. The paid Mac app
charges a one-time price for convenience and support, not for access to a
user's own data or recovery from an artificial lock.

## Paid direction (not all implemented)

The current desktop shell provides folder selection, setup guidance, the local
dashboard, skills-only export, and trusted multi-route benchmarking. Broader
automatic discovery and update checks below are planned, not shipped. Release
readiness is tracked in [the desktop guide](desktop-setup.md).

- Signed and notarized native macOS application
- Automatic Mac and Codex discovery
- Guided Remote Login and permission setup
- Wi-Fi/direct-link route testing and fastest-route selection
- Visual inventory and storage planning
- Component selection and small targeted repairs without repeating a full copy
- One-click pause, resume, safe stop, finalization, and rollback guidance
- Automatic update checks
- Human-readable verification report
- Maintainer support

## Founding Edition

The downloadable Mac beta costs **$50 one time**, including best-effort
maintainer support and a 30-day refund policy. No subscription or pre-order.

On September 7 the Founder explicitly authorized opening self-service paid beta
downloads while the remaining acceptance checks continue. This supersedes the
earlier manual-only beta policy below. The approved artifact is signed and
notarized build 5 for Apple silicon, not an unsigned early build. Native
accessibility, permissions and physical network-interruption checks remain
unfinished and are disclosed before payment. See the
[paid-beta launch record](paid-beta-launch-2026-09-07.md) for exact scope.

### Historical policy: paid beta by request (superseded September 7)

The Founder approved a separate **$50 paid beta with manual delivery**, without
waiting for Apple Developer activation. This is not an instruction to open the
general checkout or weaken its signed-artifact checks.

Before accepting a beta payment:

- Complete and review the authentic cross-Mac migration and recovery acceptance
  for the exact candidate. Record remaining limitations honestly; a beta label
  is not a passing test result.
- Confirm the buyer's setup fits the tested scope and provide the price,
  unsigned/unnotarized status, best-effort support and 30-day refund policy
  before payment. Do not imply Apple endorsement or a signed release.
- Explain that finalization replaces selected destination data after backup,
  rather than merging independent work. Require keeping the old Mac and an
  independent backup during beta use.
- Freeze the exact tested build and verify its checksum and delivery. Record
  the purchase and delivered version privately, using the existing Stripe
  account once its applicable seller/product setup is confirmed.

The beta is an actual deliverable, not a pre-order for a future signed app.
Do not collect a payment while its tested build or delivery is unavailable.
Do not promise a launch date or guaranteed fix. Standard signing/notarization
and clean-Mac acceptance remain required for the later general release.

Under that earlier policy, the signed Mac app was not publicly downloadable;
early unsigned/unnotarized Mac builds may be requested from Josh and are handled
case by case. Beta does not mean release acceptance is complete. Keep the source
Mac and an independent backup; finalization replaces selected destination data,
not merges independently active workspaces. Do not send credentials or workspace
contents when requesting access.

The full open-source CLI is available today. The paid refund window
is 30 days from purchase. Current release status and policies are published at
<https://migrate.segeren.com>.

## Support promise

We make a best-effort attempt to investigate and resolve reported issues. We
aim to respond within a few business days, depending on availability, issue
complexity, and the information provided. Requests are handled case by case.
This is a response target, not a guaranteed service level or a promise to fix an
issue within that time. We cannot guarantee a solution to every issue, recovery
of every workspace, or compatibility with every configuration. Statutory rights
and the refund policy remain unaffected.

## Non-negotiables

- No telemetry by default
- No sale of user data
- No hosted copy of private conversations or repositories
- No weaker safety behavior in the free CLI
- No fake countdowns, forced subscriptions, or recovery ransom
- Clear unofficial/OpenAI non-affiliation language
