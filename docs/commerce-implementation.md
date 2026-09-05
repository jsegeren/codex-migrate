# Purchase and delivery implementation — September 5, 2026

Status: implementation and private-storage transport tested; **not a live checkout release**.
The committed release catalog contains only a harmless sandbox delivery fixture; no commerce environment variables
or webhooks have been installed in Production. No app archive was published.

## Boundaries

- The existing Stripe account remains the payment provider. No You.one
  products, prices, settings, customers, keys or databases were modified.
- The separate `codex-migrate-commerce` Neon project was created through the
  existing Vercel integration. Its `commerce-sandbox` branch contains the
  tested schema and clearly synthetic purchase records. The main branch has
  no purchase schema or customer records. No new vendor account was created.
- Both computes and new-compute defaults are capped at 0.25 CU with 300-second
  idle suspension, on the existing usage-priced Launch installation. Database
  storage and active compute incur that plan's normal charges; this is not a
  claim of a free database. Retained history is one day.
- Purchase state contains the Stripe session/payment reference, buyer email,
  release ID, timestamp, and delivery state. No card details, migration data,
  Codex credentials or analytics identity is stored there. Launch-email
  consent and the existing maintainer-mailbox intake stay separate.
- Official Stripe SDK signature validation uses raw request bytes, a five-minute
  signature tolerance and the exact endpoint secret. Unrelated product events
  are acknowledged without fulfillment. Payment authority comes from a fresh
  account/session/line-item/charge read, not the event payload or success URL.
- Exactly one one-time $50 USD line item, the configured product/price and
  release, paid/complete status, Managed Payments, matching environment and
  successful charge are required. Discounts, mixed carts, refunds (including
  partial refunds), disputes and unverifiable fields stop delivery/access.

## Recovery and email semantics

The database's unique session key and conditional delivery claim handle
concurrent/replayed events. A purchase record is durable before sending mail.
Stripe retries failed webhook deliveries; the operator can use
`node ops/commerce-deliveries.js` for aggregate delivery-state counts, or
`--retry-pending` to retry at most ten explicitly pending deliveries.

SendGrid 202 means accepted by the provider, not inbox delivery. Explicit 4xx
rejections return to pending, with a five-attempt limit. A timeout/5xx is
`uncertain`; a process crash while sending leaves `sending`. Neither is
automatically reclaimed: the mail provider and database cannot provide one
atomic transaction, so promising exactly-once email would be false. Review
these states in private provider dashboards before deciding to resend. A
database failure after provider acceptance can also leave an uncertain send.
Purchase access remains independent of email delivery.

Private recovery-link credentials live in URL fragments, are removed from the
current history entry, and travel to the API in POST bodies. This page loads
no analytics. HMAC credentials are environment-bound and must be kept private;
preserve the link secret across deployments. Rotating it invalidates old links
and needs a deliberate recovery plan. Every download request rechecks payment,
refund and dispute state. A later release does not silently retarget an older
purchase's artifact. Emails are transactional only, with click/open tracking off.
An already issued file link remains usable for up to five minutes; a refund
prevents new links but cannot retract a completed download or immediately revoke
that short window. This is paid official distribution, not DRM.

## Configuration and release gates

Node 24 is pinned for the website's commerce functions; the Python migration
engine remains dependency-free. Dependencies are pinned in `package-lock.json`.

Private server-only variables:

- `COMMERCE_MODE`: `sandbox` or `live`; absence keeps commerce closed.
- `COMMERCE_STRIPE_KEY`, `COMMERCE_STRIPE_ACCOUNT`, `COMMERCE_PRODUCT`,
  `COMMERCE_PRICE`, `COMMERCE_WEBHOOK_SECRET`: explicitly scoped Stripe setup.
- `COMMERCE_DATABASE_URL`: this product's database and matching environment.
- `COMMERCE_LINK_SECRET`: persistent random 32-byte secret encoded as hex.
- `COMMERCE_RELEASE`: a reviewed entry in `commerce/releases.json`.
- `COMMERCE_BLOB_STORE_ID`: exact private store ID without the `store_` prefix.
  Hosted SDK authentication uses the connected project's OIDC identity. An
  explicitly scoped `COMMERCE_BLOB_READ_WRITE_TOKEN` can be supplied for operator
  use; never expose it or a signing key to the browser.
- `COMMERCE_CHECKOUT_OPEN=yes`: a separate checkout-opening gate.
- `COMMERCE_SANDBOX_OPERATOR_TOKEN`: random 32-byte hex token, required in the
  Authorization header to create sandbox checkouts through the endpoint.
