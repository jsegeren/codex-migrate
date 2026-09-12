# Paid beta distribution — September 8, 2026

## Authorization and boundary

The Founder explicitly approved: “light up the paid download right now and keep
testing in parallel.” This replaces the earlier requirement to finish every
general-release acceptance check before opening self-service sales. It does not
mark those checks passed or complete the overarching release goal.

The purchase is $49 USD one time for the current Apple silicon Mac beta,
including best-effort maintainer support and a 30-day refund policy. Signing,
notarization, mandatory verified backups, strict SSH, payment verification and
private entitlement-bound delivery remain enforced. Finalization replaces
selected data; it does not merge two independently active workspaces. Buyers
must retain their old Mac and an independent backup.

## Price update — September 10, 2026

The Founder set the ongoing one-time price at **$49 USD**. Stripe price
`price_1UEMgFJfbWpcJIZbPsmXjF2J` was created on the existing live product and
made its default price. The prior $50 price remains recorded as a legacy live
price so a valid earlier payment cannot lose download access after the catalog
change. The checkout still permits one item, no subscription and no discount;
tax may be added separately. The dated $50 observations below remain historical
receipts rather than descriptions of the current offer.

## Current exact artifact

- Release ID: `beta-build9-arm64`, explicit `beta` channel.
- Filename: `Codex-Migrate-0.1.0-build9-arm64.zip`; 8,307,597 bytes.
- Source: `8f1e0225a6babcb1be1be0a876da11edd73732d8`.
- SHA-256: `7aadccacec63b09fe637cd61c506f4730f2de62163687ec56a2cc63ad8306133`.
- Notarization: `9ddf03b5-c947-4d97-a598-d71519e179d9`, Accepted.
- Private live-store upload and full readback matched exact size and digest.

The catalog's `accepted: true` records this specific distribution approval, not
full clean-Mac or WCAG certification. Sandbox entries remain ineligible for live
sale. Build 9 retains build 8's migration behavior and atomic destination Codex
identity preservation while correcting the observed IPv6 hardware-route label.
Its fault-injection, complete-suite, exact packaged executable, signature,
staple and Gatekeeper evidence is recorded in
[installer interruption validation](identity-interruption-validation-2026-09-07.md).

## Remaining validation

Receiving-Mac quarantined first launch/permissions, the guided permission-
recovery journey, physical USB-C/Thunderbolt interruption and broader
hardware/provider compatibility remain open. The exact build 9 engine has
failed closed on a real TCC-protected workspace selection without printing
protected content. Its key setup, connection, recovery and diagnostic controls
also passed a spoken VoiceOver walkthrough, and an isolated 256 MiB transfer
resumed after the destination Wi-Fi radio was physically powered off and back
on, then matched the source hash exactly without finalization. The website and
hosted Checkout continue to disclose the beta boundary before payment. Existing
real-device automated recovery, unexpected SSH loss/restart, pause/stop/resume
and browser skills-repair receipts remain separately scoped.

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

## Build 9 hardware-route correction and promotion

A September 10 isolated two-Mac hardware run staged a unique 512 MiB skill over
the real Wi-Fi/Bonjour route, paused after 4 KiB, resumed the same migration and
matched the staged payload byte-for-byte. The run did not finalize or touch the
owner's active destination Codex workspace. It exposed one cosmetic defect:
macOS IPv6 route inspection requires an explicit address family, so the working
Wi-Fi path was displayed as `unknown`. Source `8f1e0225a6babcb1be1be0a876da11edd73732d8`
corrects that label and adds regression coverage without changing transfer,
backup, installation or verification behavior.

Build 9 was produced from that clean pushed source, signed with Developer ID,
accepted by Apple notarization submission `9ddf03b5-c947-4d97-a598-d71519e179d9`,
stapled and accepted by Gatekeeper. Eleven exact packaged-engine checks passed
with one expected case-sensitive-filesystem skip. Its 8,307,597-byte archive
has SHA-256 `7aadccacec63b09fe637cd61c506f4730f2de62163687ec56a2cc63ad8306133`.
The private live-store upload was independently read back with the same size
and digest. The existing paid-beta authorization applies to this narrowly
corrected build; older catalog entries and objects remain available for their
existing entitlements. Production deployment
`dpl_2cwsjH18CyecqkKjsxmvwSdZaoUn` reached READY and was aliased to
`migrate.segeren.com` with `COMMERCE_RELEASE=beta-build9-arm64`; a subsequent
availability read remained open at $50 for Apple silicon on the beta channel.

## Build 9 physical interruption and VoiceOver observations

On September 10, an isolated 256 MiB workspace-skill transfer used the current
build 9 source and a real Wi-Fi route to the receiving Mac. The destination
Wi-Fi radio was powered off for 18 seconds during active staging. The control
SSH connection failed, no installation or finalization began, and the browser
workflow remained safely in staging. After Wi-Fi returned, staged bytes
advanced within the same scope. An explicit Pause retained 19,996,672 bytes;
reopening the same durable migration and rerunning preflight completed staging
at 268,541,952 bytes. The staged payload matched source SHA-256
`91f82081150ad7417f06b75e857020347ab575e5a884b43ed48f3abef93b59fd`.
The private receipt is
`/Users/Shared/CodexMigrate-PhysicalDrop-20260910-0422.json`. Finalization was
not attempted, no personal workspace was selected, and disposable local and
remote test data were moved to Trash after verification.

The exact distributed build 9 launcher was then opened with macOS VoiceOver and
the VoiceOver caption panel enabled. Keyboard navigation produced the expected
spoken labels and roles for Help / Email support, receiver mode, Create
connection card, existing SSH, fresh connection, Continue, recovery options,
the support email and Prepare diagnostic report. Collapsed state and group or
region context were announced where applicable. This is direct spoken
screen-reader evidence for the key setup and recovery controls, not a claim of
complete assistive-technology or every-state certification. The private
observation receipt is `/Users/Shared/CodexMigrate-VoiceOver-20260910.md`.

## Build 10 focused-interface promotion

Build 10 packages the Founder-reviewed, simplified browser interface from
clean pushed source `c3e398b23d0a0d913bd7567e7d3e512c1d0e0e01`. The migration,
backup, replacement and verification machinery is unchanged; the dashboard now
shows only the actions relevant to the current state, moves detailed scope and
backup information behind disclosures, and uses shorter status labels.

The Apple-silicon app was signed with Developer ID, accepted by Apple
notarization submission `0ca60a10-15d3-41a3-8af7-502fe0f730d6`, stapled and
accepted by Gatekeeper. Eleven exact packaged-engine checks passed with one
expected case-sensitive-filesystem skip. The 8,308,464-byte archive has SHA-256
`f5a1634380c386c3c0c4bfdcab65270cd45c7ffe151b7378d01b9a8be1e6a739`.
The private live-store upload was streamed back and matched that exact size and
digest. The existing Founder authorization for the paid beta applies to this
interface-only successor; existing purchases remain bound to their original
catalogued artifacts.
