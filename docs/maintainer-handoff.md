# Codex Migrate maintainer handoff

This document is the fast, canonical entry point for an engineer taking over
Codex Migrate. It describes the current product and operating state; dated
validation records remain evidence for how that state was reached.

## Product in one paragraph

Codex Migrate is an unofficial, privacy-first Mac-to-Mac migration tool for
local OpenAI Codex work, including Codex in the ChatGPT desktop app. Its promise
is simple: **do not lose your Codex work when you change or upgrade your Mac**.
It moves local conversations, configuration, skills, automations, selected
repositories, branches, worktrees and unfinished files directly between Macs,
then verifies the result. It preserves the receiving Mac's authentication and
installation identity. It is a one-time migration tool, not continuous sync or
a merge engine for two active workspaces.

The free MIT-licensed CLI/source and paid Mac app use the same migration engine
and safety model. The paid edition is the signed, Apple-notarized Apple-silicon
package, a guided browser-first experience, best-effort support from Joshua
Segeren and a 30-day refund policy. It is not a separate closed-source migration
implementation.

## Current live state

As of September 22, 2026 (Pacific time):

- Public site: <https://migrate.segeren.com/>
- Source repository: <https://github.com/jsegeren/codex-migrate>
- Offer: signed and notarized Apple-silicon Mac **beta**, $49 USD one time
- Checkout: open through the existing Segeren Studio Stripe account
- Delivery: entitlement-bound private download after verified payment
- Support: best effort at `joshua@segeren.com`
- Public analytics: the separate Codex Migrate GA4 property; no app or workspace
  analytics
- Current paid artifact: `beta-build15-arm64`
- Artifact filename: `Codex-Migrate-0.1.0-build15-arm64.zip`
- Source commit: `929e65c0b2f24e1b84ca7305895c4312520c720c`
- Archive size: 8,538,406 bytes
- Archive SHA-256:
  `e8a578b4f6a0e58de17325671eb6015d8379f46c5bc55063fdee9fed2f99c8fc`
- Apple notarization submission:
  `bfeca634-8fcc-4356-b792-0487653e8470` (`Accepted`)
- Acceptance label: `founder-approved-paid-beta-2026-09-07`

Build 15 retains the established guided migration and Vault backup views. It
adds thread-identity-aware history, old-title and active-message search,
verified version timelines, guarded selected-thread copy-back, and recovery-key
import. Protection begins after a verified backup, not at installation; the
automatic-protection state also requires a successful scheduled run. Local
backup is not Mac-loss insurance, and the `PreCompact` hook is not shipped.
See [the exact release and physical-test receipt](vault-history-physical-acceptance-2026-09-22.md).
The selected-thread path passed bounded physical two-Mac acceptance while the
receiving Mac remained in use; see
[the selected-thread acceptance receipt](vault-selected-thread-acceptance-2026-09-18.md).

`commerce/releases.json` is the executable release catalog. Do not replace an
existing artifact or remove an old catalog entry: existing purchases remain
bound to the exact artifact they bought.

The beta is intentionally available before broad general-release certification.
Never present it as fully certified, risk-free, or compatible with every Mac,
filesystem, provider state or assistive-technology configuration.

## Safety invariants

These are product law, not implementation suggestions:

1. Inventory and planning are the default; mutation requires explicit apply
   intent.
2. Source data is never deleted.
3. SSH host-key verification is never disabled.
4. Migration data travels directly between the user's Macs, not through the
   Codex Migrate website or commerce backend.
5. The destination is staged before installation.
6. Destination backups and enough free space are verified before replacement.
7. Destination Codex authentication and `installation_id` are preserved.
8. Finalization requires Codex to be closed and the protected sequence to
   complete.
9. Interrupted staging resumes from durable state; interrupted installation
   enters explicit recovery and never infers success from a missing marker.
10. Unknown or contradictory state fails closed with bounded guidance.

Start with [the security model](security-model.md),
[recovery](recovery.md) and [architecture](architecture.md) before changing the
migration engine.