- `COMMERCE_SANDBOX_EMAIL`: the maintainer-controlled delivery sink; sandbox
  mail to any other address is rejected.
- Existing `SENDGRID_API_KEY` and `LAUNCH_FROM_EMAIL` provide transactional mail.

The API needs Accounts, Products, Prices, Payment Intents and Charges read
access plus Checkout Sessions write access. The Founder approved the two
additional read scopes. After Stripe's identity checkpoint, September 5 API
readback returned HTTP 200 for both Payment Intents and Charges using the
existing sandbox restricted key. No live key or write scope was added.

Sandbox Vercel previews use their own platform-provided `VERCEL_URL` for return
URLs, delivery links and exact request-origin checks. The hostname must match
this project's deployment prefix and existing team suffix; missing or malformed
preview identity fails closed. Request headers never select the link origin.
Live mode and Production remain pinned to `https://migrate.segeren.com`.
The public purchase CTA remains hidden in sandbox mode and operator authorization
is still mandatory. This enables isolated hosted testing without redirecting a
test buyer into the unconfigured Production purchase route.

Use the direct database URL as `COMMERCE_DATABASE_URL_UNPOOLED` and set
`COMMERCE_MIGRATION_CONFIRM=codex-migrate-commerce` with the matching mode to run
`node ops/commerce-migrate.js`. This operator-only command is pinned to this
project's two known hosts. Never run migrations automatically on requests.
The Drizzle migration was applied and tested only on the sandbox branch.

The Founder selected purchase-only official Mac downloads, including best-effort
support and an aim to reply promptly. Source and CLI remain MIT-licensed. The
public GitHub artifact adapter has been replaced by private Vercel Blob delivery.
The catalog has no live app entries. Each reviewed entry binds `id`, `kind`,
`source`, `sha256`, `filename`, `size` and the exact content-addressed
`sandbox/<sha256>/<filename>` or `live/<sha256>/<filename>` pathname. Live also
requires `accepted: true`. Archives are capped at 100 MiB in this first release;
the current unsigned app candidate is approximately 8 MiB.

Every request freshly verifies the purchase, checks storage metadata against
the catalog, and issues GET-only access to that exact file for at most five
minutes. Neither the storage token nor delegation signing key reaches the
browser. The native browser downloader receives the short-lived URL; pressing
Download again obtains fresh authorization. Signed URLs are sensitive during
their lifetime and must not be logged or sent to analytics. No file bytes pass
through the website's function response limit.

The dedicated private store is `store_Ksz4f7gOIH2qRu9I` (`codex-migrate-downloads`,
iad1), connected only to this project's Development environment. The CLI created
an ignored `.env.local`, restricted to mode 600. Production is not connected.
No app has been uploaded. One retained 8 MiB synthetic transport object lives at
`sandbox/79f06f97f57af33fad064057855fadd5c276c4adeb75d778f2e26e29a2da96fd/transport-fixture.zip`;
it is not an app or a ZIP-format acceptance fixture. Store usage incurs normal
Vercel Blob charges. The operator-only `ops/commerce-storage-check.js` requires
`COMMERCE_STORAGE_TEST=yes`, creates a new synthetic object per run and prints
only bounded result metadata, never credentials or signed URLs.

Before registering any live entry, upload without overwriting, independently
download and verify its bytes, and retain signing/notarization, clean-source,
and actual clean-Mac acceptance evidence for that exact archive. The operator
upload procedure below binds the build receipt to uploaded bytes. A manifest
boolean does not substitute for signing or clean-Mac evidence.

Before activation: execute the app-upload workflow against an actual signed build,
run a real sandbox Managed Payments payment/refund
through these routes and the controlled inbox, recheck the published edge rate
limits below, and verify the real hosted raw-body
signature boundary. Then finish live Managed Payments eligibility/terms,
Apple signing and clean-Mac migration acceptance. No live checkout should be
opened to bypass any of these checks.

## Evidence

- Hosted Preview `dpl_Cd4uzyk2QviBTmyxMEns7H5aSLtQ` reached READY.
  Anonymous access remained protected; availability returned false, checkout
  without operator authorization returned 403, and an unsigned webhook returned
  400. An authorized hosted request created the actual sandbox Checkout session
  `cs_test_a1VEO6YspZqRxlWr3dcOfcFRd8Uty3hBnDW9japlcbAc1cTgncj9kZGKJn`.
  Browser submission with Stripe's synthetic test card completed at $50 USD,
  with `livemode: false` and Managed Payments enabled. No real money moved.
  The database recorded one purchase and one provider-accepted mail attempt;
  the recipient mailbox subsequently showed that exact test message in Spam.
  Provider acceptance is therefore verified, but inbox deliverability still
  needs work. The same sandbox payment was subsequently refunded in full;
  fresh Stripe readback confirmed `livemode: false`, `refunded: true` and
  `amount_refunded: 5000`. Hosted status and download requests, including a
  previously valid recovery credential, both returned 403
  `purchase_requires_support` without a new file URL. This tests the actual
  hosted refund boundary, not a live refund or a signed app.
