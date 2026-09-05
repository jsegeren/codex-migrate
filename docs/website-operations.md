# Website and launch intake

The public site is deployed to the existing `codex-migrate` Vercel project.
Its canonical hostname is `migrate.segeren.com`; Squarespace manages DNS.
The `migrate` CNAME serves the site. Three additional CNAMEs authenticate
`segeren.com` for SendGrid (return path plus two DKIM selectors); preserve them
with the existing strict DMARC record. Do not change the apex site, MX records,
or nameservers. Static output is `site/`; `api/signup.js` is a Node function.

## Email configuration

Production-only sensitive environment variables:

- `SENDGRID_API_KEY`: existing authorized SendGrid sending credential.
- `LAUNCH_FROM_EMAIL`: `joshua@segeren.com`, on the authenticated sender domain.
- `LAUNCH_NOTIFY_EMAIL`: fixed maintainer inbox.

Never put these values in Git, browser code, screenshots, or command logs.
The endpoint accepts same-origin URL-encoded POSTs, one validated address,
explicit launch-only consent, and an empty honeypot. It sends a fixed plain-text
message to the maintainer only. No visitor autoresponder, payment, or bulk
newsletter is created. Open/click tracking is disabled for the notification.

Success means SendGrid returned 202, not proof of inbox delivery. Error and
timeout responses never claim success, and ambiguous sends are not retried
automatically. The maintainer mailbox is the request store; there is no separate
database or guaranteed delivery queue. No address is reflected in the response
or logged by application code. Hosting and email providers still process requests.

The production Vercel Firewall must enforce the `Limit launch signups` rule:
five requests per IP per 600 seconds, fixed window, rate-limit on exceed. Inspect
and publish only this project's intended rule changes. Do not substitute an
in-memory limiter, which would reset across serverless instances. Distributed
abuse remains possible; disable intake by removing the sending credential if
necessary. Monitor the maintainer inbox and SendGrid sending activity.

Josh must deduplicate requests, confirm address ownership before launch mail,
honor opt-outs, and remove launch requests after the requested notice. The form
does not authorize unrelated marketing. Early-build requests remain individual
email conversations and never automatically deliver an unsigned app.

## Checks and deployment

Run `node --test tests/signup.test.js` and the Python test suite. Check desktop
and mobile layout, keyboard labels, consent, successful delivery, and failure
messages. Test actual sending only to the maintainer's controlled address.
Verify the receipt in the inbox; remove test entries from any manual launch list.

On September 5, 2026, Squarespace's authoritative DNS returned all three
SendGrid CNAMEs and SendGrid confirmed `segeren.com` as authenticated. The
existing DMARC policy was unchanged. Production and Preview sender configuration
now use `joshua@segeren.com`; both environments require a deployment made after
that configuration change.

Deploy through the linked Vercel project, then check the custom hostname, TLS,
signup endpoint, `robots.txt`, `sitemap.xml`, and canonical links. Search-engine
discovery is enabled; this does not guarantee Google indexing or ranking.

## Search Console

The URL-prefix property `https://migrate.segeren.com/` was added and ownership
automatically verified through the existing domain-provider setup on September
4, 2026. No DNS records, website verification files, or unrelated properties
were changed. Keep the existing verification DNS record in place.

The canonical `/sitemap.xml` was submitted successfully. Search Console reported
**Success**, a September 4 last-read date, and **6 discovered pages**: the
homepage, two guides, and three legal pages. Discovery is not indexing. Use this
exact property when inspecting URLs or submitting future sitemap changes.

Homepage inspection initially reported **Discovered - currently not indexed**.
After its live eligibility check, Google accepted the indexing request and
reported that the homepage was added to a priority crawl queue. Do not repeatedly
submit the same URL; this does not improve queue priority. Actual indexing and
ranking remain unverified and are not guaranteed.

All six live pages returned HTTP 200 with matching self-canonicals, one H1,
and no HTML or response-header `noindex` directive during this check.

## Website analytics

