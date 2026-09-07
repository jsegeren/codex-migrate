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

Pending production deployment and final live checkout verification. Do not
interpret this authorization record as evidence that checkout is already open.

Rollback: set `COMMERCE_CHECKOUT_OPEN=no` and redeploy the validated source.
Keep the release catalog and private artifact available for existing buyers;
closing new sales must not invalidate already-paid download entitlements.