- That real browser test found purchase fetches omitted the hosting-auth cookie,
  causing protected Preview requests to fail while authenticated API checks
  passed. Purchase, checkout and availability fetches now retain same-origin
  credentials. Payment authority still uses explicit bearer credentials and
  fresh Stripe verification; cookies do not authorize a purchase. Regression
  assertions cover each request. Corrected Preview
  `dpl_3q9NMXFwJyvowAwPjTEFFHXse286` passed browser retesting: the same paid
  session showed “Your purchase is verified” and enabled Download for Mac.
  The existing sandbox webhook alias now targets that Preview.
- The explicit support Reply-To correction is deployed on guarded Preview
  `dpl_8HXvmn6XSbqA3rjPdZq7hzB5of5y`, and the stable sandbox alias points to it.
  The exact deployed source revision passed CI and 184 Node tests, with the one
  real-database test intentionally skipped in the default suite. Hosted
  availability still returns `false`. A second hosted simulated payment reached
  this deployment: Vercel recorded 200 for checkout, the signed Stripe webhook,
  purchase status and download authorization, while the isolated database
  recorded its maintainer-address delivery as `sent` after one attempt.
  SendGrid's activity log recorded Google's `250 2.0.0 OK` response and
  `Delivered` in under one minute. Gmail has not surfaced that message, so
  inbox placement and the deployed Reply-To header remain unproved.
- The real paid session's hosted status and download APIs both returned 200.
  Independent retrieval of the authorized private file returned 200, 451 bytes,
  a matching archive SHA-256 and an attachment response. The Chrome buyer-button
  path instead reached `ERR_BLOCKED_BY_CLIENT`; no browser-downloaded file was
  found. Do not count that as a successful browser download or disable browser
  security protections to obtain a passing result. The second hosted purchase
  reproduced the same client block. Pausing AdBlock on only the private blob
  host and reloading did not change it, and AdBlock was restored immediately;
  this rules out that extension but does not identify the blocking client.
  The purchase page no longer starts the cross-origin attachment with an
  asynchronous `location.assign`, which can lose the initiating user gesture.
  After server verification it now binds the exact validated five-minute URL to
  a real Download for Mac link; the buyer's subsequent trusted click directly
  requests the attachment. Missing links trigger regeneration instead of a
  false download claim. All 185 website tests pass. Real Chromium at 1280px and
  320px accepted a harmless mocked attachment from that link, recorded a file
  download, retained useful focus and had no horizontal overflow. This proves
  the user-gesture correction and rendered behavior, not the hosted private
  Blob or paid session. Repeat the actual hosted browser acceptance before
  release. Exact commit `793e237` is deployed on guarded Preview
  `dpl_Ny7QyfH8W2x5vTXLB6Z5weC4cQR6`; the stable sandbox alias points to it,
  serves the new link implementation, and continues to report availability
  `false`.
- September 5 sandbox setup: created endpoint `we_1UCK0vQwGK6ZgBcKbA8f3rXL`
  in `acct_1Rkc6nQwGK6ZgBcK` for `checkout.session.completed` and
  `checkout.session.async_payment_succeeded`. The endpoint targets this
  project's stable sandbox alias with private Vercel deployment-protection
  bypass authentication. Its signing secret and commerce configuration are
  sensitive Preview-only variables. Production commerce remains unconfigured.
- Existing `SENDGRID_API_KEY` and `LAUNCH_FROM_EMAIL` values were preserved,
  with Preview added to their Production scope. `LAUNCH_NOTIFY_EMAIL` remains
  Production-only. Sandbox transactional delivery is restricted to the
  maintainer-controlled inbox; no launch-subscriber list was copied.
- Sandbox fixture `sandbox-delivery-2026-09-05` is a valid 451-byte ZIP containing
  only the committed `tests/fixtures/commerce-download/README.txt`. Its private
  upload was independently downloaded and matched SHA-256
  `1a9d8e5775804a42e03655c7653d4d5315fca718445a2aecff144f00faf53343`.
  This proves fixture storage, not payment, inbox delivery or app acceptance.