Google Analytics is configured under the existing **Segeren Studio** account as
the separate **Codex Migrate** GA4 property. Its web stream is **Codex Migrate
website** for `https://migrate.segeren.com` (measurement ID `G-1MZ87MY2X4`).
The measurement ID is public configuration; no Analytics API credential belongs
in the repository.

The local `site/analytics.js` regional controller is the only supported loader.
It queries the same-origin `/api/analytics-region` endpoint, which maps Vercel's
edge-provided country code to either `default` or `consent` without returning or
retaining the country. Unknown locations fail closed. The production tag does
not load on localhost or an unrecognized hostname.

Full GA4 measurement is enabled by default outside the EEA, United Kingdom and
Switzerland. In those consent-required markets, the tag starts in advanced
consent mode with analytics and advertising storage denied, sends only
cookieless measurement pings, and shows a compact 360px corner choice. **Allow**
enables full measurement; **Decline** retains cookieless measurement and clears
Codex Migrate-specific cookies. Explicit choices persist in browser local
storage and can be changed from the footer. There is no global consent banner.
This is public-website measurement only: the CLI, Mac app, local dashboard,
migration state, conversations and repositories do not send analytics.

The intentionally small event model is:

- automatic page views and GA enhanced measurement, subject to the regional
  storage mode;
- `select_free_cli` for the primary open-source calls to action;
- `select_launch_email` for the homepage launch-email call to action;
- `select_you_one` for the separate You.one cross-promotion; and
- `generate_lead` only after SendGrid accepts a valid launch-email request.

`generate_lead` is configured as a GA4 key event with no monetary value. The
property's Search Console link uses the exact
`https://migrate.segeren.com/` URL-prefix property and the Codex Migrate web
stream. This unlocks native acquisition and organic-search reporting once data
arrives.

Privacy and reporting settings were reviewed on September 4, 2026. Google
Signals is enabled for aggregate demographics, interests and cross-device
insights from eligible visitors with full measurement; user-provided data remains off, and the site
does not send signup emails or other user IDs to GA. Ads personalization remains
disallowed in all regions. Event and user retention are both 14 months and user
retention resets on new activity. When storage is granted, the tag uses Codex
Migrate-specific, host-only cookies with a 14-month expiry that refreshes for
returning-user continuity.
Granular location/device reporting remains enabled for the approximate
city/region, browser and device reporting disclosed in the privacy policy.

Use GA's native Home, Realtime, Acquisition and Events/Key events reports as the
initial dashboard. They cover visits, source/medium, devices/regions, CTA events
and launch-request conversion rate without adding another credential-bearing
application. Build a custom exploration only after enough real traffic exists
to define useful questions; do not create a public dashboard or expose the
Analytics Data API merely to duplicate the native reports.

## Paid checkout: sandbox evidence, not a live release

On September 4, 2026, the existing **Segeren Studio sandbox** in Stripe was
used to create **Codex Migrate — Founding Edition (TEST ONLY)** at **$50 USD,
one time**, fixed quantity one. The existing live account, its products, and
unrelated sandbox products were not changed. No keys were copied or created.

The actual hosted test checkout—not just its dashboard preview—accepted
Stripe's documented fictional test card. A reserved example.com test address
and fictional tester name were used, saved-payment signup was disabled, and
agent operation was disclosed. Stripe recorded the payment as **Succeeded**.
A full sandbox refund then changed that same payment to **Refunded**, with a
note identifying the acceptance test. No real money moved and no receipt email
was sent. The confirmation explicitly said no app was delivered or released.

The sandbox Payment Link was subsequently **Deactivated** and can be reactivated
for further acceptance testing. Locate it by the exact test-product name in the
sandbox's Payment Links list; do not create duplicate links or use **Copy to
livemode** as a release shortcut. No checkout link was added to the public site.

This proves the basic hosted sandbox card-payment and manual-refund path only.
It does **not** prove app delivery, receipt email delivery, purchase recovery,
declines, delayed payment methods, tax compliance, or live payment readiness.
The test used the existing default payment-method configuration and no automatic
tax. Those choices must not be copied to live sales without review.