## Repository map

- `src/codex_migrate/` — canonical Python migration, verification, recovery,
  SSH and local-dashboard engine
- `desktop/` — native macOS launcher, packaging and release builder
- `site/` — static public site, local analytics controller and purchase UI
- `api/` — Vercel serverless availability, checkout, purchase, webhook,
  analytics-region and signup endpoints
- `commerce/` — immutable release catalog
- `ops/` — operator-only commerce, artifact, deployment-policy and social-card
  helpers
- `tests/` — Python engine plus Node site/commerce regression coverage
- `docs/` — design, security, recovery, launch, validation and operating
  evidence

The native wrapper deliberately does not implement a second migration UI. It
starts the loopback-only browser application, which owns setup, status,
recovery and support. The dashboard binds to `127.0.0.1` and requires its
random owner token.

## Service map

### GitHub

`jsegeren/codex-migrate` is the public source authority. `main` is the default
branch. GitHub Actions compiles and tests Python 3.9 and 3.12, type-checks the
Swift shell and runs the Node suite. Never publish the paid archive as a public
GitHub asset.

### Vercel and DNS

The public site is the existing Vercel project `codex-migrate`
(`prj_jXmzcjmACVYfAgdNytpAwSuDSCHK`). Static output is `site/`; API routes are
in `api/`. `migrate.segeren.com` is the canonical hostname. Squarespace owns
DNS. Preserve the apex, MX, nameservers, the `migrate` CNAME, strict DMARC and
the SendGrid return-path/DKIM records.

### Stripe

Stripe provides live one-time Checkout. The server verifies a paid session
before issuing access. The live webhook handles completed and asynchronously
paid Checkout events. Keep the
one-item, no-subscription, no-discount contract and the current beta disclosures.
Do not treat a Checkout session as a sale; only verified payment is fulfillment
authority.

### Lakebase Postgres on Neon

The separate project `codex-migrate-commerce` is the purchase/delivery state
authority. It stores Stripe references, buyer email, release binding, delivery
state, attempts and leases. It does not store Codex credentials, workspace data
or analytics identity. Apply schema changes through `ops/commerce-migrate.js`
using a direct connection on a branch first; do not run ad hoc Production DDL.

### Vercel Blob and SendGrid

Paid builds live in private Vercel Blob paths. Upload and read back an exact
checksum with the operator tooling; never expose the object URL. SendGrid sends
the buyer's transactional download email and purchase alerts to
`segerej@gmail.com` and `joshua@segeren.com`. Provider acceptance is not proof
of inbox delivery. Recovery-email delivery remains independent of download
entitlement.

### Apple

Release builds require the existing Developer ID Application identity and an
existing `notarytool` Keychain profile. Secrets stay in the Keychain or private
operator environment, never in Git, Card text, screenshots or command
arguments. The builder can resume the exact saved notarization submission; it
must not rebuild or submit twice after an uncertain outcome.

### Analytics and discovery

The public site uses GA4 property **Codex Migrate** in the Segeren Studio
account (measurement ID `G-1MZ87MY2X4`) and the Search Console URL-prefix
property `https://migrate.segeren.com/`. Outside consent-required markets,
analytics loads by default. In the EEA, United Kingdom and Switzerland it uses
advanced consent mode with a compact choice. Unknown regions fail closed. The
app, local dashboard, conversations and repositories send no analytics.

## Local development and verification

Requirements are macOS, Python 3.9+, OpenSSH, rsync, Git and Node for the public
site/commerce suite. From a clean checkout:

```bash
PYTHONPATH=src python3 -m compileall -q src
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m codex_migrate --version
xcrun swiftc -typecheck -parse-as-library desktop/CodexMigrate.swift desktop/SavedSetup.swift
npm ci --ignore-scripts
npm test
```

The CLI entry point is `./codex-migrate`. Run `./codex-migrate launch` for the
guided local browser flow, `inventory` for content-free source inspection and
`inspect` for read-only destination preflight. Never use a real personal
workspace for destructive or fault-injection tests.

