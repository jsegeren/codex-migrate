# Sandbox subscription checkout checkpoint

This slice creates a real Stripe **test-mode** subscription checkout for an
already purchased, email-paired native device. It does not activate Production,
publish a customer price, charge a live payment, or certify cloud recovery.
The existing one-time app purchase and appcast are unchanged.

## Ownership and payment evidence

- The native bearer and device ID resolve the account through the existing
  unexpired/unrevoked session and fresh original-purchase verification. The
  request cannot supply account identity, a Checkout Session, email, price,
  allowance, or trial duration.
- A durable account-scoped attempt freezes the server catalog and return site
  before Stripe creation. Concurrent requests share the same attempt and
  Stripe idempotency key. Provider/catalog identity is checked before checkout.
- Lost create or database acknowledgement is retried/reconciled using that
  attempt. After 23 hours an attempt without a saved session refuses automatic
  creation; Stripe may prune idempotency keys after 24 hours. Expired saved
  sessions require support rather than silently starting another subscription.
- Completion retrieves the saved session and its current Stripe subscription.
  Both must have the exact server-owned account/attempt metadata, test mode,
  customer, monthly USD price, quantity and collection state. Pending, canceled,
  unpaid, paused, foreign or changed-price subscriptions grant nothing.
- Recording subscription evidence is idempotent and cannot overwrite another
  subscription or attach the same subscription to two accounts. This record
  is not payment authority: every upload continues its independent fresh
  Stripe and original-purchase checks. No last-good backup pointer is touched.

## Explicit test policy

`HOSTED_SANDBOX_SUBSCRIPTION_OPEN=yes` is required in addition to both sandbox
modes, the pinned sandbox database and named project's protected Preview.
Production/live mode remains refused. The price and allowance come from the
same server catalog settings as the upload runtime; no customer inputs select
them. The sandbox fixture collects a card and has a 30-day test trial. That is
not the final commercial billing, tax, retention or first-included-month
contract, and final prices still require measured all-in costs and approval.

The route has only `begin` and `status`. Re-enrollment after cancellation and
automatic replacement of expired checkouts are deliberately absent until an
explicit reconciliation path proves there is no second subscription. This is
not yet a public billing UI or a complete subscription lifecycle.

### Native test checkout client

The dark `HostedSubscriptionClient` now supplies a native begin/status bridge
to this endpoint. Both actions require explicit mutation consent: status can
record a completed checkout on the server and is not a read-only check. The
existing crypto helper supplies the device bearer; it never enters a browser
result, argument, receipt or error message. Only the named project's protected
Preview origins are supported (plus explicitly selected loopback fixtures).
The public service origin and live subscription results remain refused.

The request contains only the action and device ID. It cannot choose a price,
allowance, account, trial or Checkout Session. Results are exact, bounded,
test-mode shapes; checkout links must point to the test-session checkout path
on `https://checkout.stripe.com`. Redirects, extra/duplicate JSON fields,
unexpected content types/encoding, and provider/native diagnostics are refused
without an automatic retry. A subscribed result is not a backup or protection
receipt. This client neither opens the browser nor completes a payment. Wiring
the customer flow and certifying real Stripe pairing remain separate work.

### Acceptance-only setup integration

The setup flow now accepts an explicit
`CODEX_BACKUP_HOSTED_SUBSCRIPTION_PREVIEW` protected Preview origin, only when
`CODEX_BACKUP_HOSTED_SETUP_ACCEPTANCE=yes` already enables the dark setup UI.
The named-project origin validation still refuses Production and live billing.
After pairing and confirming the separately saved recovery key, the operator
checks test subscription status, explicitly prepares checkout if none is
confirmed, opens Stripe's test checkout, and explicitly checks status again.
No automatic checkout navigation or payment occurs.

Before beginning, the flow checkpoints the original account/device/Vault and
service origin, not the checkout URL or bearer. A lost response, failed local
checkpoint, or restart returns to an unchecked state and requires status before
begin. Server idempotency remains the authority for a pending checkout. Native
credential rotation is resolved under the same update lock as background work;
the original identity remains immutable provenance. A configured flow will not
start an upload or enable its schedule until the test subscription is confirmed;
stopping an existing schedule and inspecting upload state remain available.
Every actual upload still performs fresh server-side authorization.

This is test-mode wiring, not a commercial release or real-service acceptance.
The browser receives only a validated Stripe test checkout link and public
status. It never receives the native bearer, caller-selectable price, account
selector, or stored subscription entitlement. Read-only setup polling does not
perform subscription mutations. The independently saved-key recovery drill,
real test catalog/enrollment, measured pricing and signed release remain gates.
The single-threaded operator-only protected-Preview context includes this
client's opener factory and restores it afterward, without changing encrypted
object transport or copying the operator's Vercel credential into the app.

## Verification boundary

Focused JavaScript tests cover account/catalog refusal, payment status,
idempotence, lost replies, provider failures, route inputs and default-off
configuration. Disposable PostgreSQL tests exercise real migration/functions,
durable attempts, conflict handling and evidence insertion. Fixtures/mocks do
not establish a real Stripe enrollment, cloud backup or recovery result.

At this checkpoint, all 87 SQL files in the CI sequence passed against fresh,
Unix-socket-only disposable PostgreSQL 18. The full JavaScript suite passed
643 tests with one skip; the Preview transport suite passed 11. Independent
reviewer `public_release_review` accepted the exact bounded checkout and
preflight changes as-is after its focused tests, source inspection, syntax and
diff checks. No real service enrollment or customer billing is claimed.

Next: independently review this exact diff, run required CI, apply the reviewed
migration only to the pinned sandbox, and complete real email pairing followed
by the actual test checkout. Then prove publication and separate-Mac recovery,
corruption/interruption safety, unattended scheduling, measured costs, final
billing terms and the exact signed/notarized release before selling hosting.

Primary references: [Stripe Checkout subscription parameters](https://docs.stripe.com/api/checkout/sessions/create),
[free trials](https://docs.stripe.com/payments/checkout/free-trials), and
[idempotent requests](https://docs.stripe.com/api/idempotent_requests).

Owner: the primary Codex Backup implementation task. Its reused sibling
worktree is retained for this active slice, with retirement due October 4, 2026.
Source checkpoints must be pushed before handoff; credentials and test keys
remain outside Git.