### Payment provider decision (September 5, 2026)

The Founder selected the **existing Stripe account** to avoid another provider
account. This supersedes the earlier Lemon Squeezy recommendation. Reuse the
existing Codex Migrate sandbox product and keep You.one's products, prices,
webhooks, subscriptions, and shared billing defaults unchanged. Do not create a
Lemon Squeezy account or duplicate the existing test checkout.

Evaluate **Stripe Managed Payments** for the Codex Migrate transactions only.
Provider choice does not establish live account approval, accept additional
terms, or enable paid checkout. Ordinary Stripe payment processing and Stripe
Tax must not be described as merchant-of-record coverage. Such coverage also
does not transfer our product-safety, privacy, or maintainer-support obligations.

For a $50 one-time download, the current public comparison is:

| Option | Published transaction price | Approximate fee on a $50 domestic-card sale | Relevant fit |
| --- | --- | --- | --- |
| Lemon Squeezy | 5% + 50¢, no monthly payment-processing fee | $3.00 | Merchant of record; directly hosts digital files up to 5 GB per product, supports one-time license keys, and signs webhooks. |
| Paddle | 5% + 50¢, no monthly fee | $3.00 | Merchant of record; supports one-time downloadable software, with fulfillment driven by a signed `transaction.completed` webhook. |
| Stripe Managed Payments | 3.5% in addition to ordinary Payments fees | About $3.50 using Stripe's current 2.9% + 30¢ US domestic-card price | Merchant of record; supports eligible downloadable software and requires account activation and a Managed Payments checkout. |

The earlier Lemon Squeezy recommendation favored bundled tax handling and
hosted downloads. The Founder prefers reusing Stripe; the modest illustrative
fee difference above is not a sufficient reason to add another account.
Stripe still requires our own verified artifact-delivery flow. If Managed
Payments is unavailable, report the specific account/product limitation and
resolve the tax arrangement before live sales; do not silently switch providers
or represent standard Checkout as equivalent.

Stripe's current setup documentation enables Managed Payments per Checkout
Session with `managed_payments[enabled]=true`, allowing unrelated payments to
remain unchanged. Eligibility is account- and product-specific. The software
must have an eligible downloaded-software tax category, not a SaaS category
chosen merely to complete onboarding. Check the treatment of incidental
best-effort support before activation: Stripe excludes separately sold
professional/technical-support services and requires automated digital delivery.