## Release procedure

1. Start from clean, pushed source and record the exact commit.
2. Run the full Python, Swift and Node checks above.
3. Build in release mode with the existing Developer ID signing identity and
   either an unlocked notarytool Keychain profile or an authorized App Store
   Connect Team API key. Do not run a locked profile and ask the Founder to
   guess its password. The Team-key form avoids the *notarization* Keychain;
   it does not bypass the Developer ID signing identity:

   ```bash
   python3 desktop/build.py --release \
     --identity "<Developer ID Application identity>" \
     --notary-profile "<existing notarytool profile>"
   ```

   The alternative flags are `--notary-api-key <absolute owner-only .p8 path>
   --notary-key-id <key ID> --notary-issuer <issuer UUID>`. See
   [desktop setup](desktop-setup.md) for the guarded command and limitations.

4. If Apple submission was already created and the local build record proves
   its identity, resume with `--resume-notarization <build-directory>`; do not
   rebuild or resubmit speculatively.
5. Verify strict code signature, staple, Gatekeeper assessment, packaged-engine
   checks, archive size and SHA-256.
6. Upload through `ops/commerce-upload.js` and independently read back the
   entire private object. The size and SHA-256 must match.
7. Add a new immutable entry to `commerce/releases.json`. Keep previous entries.
8. Point Production configuration at the new accepted release, redeploy the
   existing Vercel project and verify `/api/availability` before touching
   checkout-open state.
9. Exercise the ordinary buyer journey without charging unless a controlled
   purchase is explicitly authorized. Verify disclosures before Pay, then
   verify payment, private delivery, recovery and operator alerts when a real
   transaction exists.
10. Update [release readiness](release-readiness.md), the paid-beta launch
    record and this handoff with exact evidence. Never convert a partial test
    into a broader claim.

Rollback closes **new** checkout and deploys the last validated source. It must
not delete release-catalog entries, private artifacts or existing buyer access.

## Commerce and support operations

- Current operational detail: [commerce implementation](commerce-implementation.md)
- Website, email, analytics and Search Console:
  [website operations](website-operations.md)
- Buyer promise and edition boundaries: [commercial edition](commercial-edition.md)
- Support diagnostics and privacy: [support](support.md)
- Desktop setup and maintainer build notes: [desktop setup](desktop-setup.md)
- Current distribution decision: [paid-beta launch record](paid-beta-launch-2026-09-07.md)
- Current and historical acceptance evidence:
  [release readiness](release-readiness.md)

Do not send or ask for a user's `.codex` directory, workspace, password, private
key or raw terminal log. The app's diagnostic report is local, reviewable and
content-bounded. Preserve customer staging and backups until the issue is
understood.

## Known open work

These are not reasons to close the authorized beta, but they remain honest
limits and useful next tasks:

- receiving-Mac quarantined first-launch and permission recovery coverage
- broader guided macOS permission-recovery acceptance
- physical direct USB-C/Thunderbolt interruption evidence
- broader hardware, filesystem and assistive-technology coverage
- first real-customer end-to-end evidence for payment, buyer delivery email,
  operator purchase alerts, download and migration outcome
- automatic update delivery is not implemented
- Windows and continuous cross-device sync are not supported

The best next product signal is a real buyer's successful migration or a
specific failure report. Avoid speculative feature expansion until that signal
exists.

## Handoff checklist

Before claiming continuity is transferred, the next maintainer should be able
to answer yes to all of these:

- I read `AGENTS.md`, `README.md`, this document, security, recovery and current
  release readiness.
- I can identify the exact live artifact without exposing its private path.
- I understand why destination auth and installation identity are preserved.
- I can run the complete local test suites.
- I know the Stripe, Neon, Blob, SendGrid, Vercel, Apple, GA4 and Search Console
  roles without copying credentials into the repository.
- I know how to close new checkout without breaking existing buyers.
- I will keep historical receipts and clearly label superseded state rather
  than rewriting history.

Owner and public maintainer: **Joshua Segeren**.
