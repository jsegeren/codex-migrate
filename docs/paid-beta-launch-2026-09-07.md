# Paid beta distribution — September 8, 2026

## Authorization and boundary

The Founder explicitly approved: “light up the paid download right now and keep
testing in parallel.” This replaces the earlier requirement to finish every
general-release acceptance check before opening self-service sales. It does not
mark those checks passed or complete the overarching release goal.

The purchase is $50 USD one time for the current Apple silicon Mac beta,
including best-effort maintainer support and a 30-day refund policy. Signing,
notarization, mandatory verified backups, strict SSH, payment verification and
private entitlement-bound delivery remain enforced. Finalization replaces
selected data; it does not merge two independently active workspaces. Buyers
must retain their old Mac and an independent backup.

## Current exact artifact

- Release ID: `beta-build8-arm64`, explicit `beta` channel.
- Filename: `Codex-Migrate-0.1.0-build8-arm64.zip`; 8,308,390 bytes.
- Source: `f429bf6c234d7b9f925c61f389d6d0513de301fb`.
- SHA-256: `74a7fc5e2da91901f4a5d3f74969cd03d34549ef6f06d83151825d7727262270`.
- Notarization: `0992a488-b7fb-415d-a5c2-768bf3707f1c`, Accepted.
- Private live-store upload and full readback matched exact size and digest.

The catalog's `accepted: true` records this specific distribution approval, not
full clean-Mac or WCAG certification. Sandbox entries remain ineligible for live
sale. Build 8 retains build 7's atomic destination Codex identity preservation
across an installer interruption and corrects the packaged offline guide to
describe the available paid beta accurately. Its fault-injection,
complete-suite, exact packaged executable, signature, staple and Gatekeeper evidence is recorded in
[installer interruption validation](identity-interruption-validation-2026-09-07.md).

## Remaining validation

Native VoiceOver, receiving-Mac quarantined first launch/permissions, physical
cable removal/Wi-Fi interruption and broader hardware/provider compatibility
remain open. The website and hosted Checkout disclose ongoing native
accessibility, permissions and physical network-interruption testing before
payment. Existing real-device automated recovery, unexpected SSH loss/restart,
pause/stop/resume and browser skills-repair receipts remain separately scoped.

## Activation record

Live at <https://migrate.segeren.com/#founding-edition>.

- Source deployed: `cd9f53c3118b0e65e0266cf852e55ed1c2992774`.
- Closed preflight deployment: `dpl_43EhFcmPg2mp7eMindF4nZEJebH8`.
  Actual production credentials verified the live account, product, $50
  one-time price, database identity and private build-5 download. Full readback
  matched the checksum; anonymous access was denied. One unpaid live Checkout
  probe was created and expired, without supplying payment details or charging.
- Paid-beta deployment: `dpl_5Dh2w27yiYvxdLxUvmzZiGAPDr4W`, READY and aliased to
  the canonical domain. `COMMERCE_CHECKOUT_OPEN=yes` and
  `COMMERCE_RELEASE=beta-build5-arm64`.
- Canonical availability returns `available:true`, `priceUSD:50`,
  `architecture:arm64`, `channel:beta`.
- Existing Stripe product `prod_VCxpogUxaT0OeT` renamed “Codex Migrate — Mac
  Beta”; the existing $50 price is unchanged. Existing webhook
  `we_1UCbMoJfbWpcJIZbbNI7EmYl` is Active for the completed and asynchronous-paid
  Checkout events. No secret was rotated and no unrelated product was changed.
- Native Chrome displayed the live beta purchase card and followed its actual
  Buy button to hosted Stripe Checkout. Product name, $50 price, hardware,
  support/refund and remaining-test disclosures were present before Pay.
  No payment details were entered and Pay was not pressed; the browser returned
  to the site. This final browser-generated unpaid session can expire normally.
- Node suite: 277 tests, 276 passed, one skipped, zero failures. Coverage includes
  beta approval boundaries, hosted Checkout disclosures, UI labels, delivery
  email, and refusal of unreviewed artifacts.
- GitHub's default-branch README and commercial policy now advertise the live
  beta; focused documentation commit `5a1cdde6e42fb123ff57123397d393dbf49793c4`.
  Repository description also points to the $50 signed beta. This documentation
  update did not bulk-merge the separate engineering branch or trigger a new
  website deployment (the existing Vercel project has no Git repository link).

This is live checkout and exact private artifact verification, not a completed
real-money purchase. Earlier successful sandbox purchase, webhook, email,
download and refund receipts remain test-money evidence. Native clean-Mac and
accessibility checks listed above remain open.

## Build 7 paid-beta promotion

The original paid-beta launch distributed build 5. After build 7's interruption
fix passed its recorded acceptance checks, the exact build 7 archive was uploaded
to the live private store without overwriting build 5 and independently streamed
back with matching 8,307,584-byte size and SHA-256. Public source commit
`dd6715e151270970f580d9bd8960f09ca5baf63b` contains the same focused engine
change on `main`; hosted CI run `34188310627` passed on Python 3.9 and 3.12.

Production deployment `dpl_EcGdL2LMtG4SNdMsZtB586rgCnRd` reached READY and was
aliased to the canonical domain with `COMMERCE_RELEASE=beta-build7-arm64`.
Canonical availability remained open at $50 for Apple silicon on the beta
channel. A new production Checkout probe returned an HTTPS Stripe Checkout URL
for a live-mode session; no payment details were supplied and no charge or
fulfillment was created. The prior build 5 catalog entry and private object are
retained so existing entitlements continue to recover their originally purchased
artifact.

## Build 8 customer-copy correction and promotion

The distributed build 7 archive contained an obsolete offline sentence saying
paid downloads were unavailable even though checkout was live. Build 8 removes
that contradiction and adds a regression test requiring the packaged guide to
name the signed $50 beta, the complete free MIT-licensed CLI/source, best-effort
support and the 30-day refund policy. The migration engine and native launcher
source are unchanged from build 7.

Build 8 was signed, notarized, stapled and Gatekeeper accepted. Eight exact
packaged-engine desktop checks passed; the ninth, a case-sensitive-filesystem
fixture, was skipped as expected on this Mac. A real Chromium test against the
packaged helper opened Help, prepared a bounded local diagnostic report,
displayed it for review and downloaded it without exposing private paths,
tokens or passwords and without uploading or emailing anything automatically.
Focused build and desktop tests passed 23 checks with one expected
case-sensitive-filesystem skip. The full Python suite passed 729 checks with 12
skips before packaging; the build 8 migration engine is unchanged from that
tested source. Catalog-focused Node tests passed 87 of 87, following the prior
full 279-test Node pass with one database-dependent skip.

The exact build 8 archive was uploaded to a new private object path and streamed
back independently with matching 8,308,390-byte size and SHA-256. Production
deployment `dpl_ELKgxYbJgSnBxQMRwQzL4EME5mZ2` reached READY and was aliased to
the canonical domain with `COMMERCE_RELEASE=beta-build8-arm64`. Availability
remained open at $50 for Apple silicon on the beta channel. A production
Checkout probe returned a valid Stripe-hosted URL; no payment details were
supplied and no charge was made. Build 5 and build 7 remain private and
catalogued so existing entitlements continue to recover the artifacts they
originally purchased.

Rollback: set `COMMERCE_CHECKOUT_OPEN=no` and redeploy the validated source.
Keep the release catalog and private artifact available for existing buyers;
closing new sales must not invalidate already-paid download entitlements.
