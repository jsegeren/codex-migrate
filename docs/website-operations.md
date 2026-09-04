# Website and launch intake

The public site is deployed to the existing `codex-migrate` Vercel project.
Its canonical hostname is `migrate.segeren.com`; Squarespace manages DNS.
Only the `migrate` CNAME is required. Do not change the apex site, mail records,
or nameservers. Static output is `site/`; `api/signup.js` is a Node function.

## Email configuration

Production-only sensitive environment variables:

- `SENDGRID_API_KEY`: existing authorized SendGrid sending credential.
- `LAUNCH_FROM_EMAIL`: existing verified sender, branded Codex Migrate.
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