Official references: [Lemon Squeezy pricing](https://www.lemonsqueezy.com/pricing),
[digital files and license keys](https://docs.lemonsqueezy.com/help/products/adding-products),
[signed webhooks](https://docs.lemonsqueezy.com/help/webhooks/signing-requests),
[Paddle pricing](https://www.paddle.com/pricing),
[Paddle one-time digital products](https://developer.paddle.com/get-started/how-paddle-works/digital-products/),
[Stripe pricing](https://stripe.com/pricing), and
[Managed Payments eligibility and behavior](https://docs.stripe.com/payments/managed-payments/how-it-works).

### Remaining commerce work

See [the September 5 implementation and verification record](commerce-implementation.md)
for the new guarded checkout/webhook/delivery code and isolated sandbox database.
Its release catalog is intentionally empty and hosted commerce is not activated.

#### Sandbox operator helper (not deployed to the website)

`node ops/stripe-sandbox-checkout.js` reads the configured Stripe account and
expanded price/product and verifies the exact active, test-only $50 USD
one-time catalog entry. It does not create or change anything by default.
With `--create`, it creates one sandbox Checkout Session with Managed Payments
enabled explicitly. The existing TEST ONLY product carries the no-app-delivered
disclosure; Managed Payments rejects Checkout's `custom_text` option. It never completes a
payment, creates a product, changes account defaults, or creates a subscription.

Configure these environment variables privately in the operator's process:

- `CODEX_MIGRATE_STRIPE_TEST_KEY`: sandbox restricted key, not a live key.
- `CODEX_MIGRATE_STRIPE_TEST_ACCOUNT`: expected sandbox account ID.
- `CODEX_MIGRATE_STRIPE_TEST_PRODUCT`: existing TEST ONLY product ID.
- `CODEX_MIGRATE_STRIPE_TEST_PRICE`: its existing $50 one-time USD price ID.

Do not put credentials in command arguments, Git, public environment variables,
screenshots, or diagnostic reports. The helper returns only status and, after a
verified create, the sandbox session ID. Open its hosted checkout from Stripe's
dashboard; do not add it to the public website. Run it with Node 24 or newer.
It requires read access to the account, product and price, and Checkout Session
write access only for `--create`. Use scoped sandbox access, not You.one's live
credentials. A timeout is ambiguous: inspect the dashboard before rerunning.
Each explicit run can create a new test session; this is not a durable purchase
fulfillment or retry queue.

The local fixtures verify guards and request construction, not Stripe account
activation or API acceptance. The existing sandbox catalog currently reports
the test product eligible under General - Electronically Supplied Services.
That code is allowed for this test helper; choose the correct specific
downloaded-software category for the eventual live product after tax review.
The signed artifact, fulfillment, recoverable customer download, and real
Managed Payments payment/refund acceptance remain separate release gates.

Account inspection on September 5 found the existing live account's legal
business name **Joshua Segeren**, public name **Segeren Studio**, and website
**segeren.com**. Managed Payments onboarding is offered in both the live account
and its existing sandbox; it has not been activated. Merely seeing onboarding
does not prove final approval. Onboarding drafts were opened and saved without
creating live products, accepting terms, or changing the shared tax category.
The existing sandbox product remains unchanged and its old Payment Link remains
deactivated. After explicit Founder confirmation, an agent-labelled restricted
sandbox key was created with Accounts/Products/Prices read access and Checkout
Sessions write access. It was stored only in a private owner-only local file
(mode 600, parent directory 700), not Git, Vercel, chat, or shell arguments.
No standard key was copied and no live credential was used.

September 5 API verification: the restricted key successfully read the expected
account and exact $50 test catalog entry. The first create request returned 400
because Managed Payments disallows `custom_text`. After removing that option
and adding a regression assertion, one subsequent request created a session
verified as test-mode, open, one-time payment, and Managed Payments enabled.
No ordinary-checkout fallback or automatic retry was performed. Sandbox API
acceptance does not prove live activation, successful payment, or fulfillment;
no payment was completed through this Managed Payments session.

Verification: all 25 isolated helper tests and all 56 Node tests passed.
The helper is operator tooling outside `api/` and is not a website endpoint.

#### Activation and release

- Confirm the existing Stripe account's legal seller and Managed Payments
  eligibility/terms before live sales. Provider selection is complete; do not
  ask the Founder to choose Stripe again. Do not silently accept vendor terms,
  create a live product, or change shared Stripe settings.
- Implement server-verified purchase fulfillment, not a success-page redirect
  treated as proof of payment. Scope events to this exact product/price and
  environment; verify webhook signatures and paid status; handle retries and
  duplicate events without granting unrelated access or losing delivery.
- Deliver the exact reviewed, signed/notarized, checksummed release artifact,
  with a way to recover the download after closing the browser. Never substitute
  an unsigned build or a mutable unverified ZIP.
- Test paid and unpaid events, replay/duplicate handling, download and email
  failures, browser closure, support requests and refunds. Transaction emails
  must not enroll purchasers in launch or You.one marketing lists.
- Review seller/support details, privacy/terms/refund links, allowed payment
  methods and tax behavior before enabling a live $50 checkout. Customer payment
  data and private webhook/signing credentials never belong in Git.

References: [Stripe sandbox testing](https://docs.stripe.com/testing),
[payment fulfillment](https://docs.stripe.com/checkout/fulfillment), and
[Managed Payments responsibilities](https://docs.stripe.com/payments/managed-payments/how-it-works).