- 184 Node tests passed; the real-database test is skipped in the default suite.
- Sandbox checkout now rejects missing/malformed/incorrect operator tokens before
  any runtime, database or provider access. Request IDs must be strings rather
  than values coercible to UUIDs. Direct handler tests cover authorization order,
  the exact one-time line item, Managed Payments, retry idempotency, live/sandbox
  separation, wrong accounts/prices/products, and unverified redirect rejection.
- The purchase CTA now reads a no-store availability endpoint that stays closed
  for missing configuration, sandbox mode, or an unreviewed release. Only an
  explicitly enabled live release displays hardware compatibility and the $50
  checkout button. No checkout session starts until the buyer clicks. Retries
  reuse a per-tab request reference; delayed readiness preserves a focused or
  filled email-signup form. A privacy disclosure explains this local state.
  Chromium desktop/320px checks with mocked readiness/payment responses verified
  the hidden prelaunch fallback, visible purchase state, retry keyboard focus,
  17px button text without underlining, and no narrow-screen horizontal overflow.
  These are UI checks, not a completed hosted purchase or live release.
  Preview deployment `dpl_BB1e3pSjRGu16BnSnfpYdU4V5MWq` from `9b03dcc` reached
  READY: availability returned HTTP 200 with `available: false`, and checkout
  returned HTTP 503 with `checkout_closed`. Production was not promoted.
- Full Python regression run: 586 tests completed, 579 passed and seven explicit
  filesystem skips, in 141.061 seconds. Mock notarization output in that suite
  is not an actual signed release.
- The explicitly enabled real sandbox database test passed separately on
  Node 26.7.0: concurrent insert/claim, one accepted send, conflict rejection,
  and uncertain-send no-retry behavior. It retains two synthetic rows per run.
- 19 website tests passed. Browser success/error checks used explicit mocked
  payment responses, not claims of real paid transactions or downloaded apps.
- Desktop 1280px and narrow 320px browser checks cover readable layout, no
  horizontal overflow, fragment removal, closed-checkout error/help, and
  success controls. Optional checksum disclosure reduces visible text. These
  are not full WCAG or VoiceOver certification.
- Apple account refresh still reports the intended account as Pending; local
  signing-identity inspection found zero valid identities.
- Real private-storage check: 8,388,608 bytes downloaded and SHA-256 matched;
  anonymous access denied, altered pathname denied, expired signed link denied,
  and the provider served an attachment response. This does not prove payment,
  hosted webhook behavior, inbox delivery, app launch, or migration acceptance.
- Purchase-page browser success checks at 1280px and 320px use explicit mocked
  payment responses. Eight shipped-script tests cover manual activation,
  duplicate-click suppression, retry focus, preserving user-moved focus,
  browser-clock independence, and rejection of public/malformed destinations.
  Real Chromium keyboard activation of a failing download left focus on Check
  again; the 320px error screen had no horizontal overflow and a 17px button.

## Published edge request limits

### Transactional sender follow-up

Gmail's September 5 details for the actual test message showed
`joshua@shopcierge.ai` as sender, `em4285.shopcierge.ai` as mailed-by and
`shopcierge.ai` as signed-by, with TLS. Gmail's stated Spam reason was similarity
to messages identified as spam in the past; this is not evidence of failed
domain authentication. No Spam label or mailbox filtering rule was changed.

The delivery implementation now explicitly sets Reply-To to the advertised
support mailbox, `joshua@segeren.com`, with regression assertions for sandbox
and live messages. SendGrid's official username-recovery flow identified the
legacy account, the saved credential authenticated, and the account owner
completed the text-message challenge. The account initially showed the old
Shopcierge domain authenticated but only a single-sender identity for
`joshua@segeren.com`.

The `segeren.com` sending domain is now fully authenticated. Squarespace's
authoritative DNS returns SendGrid's exact return-path and two DKIM CNAMEs;
SendGrid reported verification success. The existing strict DMARC record was
preserved and link branding was not enabled because commerce mail disables
click tracking. `LAUNCH_FROM_EMAIL` now uses `joshua@segeren.com` for Production
and Preview. Production deployment `dpl_9tkPY8rT5Z91xN8WkWMxk9fGyiwh` and
guarded Preview `dpl_DV9g1dAheijpisyxBVvr3dgps4qr` were deployed after the
configuration change; both availability endpoints remain closed. A new
production launch-intake submission returned 200. SendGrid recorded From
`joshua@segeren.com` and Google's `250 2.0.0 OK` delivery response in two
seconds. The message landed in the Segeren Inbox, where Gmail's expanded
details showed From and Reply-To `joshua@segeren.com`, mailed-by
`em5636.segeren.com`, signed-by `segeren.com`, and TLS. This is direct proof of
the deployed branded sender, domain authentication, Reply-To, and inbox
placement for launch intake. Purchase-delivery inbox placement remains a
separate open acceptance item because the purchase message and delivery path
are different.

