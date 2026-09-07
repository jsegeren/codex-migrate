# Paid beta distribution — September 7, 2026

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

## Exact artifact

- Release ID: `beta-build5-arm64`, explicit `beta` channel.
- Filename: `Codex-Migrate-0.1.0-build5-arm64.zip`; 8,305,628 bytes.
- Source: `48f5194cd008dddf59b35b1e2c78aff74d46720c`.
- SHA-256: `adc126c92952e0031138b199bc2003c18ee08a6a419f2cfe91ea404b84483be7`.
- Notarization: `b8a32506-0c36-49c3-bdc1-e9ce31550e49`, Accepted.
- Private live-store upload and full readback matched exact size and digest.

The catalog's `accepted: true` records this specific distribution approval, not
full clean-Mac or WCAG certification. Sandbox entries remain ineligible for live
sale. The migration engine is unchanged by this commerce release.

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

This is live checkout and exact private artifact verification, not a completed
real-money purchase. Earlier successful sandbox purchase, webhook, email,
download and refund receipts remain test-money evidence. Native clean-Mac and
accessibility checks listed above remain open.

Rollback: set `COMMERCE_CHECKOUT_OPEN=no` and redeploy the validated source.
Keep the release catalog and private artifact available for existing buyers;
closing new sales must not invalidate already-paid download entitlements.