### Firewall configuration

The September 5 readback found the existing “Limit launch signups” rule matched
all `/api/` requests, not just signup. Its five-per-ten-minute bucket would also
throttle purchase recovery, analytics and Stripe webhook requests. With no
preexisting draft changes, that rule was narrowed to `/api/signup`, and two
separate per-IP fixed-window rules were added and published on the existing
Codex Migrate project: checkout 10 requests/minute, purchase recovery 60/minute.
Exceeded requests receive HTTP 429, not an interactive browser challenge.
The exact rule inventory is in `ops/commerce-firewall.v1.json`. Readback confirmed
all three enabled and no unpublished changes; other projects were not touched.

A bounded unauthenticated check on the public domain observed checkout's first
10 requests reaching the existing 404 route response and the next two returning
429; purchase's first 60 returned 404 and the next two 429. Eight analytics
requests still returned 200, and eight webhook requests returned the existing
404, not 429. Those commerce routes are not yet deployed to Production; this
proves the edge limits and separation, not functioning paid delivery or webhook
signature handling. No valid signup, payment, or email was submitted. The
buyer scripts handle non-JSON 429 responses with a wait/retry instruction while
retaining checkout retry identity and download recovery access.
After the checkout window expired, a new request again reached the ordinary
404 route response. Real Chromium checks at 320px with explicit HTML 429
fixtures showed the wait instructions without overflow; checkout retained
keyboard focus, and the download page kept Check again available. Screenshots
were inspected. This is responsive/error-state evidence, not an actual payment.

Inspect with `vercel firewall rules list`, `rules inspect <id>` and `diff` before
changing anything. Publish only the reviewed project-specific draft. If a limit
causes legitimate shared-network failures, adjust only that rule's threshold;
do not restore the broad `/api/` signup match or rate-limit Stripe with a buyer
bucket. Per-IP limits can affect shared networks and do not stop distributed
abuse or guarantee a spending cap. Normal Vercel usage charges still apply.

## Upload a signed candidate (operator only)

`ops/commerce-upload.js --build-dir <absolute-build-directory> --release-id <id>`
defaults to a local plan and performs no storage calls. Run with Node 24 or newer.
The directory must be one direct, non-linked child of this repository's `build`
directory. The receipt and archive must be owner-held regular files without
group/world write access. The receipt must name a clean-source release, an
Accepted notarization submission, the canonical release archive name and its
matching SHA-256. The source commit must still exist locally. An unsigned build
is rejected before any upload.

After reviewing the plan, add `--apply` with this product's private Blob
authentication in the environment. It uploads only to `codex-migrate-downloads`,
with public access and overwrite disabled, then independently streams the stored
bytes back and verifies their size and digest. A retry verifies an existing
object without overwriting it. A corrupt existing object stops for operator
review. Exceptions do not print provider credentials or signed URLs.

The result deliberately has `accepted: false`. This utility checks the build
receipt and transport, not the actual Apple signature or application behavior.
Complete the signed-download/clean-Mac checklist against those exact bytes,
then manually review and add the accepted entry to `commerce/releases.json`.
Neither upload nor a passing test toggles checkout. A real signed candidate is
still unavailable: the refreshed Apple account on September 5 remains Pending.

Seventeen upload tests cover receipt/byte rejection, private upload/read-back,
existing-object retry, corruption, and acceptance staying false. They use fake
storage and synthetic bytes, not claims of Apple acceptance. Running the
operator against the existing `desktop-cip8tnrb` unsigned candidate correctly
failed without uploading an app. CI for checkpoint `efc6449` passed both Python
versions before this follow-up.

## Hosted closed-state check

The guarded preview for source `6a1cf4a` deployed successfully at
`https://codex-migrate-ciqg66ao7-joshuas-projects-d3a5c48d.vercel.app`.
POST requests to checkout, purchase and Stripe webhook all returned HTTP 503
with `checkout_closed`, not function-loading errors. This establishes hosted
bundling and closed configuration only; raw-body signature verification still
requires the configured sandbox webhook test. No Production promotion occurred.
The CLI used project-scoped deployment-protection access without printing its
credential. Deployment inputs excluded `.env.local`, app archives, diagnostics,
tests, operator scripts and local dependencies. The subsequent Node 24 pin
prevents Vercel silently choosing a future major runtime.
